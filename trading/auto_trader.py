from __future__ import annotations

import logging
import asyncio

from ib_async import IB, Future, Trade, Order

from core.config import SignalConfig
from strategy.signal_engine import Signal

logger = logging.getLogger(__name__)

class AutoTrader:
    def __init__(self, ib: IB, contract: Future, config: SignalConfig):
        self.ib = ib
        self.contract = contract
        self.config = config
        self._active_trade: Trade | None = None
        self._position: int = 0
        self.enabled: bool = config.auto_trade_enabled

    @property
    def has_position(self) -> bool:
        return self._position != 0

    async def execute_signal(self, signal: Signal) -> None:
        if not self.enabled:
            logger.info("Auto-trade is disabled, ignoring signal.")
            return

        if self.has_position or self._active_trade:
            logger.warning("Already have active position or trade, ignoring new signal.")
            return

        action = 'BUY' if 'LONG' in signal.signal_type else 'SELL'
        quantity = self.config.auto_trade_quantity

        bracket = self.ib.bracketOrder(
            action=action,
            quantity=quantity,
            limitPrice=signal.entry,
            takeProfitPrice=signal.take_profit_1,
            stopLossPrice=signal.stop_loss
        )
        
        parent, take_profit, stop_loss = bracket

        logger.info(f"Placing bracket order: {action} {quantity} @ {signal.entry}, TP: {signal.take_profit_1}, SL: {signal.stop_loss}")

        for order in bracket:
            trade = self.ib.placeOrder(self.contract, order)
            if order == parent:
                self._active_trade = trade
                trade.fillEvent += self._on_fill
                trade.statusEvent += self._on_status_change
            
        await asyncio.sleep(0)  # yield to event loop

    def _on_fill(self, trade: Trade, fill) -> None:
        logger.info(f"Order filled: {fill.execution.side} {fill.execution.shares} @ {fill.execution.price}")
        if trade.order.action == 'BUY':
            self._position += int(fill.execution.shares)
        else:
            self._position -= int(fill.execution.shares)
            
        if self._position == 0:
            logger.info("Position closed.")
            self._active_trade = None

    def _on_status_change(self, trade: Trade) -> None:
        logger.info(f"Order status changed to {trade.orderStatus.status}")
        if trade.orderStatus.status in ('Cancelled', 'Inactive') and not self.has_position:
            self._active_trade = None

    async def cancel_all(self) -> None:
        logger.info("Cancelling all open orders.")
        for trade in self.ib.openTrades():
            if trade.contract.symbol == self.contract.symbol:
                self.ib.cancelOrder(trade.order)
        await asyncio.sleep(0.5)
