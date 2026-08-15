"""MNQ Overnight Volume Profile Signal System — Main Entry Point.

Orchestrates all modules: data acquisition, analytics, signal generation,
dashboard display, Telegram alerts, and optional auto-trading.
"""
from __future__ import annotations

import asyncio
import logging
import signal as os_signal
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from rich.live import Live
from rich.console import Console
from rich.logging import RichHandler

from core.config import load_config
from core.connection import ConnectionManager
from core.contracts import ContractManager
from data.historical import HistoricalDataFetcher
from data.tick_stream import TickStreamManager
from analytics.volume_profile import VolumeProfileCalculator
from analytics.trade_classifier import TradeClassifier
from analytics.footprint import FootprintAggregator
from analytics.absorption import AbsorptionDetector
from strategy.signal_engine import SignalEngine
from output.dashboard import Dashboard
from output.webhook import TelegramNotifier
from trading.auto_trader import AutoTrader

logger = logging.getLogger("mnq")

ET = ZoneInfo("America/New_York")


async def main():
    # ── Logging ──────────────────────────────────────────────────────
    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=True, show_path=False)],
    )

    console = Console()
    console.print("\n[bold cyan]⚡ MNQ Signal System v1.0[/bold cyan]\n")

    # ── Config ───────────────────────────────────────────────────────
    config_path = Path(__file__).parent / "config.toml"
    config = load_config(config_path)
    logger.info("Configuration loaded.")

    # ── IBKR Connection ──────────────────────────────────────────────
    conn_mgr = ConnectionManager(config.connection)
    await conn_mgr.connect()
    ib = conn_mgr.ib
    logger.info(f"Connected. Server version: {ib.client.serverVersion()}")

    # ── Contract Resolution ──────────────────────────────────────────
    contract_mgr = ContractManager(ib, config.contract)
    contract = await contract_mgr.resolve()
    tick_size = config.frvp.tick_size
    logger.info(f"Contract: {contract.localSymbol}  (tick={tick_size})")

    # ── FRVP Calculation ─────────────────────────────────────────────
    fetcher = HistoricalDataFetcher(ib, contract, config.frvp)
    overnight_bars = await fetcher.fetch_overnight_bars()

    vp_calc = VolumeProfileCalculator(
        tick_size=tick_size,
        value_area_pct=config.frvp.value_area_pct,
        algorithm=config.frvp.algorithm,
    )
    frvp = vp_calc.calculate_from_bars(overnight_bars)
    logger.info(
        f"FRVP → POC: {frvp.poc:.2f}  VAH: {frvp.vah:.2f}  "
        f"VAL: {frvp.val:.2f}  VA%: {frvp.va_pct_actual*100:.1f}%"
    )

    # ── Analytics Pipeline ───────────────────────────────────────────
    classifier = TradeClassifier(tick_size=tick_size)
    footprint = FootprintAggregator(
        tick_size=tick_size,
        big_trade_threshold=config.orderflow.big_trade_threshold,
    )
    absorption = AbsorptionDetector(config=config.orderflow, tick_size=tick_size)

    # ── Signal Engine ────────────────────────────────────────────────
    engine = SignalEngine(config=config.signal, tick_size=tick_size)
    engine.set_frvp(frvp)

    # Set post-open cooldown (09:30 + cooldown_secs ET)
    now_et = datetime.now(ET)
    open_time = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
    cooldown_end = open_time + timedelta(seconds=config.signal.cooldown_after_open_secs)
    if now_et < cooldown_end:
        engine.set_cooldown(cooldown_end)
        logger.info(f"Cooldown active until {cooldown_end.strftime('%H:%M:%S')} ET")

    # ── Output Layer ─────────────────────────────────────────────────
    dashboard = Dashboard(config.dashboard)
    dashboard.update_frvp(frvp)
    dashboard.auto_trade_on = config.signal.auto_trade_enabled
    dashboard.webhook_on = config.webhook.telegram_enabled
    dashboard.set_connected(True)
    dashboard.set_status("Running")

    telegram = TelegramNotifier(config.webhook)
    if config.webhook.telegram_enabled:
        await telegram.start()

    auto_trader = AutoTrader(ib, contract, config.signal)

    # ── Tick Stream ──────────────────────────────────────────────────
    tick_stream = TickStreamManager(ib, contract)

    # ── Cumulative session counters ──────────────────────────────────
    session = {"cum_delta": 0.0, "buy_vol": 0.0, "sell_vol": 0.0, "big_trades": 0}

    # ── Wiring: Trade ticks → Classifier → Footprint ────────────────
    def on_trade_tick(timestamp: datetime, price: float, size: float):
        """Called for every AllLast tick."""
        trade = classifier.classify(
            timestamp=timestamp,
            price=price,
            size=size,
            bid=tick_stream.best_bid,
            ask=tick_stream.best_ask,
        )
        footprint.add_trade(trade)
        absorption.update_dynamic_threshold(size)

        # Update session counters
        if trade.direction == 1:
            session["cum_delta"] += size
            session["buy_vol"] += size
        else:
            session["cum_delta"] -= size
            session["sell_vol"] += size

        dashboard.update_price(price, tick_stream.best_bid, tick_stream.best_ask)

    def on_quote_tick(timestamp: datetime, bid: float, ask: float, bid_size: float, ask_size: float):
        """Called for every BidAsk tick."""
        dashboard.update_price(dashboard.last_price, bid, ask)

    tick_stream.on_trade.append(on_trade_tick)
    tick_stream.on_quote.append(on_quote_tick)

    # ── Wiring: Footprint bar complete → Absorption → Signal Engine ─
    def on_bar_complete(bar):
        """Called when a 1-min footprint bar finalises."""
        # Update dashboard orderflow stats
        bar_buy = sum(bar.ask_vol_by_tick.values())
        bar_sell = sum(bar.bid_vol_by_tick.values())
        session["big_trades"] += bar.big_trade_count

        dashboard.update_orderflow(
            delta=session["cum_delta"],
            buy_vol=session["buy_vol"],
            sell_vol=session["sell_vol"],
            big_trades=session["big_trades"],
        )
        dashboard.current_bar = bar

        # Check for absorption events
        events = absorption.check_bar(bar, frvp)
        for event in events:
            engine.on_absorption_event(event)
            logger.info(
                f"🔔 Absorption: {event.signal_type} at {event.price_level:.2f} "
                f"(vol={event.absorbed_volume:.0f}, ratio={event.imbalance_ratio:.1f})"
            )

        # Run signal engine
        engine.on_bar_complete(bar)

    footprint.on_bar_complete.append(on_bar_complete)

    # ── Wiring: Signal → Dashboard + Telegram + Auto-Trader ─────────
    def on_signal(sig):
        """Called when a new trading signal is generated."""
        dashboard.add_signal(sig)
        logger.info(
            f"🎯 SIGNAL: {sig.signal_type}  Entry={sig.entry:.2f}  "
            f"SL={sig.stop_loss:.2f}  TP1={sig.take_profit_1:.2f}  Score={sig.confidence}"
        )
        if config.webhook.telegram_enabled:
            asyncio.create_task(telegram.send_signal(sig))
        if config.signal.auto_trade_enabled:
            asyncio.create_task(auto_trader.execute_signal(sig))

    engine.on_signal.append(on_signal)

    # ── Start Tick Stream ────────────────────────────────────────────
    await tick_stream.start()
    logger.info("Tick stream started. Listening for trades...")

    # ── Graceful Shutdown ────────────────────────────────────────────
    stop_event = asyncio.Event()

    def handle_shutdown(sig, frame):
        logger.info("Shutdown signal received.")
        stop_event.set()

    os_signal.signal(os_signal.SIGINT, handle_shutdown)
    os_signal.signal(os_signal.SIGTERM, handle_shutdown)

    # ── Main Loop: Dashboard + Wait ──────────────────────────────────
    try:
        with Live(
            dashboard._build_layout(),
            refresh_per_second=config.dashboard.refresh_fps,
            screen=True,
        ) as live:
            dash_task = asyncio.create_task(dashboard.run(live))
            try:
                await stop_event.wait()
            finally:
                dash_task.cancel()
                try:
                    await dash_task
                except asyncio.CancelledError:
                    pass
    finally:
        # ── Cleanup ──────────────────────────────────────────────────
        console.print("\n[bold yellow]Shutting down...[/bold yellow]")
        await tick_stream.stop()
        await auto_trader.cancel_all()
        if config.webhook.telegram_enabled:
            await telegram.stop()
        await conn_mgr.disconnect()
        console.print("[bold green]Clean shutdown complete.[/bold green]\n")


def run():
    """Console script entry point."""
    asyncio.run(main())


if __name__ == "__main__":
    run()
