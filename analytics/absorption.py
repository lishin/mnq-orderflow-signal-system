from __future__ import annotations

import collections
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Callable

import numpy as np

from analytics.footprint import FootprintBar
from analytics.volume_profile import FRVPResult

if TYPE_CHECKING:
    from core.config import OrderflowConfig

logger = logging.getLogger(__name__)

@dataclass
class AbsorptionEvent:
    timestamp: datetime
    signal_type: str
    price_level: float
    absorbed_volume: float
    delta: float
    imbalance_ratio: float
    bar: FootprintBar


class AbsorptionDetector:
    
    def __init__(self, config: OrderflowConfig | any, tick_size: float = 0.25):
        self.config = config
        self.tick_size = tick_size
        
        self.dynamic_threshold_enabled = getattr(config, 'dynamic_threshold_enabled', False)
        self.dynamic_threshold_window = getattr(config, 'dynamic_threshold_window', 1000)
        self.dynamic_threshold_percentile = getattr(config, 'dynamic_threshold_percentile', 90.0)
        self.absorption_imbalance_ratio = getattr(config, 'absorption_imbalance_ratio', 2.0)
        self.absorption_price_proximity_ticks = getattr(config, 'absorption_price_proximity_ticks', 4)
        self.base_threshold = getattr(config, 'big_trade_threshold', 200.0)
        
        self._recent_trade_sizes = collections.deque(maxlen=self.dynamic_threshold_window)
        self._current_threshold = self.base_threshold
        
        self.on_absorption: list[Callable[[AbsorptionEvent], None]] = []
        
    def update_dynamic_threshold(self, trade_size: float) -> None:
        if not self.dynamic_threshold_enabled:
            return
            
        self._recent_trade_sizes.append(trade_size)
        if len(self._recent_trade_sizes) >= max(100, self.dynamic_threshold_window // 10):
            self._current_threshold = float(np.percentile(
                self._recent_trade_sizes, self.dynamic_threshold_percentile
            ))
            
    def _get_threshold(self) -> float:
        if self.dynamic_threshold_enabled and len(self._recent_trade_sizes) > 0:
            return self._current_threshold
        return self.base_threshold
        
    def check_bar(
        self, bar: FootprintBar, frvp: FRVPResult | None
    ) -> list[AbsorptionEvent]:
        events = []
        
        bearish_event = self._check_bearish_absorption(bar, frvp)
        if bearish_event:
            events.append(bearish_event)
            
        bullish_event = self._check_bullish_absorption(bar, frvp)
        if bullish_event:
            events.append(bullish_event)
            
        for event in events:
            for cb in self.on_absorption:
                cb(event)
                
        return events
        
    def _check_bearish_absorption(
        self, bar: FootprintBar, frvp: FRVPResult | None
    ) -> AbsorptionEvent | None:
        
        if frvp is not None:
            dist_to_vah = frvp.distance_from_vah_ticks(bar.high)
            if dist_to_vah > self.absorption_price_proximity_ticks:
                return None
                
        buy_vol, sell_vol = bar.wick_volume('upper', self.tick_size)
        threshold = self._get_threshold()
        
        if buy_vol < threshold:
            return None
            
        body_size = bar.body_top() - bar.body_bottom()
        wick_size = bar.upper_wick()
        
        is_bearish_close = bar.is_bearish()
        is_large_wick = wick_size >= (1.5 * body_size)
        
        if not (is_bearish_close or is_large_wick):
            return None
            
        if sell_vol == 0:
            ratio = float('inf')
        else:
            ratio = buy_vol / sell_vol
            
        if ratio >= self.absorption_imbalance_ratio:
            return AbsorptionEvent(
                timestamp=bar.timestamp,
                signal_type='BEARISH_ABSORPTION',
                price_level=bar.high,
                absorbed_volume=buy_vol,
                delta=buy_vol - sell_vol,
                imbalance_ratio=ratio,
                bar=bar
            )
            
        return None
        
    def _check_bullish_absorption(
        self, bar: FootprintBar, frvp: FRVPResult | None
    ) -> AbsorptionEvent | None:
        
        if frvp is not None:
            dist_to_val = frvp.distance_from_val_ticks(bar.low)
            if dist_to_val > self.absorption_price_proximity_ticks:
                return None
                
        buy_vol, sell_vol = bar.wick_volume('lower', self.tick_size)
        threshold = self._get_threshold()
        
        if sell_vol < threshold:
            return None
            
        body_size = bar.body_top() - bar.body_bottom()
        wick_size = bar.lower_wick()
        
        is_bullish_close = bar.is_bullish()
        is_large_wick = wick_size >= (1.5 * body_size)
        
        if not (is_bullish_close or is_large_wick):
            return None
            
        if buy_vol == 0:
            ratio = float('inf')
        else:
            ratio = sell_vol / buy_vol
            
        if ratio >= self.absorption_imbalance_ratio:
            return AbsorptionEvent(
                timestamp=bar.timestamp,
                signal_type='BULLISH_ABSORPTION',
                price_level=bar.low,
                absorbed_volume=sell_vol,
                delta=buy_vol - sell_vol,
                imbalance_ratio=ratio,
                bar=bar
            )
            
        return None
