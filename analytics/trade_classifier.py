from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)

@dataclass(slots=True)
class ClassifiedTrade:
    """Represents a classified trade."""
    timestamp: datetime
    price: float
    size: float
    direction: int      # +1 = aggressive buy, -1 = aggressive sell
    tick_index: int     # int(round(price / tick_size))


class TradeClassifier:
    """Classifies trades into aggressive buys or sells."""
    
    def __init__(self, tick_size: float = 0.25):
        self.tick_size = tick_size
        self._last_price: float | None = None
        self._last_direction: int = 1
        
    def classify(
        self, timestamp: datetime, price: float, size: float, bid: float, ask: float
    ) -> ClassifiedTrade:
        
        if price >= ask:
            direction = 1
        elif price <= bid:
            direction = -1
        else:
            if self._last_price is not None:
                if price > self._last_price:
                    direction = 1
                elif price < self._last_price:
                    direction = -1
                else:
                    direction = self._last_direction
            else:
                direction = self._last_direction
                
        self._last_price = price
        self._last_direction = direction
        
        tick_index = int(round(price / self.tick_size))
        
        return ClassifiedTrade(
            timestamp=timestamp,
            price=price,
            size=size,
            direction=direction,
            tick_index=tick_index
        )
        
    def reset(self) -> None:
        self._last_price = None
        self._last_direction = 1
