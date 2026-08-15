from __future__ import annotations

import logging
from datetime import datetime
from typing import Callable
from ib_async import IB, Future, Ticker, TickByTickAllLast, TickByTickBidAsk

logger = logging.getLogger(__name__)

class TickStreamManager:
    """Manages real-time tick and quote subscriptions from IB."""

    def __init__(self, ib: IB, contract: Future):
        self.ib = ib
        self.contract = contract
        
        self.best_bid: float = 0.0
        self.best_ask: float = 0.0
        
        self.on_trade: list[Callable[[datetime, float, float], None]] = []
        self.on_quote: list[Callable[[datetime, float, float, float, float], None]] = []

    @property
    def mid_price(self) -> float:
        if self.best_bid > 0 and self.best_ask > 0:
            return (self.best_bid + self.best_ask) / 2.0
        return 0.0
        
    @property
    def spread(self) -> float:
        if self.best_bid > 0 and self.best_ask > 0:
            return self.best_ask - self.best_bid
        return 0.0

    async def start(self):
        """Starts real-time tick subscriptions."""
        logger.info(f"Starting tick stream for {self.contract.localSymbol}")
        
        self.ib.pendingTickersEvent += self._on_pending_tickers
        
        self.ib.reqTickByTickData(self.contract, tickType="AllLast")
        self.ib.reqTickByTickData(self.contract, tickType="BidAsk")

    async def stop(self):
        """Stops real-time tick subscriptions."""
        logger.info(f"Stopping tick stream for {self.contract.localSymbol}")
        self.ib.pendingTickersEvent -= self._on_pending_tickers
        self.ib.cancelTickByTickData(self.contract, "AllLast")
        self.ib.cancelTickByTickData(self.contract, "BidAsk")

    def _on_pending_tickers(self, tickers: set[Ticker]):
        for ticker in tickers:
            if ticker.contract == self.contract:
                self._process_ticker(ticker)

    def _process_ticker(self, ticker: Ticker):
        # Process trades
        if ticker.tickByTicks:
            for tick in ticker.tickByTicks:
                if isinstance(tick, TickByTickAllLast):
                    self._on_trade_tick(tick)
                elif isinstance(tick, TickByTickBidAsk):
                    self._on_quote_tick(tick)

    def _on_trade_tick(self, tick: TickByTickAllLast):
        for cb in self.on_trade:
            try:
                cb(tick.time, tick.price, float(tick.size))
            except Exception as e:
                logger.error(f"Error in trade callback: {e}")

    def _on_quote_tick(self, tick: TickByTickBidAsk):
        self.best_bid = tick.bidPrice
        self.best_ask = tick.askPrice
        
        for cb in self.on_quote:
            try:
                cb(tick.time, tick.bidPrice, tick.askPrice, float(tick.bidSize), float(tick.askSize))
            except Exception as e:
                logger.error(f"Error in quote callback: {e}")
