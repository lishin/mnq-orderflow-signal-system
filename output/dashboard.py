from __future__ import annotations

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo
import logging

from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.align import Align
from rich.live import Live

from core.config import DashboardConfig
from analytics.volume_profile import FRVPResult
from analytics.footprint import FootprintBar
from strategy.signal_engine import Signal

logger = logging.getLogger(__name__)

class Dashboard:
    def __init__(self, config: DashboardConfig):
        self.config = config
        self.frvp: FRVPResult | None = None
        self.last_price: float = 0.0
        self.best_bid: float = 0.0
        self.best_ask: float = 0.0
        self.cumulative_delta: float = 0.0
        self.buy_volume: float = 0.0
        self.sell_volume: float = 0.0
        self.big_trade_count: int = 0
        self.current_bar: FootprintBar | None = None
        self.signals: list[Signal] = []
        self.status: str = "Initializing..."
        self.auto_trade_on: bool = False
        self.webhook_on: bool = False
        self.connected: bool = False
        self._layout = Layout()

    def update_price(self, price: float, bid: float, ask: float) -> None:
        self.last_price = price
        self.best_bid = bid
        self.best_ask = ask

    def update_frvp(self, frvp: FRVPResult) -> None:
        self.frvp = frvp

    def add_signal(self, signal: Signal) -> None:
        self.signals.append(signal)
        if len(self.signals) > self.config.max_signal_log_rows:
            self.signals.pop(0)

    def update_orderflow(self, delta: float, buy_vol: float, sell_vol: float, big_trades: int) -> None:
        self.cumulative_delta = delta
        self.buy_volume = buy_vol
        self.sell_volume = sell_vol
        self.big_trade_count = big_trades

    def set_status(self, msg: str) -> None:
        self.status = msg

    def set_connected(self, connected: bool) -> None:
        self.connected = connected

    def _build_layout(self) -> Layout:
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="body", ratio=1),
            Layout(name="signals", ratio=2),
            Layout(name="footer", size=3)
        )
        layout["body"].split_row(
            Layout(name="left", ratio=1),
            Layout(name="right", ratio=1)
        )
        return layout

    def _render_header(self) -> Panel:
        now = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M:%S ET")
        conn_color = "green" if self.connected else "red"
        conn_char = "●"
        header_text = Text.assemble(
            ("MNQ Signal System", "bold blue"),
            " | ",
            (now, "cyan"),
            " | Status: ",
            (f"{conn_char} ", conn_color),
            (self.status, "white")
        )
        return Panel(header_text, style="white")

    def _render_frvp_panel(self) -> Panel:
        if not self.frvp:
            return Panel("Awaiting FRVP...", title="[bold]Volume Profile[/]", border_style="blue")

        table = Table(show_header=True, header_style="bold magenta", expand=True)
        table.add_column("Level")
        table.add_column("Price", justify="right")

        def colorize(price: float) -> str:
            if price > self.frvp.vah:
                return "bold red"
            elif price < self.frvp.val:
                return "bold red"
            else:
                return "bold green"

        table.add_row("VAH", f"{self.frvp.vah:.2f}")
        table.add_row("POC", f"{self.frvp.poc:.2f}")
        table.add_row("VAL", f"{self.frvp.val:.2f}")
        table.add_row("VA%", f"{self.frvp.va_pct_actual*100:.1f}%")
        
        last_price_str = f"[{colorize(self.last_price)}]{self.last_price:.2f}[/]"
        table.add_row("Last Price", last_price_str)

        return Panel(table, title="[bold]Fixed Range Volume Profile[/]", border_style="blue")

    def _render_orderflow_panel(self) -> Panel:
        table = Table(show_header=False, expand=True)
        table.add_column("Metric")
        table.add_column("Value", justify="right")

        cd_color = "green" if self.cumulative_delta >= 0 else "red"
        
        table.add_row("Last Price", f"{self.last_price:.2f}")
        table.add_row("Bid / Ask", f"{self.best_bid:.2f} / {self.best_ask:.2f}")
        table.add_row("Cum. Delta", f"[{cd_color}]{self.cumulative_delta:.0f}[/]")
        table.add_row("Buy Vol", f"[green]{self.buy_volume:.0f}[/]")
        table.add_row("Sell Vol", f"[red]{self.sell_volume:.0f}[/]")
        table.add_row("Big Trades", f"{self.big_trade_count}")

        return Panel(table, title="[bold]Orderflow Stats[/]", border_style="blue")

    def _render_signals_table(self) -> Panel:
        table = Table(show_header=True, header_style="bold yellow", expand=True)
        table.add_column("Time")
        table.add_column("Direction")
        table.add_column("Type")
        table.add_column("Entry")
        table.add_column("SL")
        table.add_column("TP1")
        table.add_column("Score")
        
        for sig in reversed(self.signals):
            is_long = "LONG" in sig.signal_type
            dir_str = "[bold green]▲ LONG[/]" if is_long else "[bold red]▼ SHORT[/]"
            
            score_color = "bold green" if sig.confidence >= 80 else ("yellow" if sig.confidence >= 60 else "dim")
            
            table.add_row(
                sig.timestamp.strftime("%H:%M:%S"),
                dir_str,
                sig.signal_type,
                f"{sig.entry:.2f}",
                f"{sig.stop_loss:.2f}",
                f"{sig.take_profit_1:.2f}",
                f"[{score_color}]{sig.confidence}[/]"
            )

        return Panel(table, title="[bold]Recent Signals[/]", border_style="yellow")

    def _render_footer(self) -> Panel:
        auto_trade_str = "[green]ON[/]" if self.auto_trade_on else "[red]OFF[/]"
        webhook_str = "[green]ON[/]" if self.webhook_on else "[red]OFF[/]"
        footer_text = Text.from_markup(
            f"[dim][Ctrl+C] Exit[/dim] | Auto-Trade: {auto_trade_str} | Webhook: {webhook_str}"
        )
        return Panel(Align.center(footer_text), style="white")

    def update(self) -> None:
        self._layout["header"].update(self._render_header())
        self._layout["left"].update(self._render_frvp_panel())
        self._layout["right"].update(self._render_orderflow_panel())
        self._layout["signals"].update(self._render_signals_table())
        self._layout["footer"].update(self._render_footer())

    async def run(self, live: Live) -> None:
        self._layout = self._build_layout()
        delay = 1.0 / self.config.refresh_fps
        while True:
            self.update()
            live.update(self._layout)
            await asyncio.sleep(delay)
