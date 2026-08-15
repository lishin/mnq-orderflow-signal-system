from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from analytics.trade_classifier import ClassifiedTrade

logger = logging.getLogger(__name__)

@dataclass
class FootprintBar:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    bid_vol_by_tick: dict[int, float]
    ask_vol_by_tick: dict[int, float]
    total_delta: float
    total_volume: float
    trade_count: int
    big_trade_count: int
    
    def body_top(self) -> float:
        return max(self.open, self.close)
        
    def body_bottom(self) -> float:
        return min(self.open, self.close)
        
    def upper_wick(self) -> float:
        return self.high - self.body_top()
        
    def lower_wick(self) -> float:
        return self.body_bottom() - self.low
        
    def is_bullish(self) -> bool:
        return self.close > self.open
        
    def is_bearish(self) -> bool:
        return self.close < self.open
        
    def wick_volume(self, zone: str, tick_size: float) -> tuple[float, float]:
        buy_vol = 0.0
        sell_vol = 0.0
        
        if zone == 'upper':
            min_price = self.body_top()
            max_price = self.high
        elif zone == 'lower':
            min_price = self.low
            max_price = self.body_bottom()
        else:
            raise ValueError("zone must be 'upper' or 'lower'")
            
        min_tick = int(round(min_price / tick_size))
        max_tick = int(round(max_price / tick_size))
        
        for t in range(min_tick, max_tick + 1):
            buy_vol += self.ask_vol_by_tick.get(t, 0.0)
            sell_vol += self.bid_vol_by_tick.get(t, 0.0)
            
        return buy_vol, sell_vol


class FootprintAggregator:
    def __init__(self, tick_size: float = 0.25, big_trade_threshold: float = 200.0):
        self.tick_size = tick_size
        self._big_trade_threshold = big_trade_threshold
        self._current_bar: FootprintBar | None = None
        self._current_minute: datetime | None = None
        self.on_bar_complete: list[Callable[[FootprintBar], None]] = []
        self.completed_bars: list[FootprintBar] = []
        
    def add_trade(self, trade: ClassifiedTrade) -> None:
        trade_minute = trade.timestamp.replace(second=0, microsecond=0)
        
        if self._current_minute != trade_minute:
            if self._current_bar is not None:
                self._finalize_bar()
            self._start_new_bar(trade_minute, trade.price)
            
        bar = self._current_bar
        if bar is None:
            return
            
        bar.high = max(bar.high, trade.price)
        bar.low = min(bar.low, trade.price)
        bar.close = trade.price
        
        bar.total_volume += trade.size
        bar.trade_count += 1
        
        if trade.size >= self._big_trade_threshold:
            bar.big_trade_count += 1
            
        if trade.direction == 1:
            bar.ask_vol_by_tick[trade.tick_index] = bar.ask_vol_by_tick.get(trade.tick_index, 0.0) + trade.size
            bar.total_delta += trade.size
        elif trade.direction == -1:
            bar.bid_vol_by_tick[trade.tick_index] = bar.bid_vol_by_tick.get(trade.tick_index, 0.0) + trade.size
            bar.total_delta -= trade.size
            
    def _start_new_bar(self, timestamp: datetime, price: float) -> None:
        self._current_minute = timestamp
        self._current_bar = FootprintBar(
            timestamp=timestamp,
            open=price,
            high=price,
            low=price,
            close=price,
            bid_vol_by_tick={},
            ask_vol_by_tick={},
            total_delta=0.0,
            total_volume=0.0,
            trade_count=0,
            big_trade_count=0
        )
        
    def _finalize_bar(self) -> None:
        if self._current_bar:
            self.completed_bars.append(self._current_bar)
            if len(self.completed_bars) > 60:
                self.completed_bars = self.completed_bars[-60:]
                
            for cb in self.on_bar_complete:
                cb(self._current_bar)
                
            self._current_bar = None
            
    def get_recent_bars(self, n: int) -> list[FootprintBar]:
        return self.completed_bars[-n:]
        
    def update_big_trade_threshold(self, new_threshold: float) -> None:
        self._big_trade_threshold = new_threshold
