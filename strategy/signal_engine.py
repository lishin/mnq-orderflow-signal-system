from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Any

from core.config import SignalConfig
from analytics.volume_profile import FRVPResult
from analytics.footprint import FootprintBar
from analytics.absorption import AbsorptionEvent

logger = logging.getLogger(__name__)

@dataclass
class Signal:
    """Represents a generated trading signal."""
    timestamp: datetime
    signal_type: str
    entry: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: float | None
    confidence: int
    reason: str


class SignalEngine:
    """Core logic for generating trading signals from orderflow data."""
    
    def __init__(self, config: SignalConfig, tick_size: float = 0.25):
        self.config = config
        self.tick_size = tick_size
        self._frvp: FRVPResult | None = None
        self._absorption_events: list[AbsorptionEvent] = []
        self._recent_bars: list[FootprintBar] = []
        self._price_history: list[float] = []
        self._signals: list[Signal] = []
        self._cooldown_until: datetime | None = None
        self.on_signal: list[Callable[[Signal], None]] = []

    def set_frvp(self, frvp: FRVPResult) -> None:
        """Store FRVP levels."""
        self._frvp = frvp

    def set_cooldown(self, until: datetime) -> None:
        """Set the post-open cooldown."""
        self._cooldown_until = until

    def on_absorption_event(self, event: AbsorptionEvent) -> None:
        """Store absorption event."""
        self._absorption_events.append(event)
        # Keep last 50 events
        if len(self._absorption_events) > 50:
            self._absorption_events.pop(0)

    def on_bar_complete(self, bar: FootprintBar) -> None:
        """Main evaluation entry point."""
        if self._cooldown_until and bar.timestamp < self._cooldown_until:
            return

        self._recent_bars.append(bar)
        if len(self._recent_bars) > 30:
            self._recent_bars.pop(0)

        # Check all 4 signal types
        signals_to_check = [
            self._check_failed_auction_short(bar),
            self._check_failed_auction_long(bar),
            self._check_breakout_short(bar),
            self._check_breakout_long(bar),
        ]

        for signal in signals_to_check:
            if signal and signal.confidence >= self.config.min_confidence_score:
                self._signals.append(signal)
                for callback in self.on_signal:
                    try:
                        callback(signal)
                    except Exception as e:
                        logger.error(f"Error in signal callback: {e}")

    def _check_failed_auction_short(self, bar: FootprintBar) -> Signal | None:
        if not self._frvp:
            return None

        # Check recent bars for visit above VAH
        visited_above = any(b.high > self._frvp.vah for b in self._recent_bars[-5:])
        if not visited_above:
            return None

        # Check absorption_events for recent BEARISH_ABSORPTION
        recent_bearish = [e for e in self._absorption_events[-5:] if e.signal_type == 'BEARISH_ABSORPTION']
        if not recent_bearish:
            return None
            
        latest_absorption = recent_bearish[-1]

        # Current bar closes back inside Value Area (close <= VAH)
        if bar.close > self._frvp.vah:
            return None

        entry = latest_absorption.price_level - self.tick_size
        sl = latest_absorption.price_level + (self.config.sl_buffer_ticks * self.tick_size)
        tp1 = self._frvp.poc
        tp2 = self._frvp.val

        confidence = self._calculate_confidence({
            'volume': latest_absorption.absorbed_volume,
            'imbalance': latest_absorption.imbalance_ratio,
            'delta': abs(latest_absorption.delta)
        })

        return Signal(
            timestamp=bar.timestamp,
            signal_type='FAILED_AUCTION_SHORT',
            entry=entry,
            stop_loss=sl,
            take_profit_1=tp1,
            take_profit_2=tp2,
            confidence=confidence,
            reason=f"Bearish absorption above VAH and close back inside VA. Absorption at {latest_absorption.price_level}."
        )

    def _check_failed_auction_long(self, bar: FootprintBar) -> Signal | None:
        if not self._frvp:
            return None

        # Check recent bars for visit below VAL
        visited_below = any(b.low < self._frvp.val for b in self._recent_bars[-5:])
        if not visited_below:
            return None

        # Check absorption_events for recent BULLISH_ABSORPTION
        recent_bullish = [e for e in self._absorption_events[-5:] if e.signal_type == 'BULLISH_ABSORPTION']
        if not recent_bullish:
            return None
            
        latest_absorption = recent_bullish[-1]

        # Current bar closes back inside Value Area (close >= VAL)
        if bar.close < self._frvp.val:
            return None

        entry = latest_absorption.price_level + self.tick_size
        sl = latest_absorption.price_level - (self.config.sl_buffer_ticks * self.tick_size)
        tp1 = self._frvp.poc
        tp2 = self._frvp.vah

        confidence = self._calculate_confidence({
            'volume': latest_absorption.absorbed_volume,
            'imbalance': latest_absorption.imbalance_ratio,
            'delta': abs(latest_absorption.delta)
        })

        return Signal(
            timestamp=bar.timestamp,
            signal_type='FAILED_AUCTION_LONG',
            entry=entry,
            stop_loss=sl,
            take_profit_1=tp1,
            take_profit_2=tp2,
            confidence=confidence,
            reason=f"Bullish absorption below VAL and close back inside VA. Absorption at {latest_absorption.price_level}."
        )

    def _check_breakout_short(self, bar: FootprintBar) -> Signal | None:
        if not self._frvp or len(self._recent_bars) < 5:
            return None

        # Consolidating below VAL
        consolidation_bars = self._recent_bars[-5:-1]
        if not all(b.close < self._frvp.val for b in consolidation_bars):
            return None

        cons_low = min(b.low for b in consolidation_bars)
        cons_high = max(b.high for b in consolidation_bars)

        # Break below consolidation
        if bar.close >= cons_low:
            return None

        # Follow-through
        if bar.total_delta >= 0 or bar.big_trade_count == 0:
            return None

        entry = cons_low - self.tick_size
        sl = max(bar.high, cons_high)
        tp1 = entry - 2 * (sl - entry)
        
        confidence = self._calculate_confidence({
            'delta': abs(bar.total_delta),
            'big_trades': bar.big_trade_count * 10
        })

        return Signal(
            timestamp=bar.timestamp,
            signal_type='BREAKOUT_SHORT',
            entry=entry,
            stop_loss=sl,
            take_profit_1=tp1,
            take_profit_2=None,
            confidence=confidence,
            reason="Breakout below VAL consolidation with strong sell delta."
        )

    def _check_breakout_long(self, bar: FootprintBar) -> Signal | None:
        if not self._frvp or len(self._recent_bars) < 5:
            return None

        # Consolidating above VAH
        consolidation_bars = self._recent_bars[-5:-1]
        if not all(b.close > self._frvp.vah for b in consolidation_bars):
            return None

        cons_low = min(b.low for b in consolidation_bars)
        cons_high = max(b.high for b in consolidation_bars)

        # Break above consolidation
        if bar.close <= cons_high:
            return None

        # Follow-through
        if bar.total_delta <= 0 or bar.big_trade_count == 0:
            return None

        entry = cons_high + self.tick_size
        sl = min(bar.low, cons_low)
        tp1 = entry + 2 * (entry - sl)
        
        confidence = self._calculate_confidence({
            'delta': abs(bar.total_delta),
            'big_trades': bar.big_trade_count * 10
        })

        return Signal(
            timestamp=bar.timestamp,
            signal_type='BREAKOUT_LONG',
            entry=entry,
            stop_loss=sl,
            take_profit_1=tp1,
            take_profit_2=None,
            confidence=confidence,
            reason="Breakout above VAH consolidation with strong buy delta."
        )

    def _calculate_confidence(self, factors: dict[str, float]) -> int:
        score = 50.0
        for name, value in factors.items():
            if name == 'volume':
                score += min(value / 100, 20)
            elif name == 'imbalance':
                score += min(value * 5, 20)
            elif name == 'delta':
                score += min(value / 50, 20)
            elif name == 'big_trades':
                score += min(value, 20)
                
        return int(min(max(score, 0), 100))

    @property
    def signals(self) -> list[Signal]:
        return list(self._signals)

    @property
    def latest_signal(self) -> Signal | None:
        return self._signals[-1] if self._signals else None
