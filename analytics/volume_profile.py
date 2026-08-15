from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

@dataclass
class FRVPResult:
    poc: float
    vah: float
    val: float
    total_volume: float
    va_volume: float
    va_pct_actual: float
    profile: dict[int, float]
    tick_size: float
    
    def price_from_tick(self, tick_idx: int) -> float:
        return tick_idx * self.tick_size
        
    def is_in_value_area(self, price: float) -> bool:
        return self.val <= price <= self.vah
        
    def distance_from_vah_ticks(self, price: float) -> int:
        return abs(int(round(price / self.tick_size)) - int(round(self.vah / self.tick_size)))
        
    def distance_from_val_ticks(self, price: float) -> int:
        return abs(int(round(price / self.tick_size)) - int(round(self.val / self.tick_size)))


class VolumeProfileCalculator:
    """Calculates Fixed Range Volume Profile from bar data."""
    
    def __init__(
        self,
        tick_size: float = 0.25,
        value_area_pct: float = 0.70,
        algorithm: str = "steidlmayer_2bin"
    ):
        self.tick_size = tick_size
        self.value_area_pct = value_area_pct
        self.algorithm = algorithm
        
    def calculate_from_bars(self, bars: list[Any]) -> FRVPResult:
        if not bars:
            raise ValueError("Cannot calculate volume profile from empty bars.")
            
        min_tick = int(round(min(b.low for b in bars) / self.tick_size))
        max_tick = int(round(max(b.high for b in bars) / self.tick_size))
        
        shift = min_tick
        size = max_tick - min_tick + 1
        bin_volumes = np.zeros(size, dtype=float)
        
        for bar in bars:
            if bar.volume <= 0:
                continue
                
            bar_min = int(round(bar.low / self.tick_size)) - shift
            bar_max = int(round(bar.high / self.tick_size)) - shift
            
            ticks_in_bar = bar_max - bar_min + 1
            vol_per_tick = bar.volume / ticks_in_bar
            
            bin_volumes[bar_min : bar_max + 1] += vol_per_tick
            
        total_volume = float(np.sum(bin_volumes))
        if total_volume == 0:
            return FRVPResult(
                poc=0.0, vah=0.0, val=0.0, total_volume=0.0,
                va_volume=0.0, va_pct_actual=0.0, profile={}, tick_size=self.tick_size
            )
            
        poc_idx_shifted = int(np.argmax(bin_volumes))
        
        if self.algorithm == "steidlmayer_2bin":
            val_shifted, vah_shifted, va_vol = self._expand_value_area_steidlmayer(bin_volumes, poc_idx_shifted)
        elif self.algorithm in ("greedy", "greedy_1bin"):
            val_shifted, vah_shifted, va_vol = self._expand_value_area_greedy(bin_volumes, poc_idx_shifted)
        else:
            raise ValueError(f"Unknown algorithm: {self.algorithm}")
            
        val_idx = val_shifted + shift
        vah_idx = vah_shifted + shift
        poc_idx = poc_idx_shifted + shift
        
        profile = {
            idx + shift: float(vol)
            for idx, vol in enumerate(bin_volumes)
            if vol > 0
        }
        
        return FRVPResult(
            poc=poc_idx * self.tick_size,
            vah=vah_idx * self.tick_size,
            val=val_idx * self.tick_size,
            total_volume=total_volume,
            va_volume=float(va_vol),
            va_pct_actual=float(va_vol / total_volume) if total_volume > 0 else 0.0,
            profile=profile,
            tick_size=self.tick_size
        )
        
    def _expand_value_area_steidlmayer(
        self, bin_volumes: np.ndarray, poc_idx: int
    ) -> tuple[int, int, float]:
        target_vol = np.sum(bin_volumes) * self.value_area_pct
        current_vol = bin_volumes[poc_idx]
        
        val_idx = poc_idx
        vah_idx = poc_idx
        
        max_idx = len(bin_volumes) - 1
        
        while current_vol < target_vol:
            up_vol = 0.0
            if vah_idx + 1 <= max_idx:
                up_vol += bin_volumes[vah_idx + 1]
            if vah_idx + 2 <= max_idx:
                up_vol += bin_volumes[vah_idx + 2]
                
            down_vol = 0.0
            if val_idx - 1 >= 0:
                down_vol += bin_volumes[val_idx - 1]
            if val_idx - 2 >= 0:
                down_vol += bin_volumes[val_idx - 2]
                
            if up_vol == 0 and down_vol == 0:
                break
                
            if up_vol > down_vol:
                current_vol += up_vol
                vah_idx = min(max_idx, vah_idx + 2)
            elif down_vol > up_vol:
                current_vol += down_vol
                val_idx = max(0, val_idx - 2)
            else:
                current_vol += up_vol + down_vol
                vah_idx = min(max_idx, vah_idx + 2)
                val_idx = max(0, val_idx - 2)
                
        return val_idx, vah_idx, float(current_vol)

    def _expand_value_area_greedy(
        self, bin_volumes: np.ndarray, poc_idx: int
    ) -> tuple[int, int, float]:
        target_vol = np.sum(bin_volumes) * self.value_area_pct
        current_vol = bin_volumes[poc_idx]
        
        val_idx = poc_idx
        vah_idx = poc_idx
        max_idx = len(bin_volumes) - 1
        
        while current_vol < target_vol:
            up_vol = bin_volumes[vah_idx + 1] if vah_idx < max_idx else 0.0
            down_vol = bin_volumes[val_idx - 1] if val_idx > 0 else 0.0
            
            if up_vol == 0 and down_vol == 0:
                break
                
            if up_vol > down_vol:
                current_vol += up_vol
                vah_idx += 1
            elif down_vol > up_vol:
                current_vol += down_vol
                val_idx -= 1
            else:
                current_vol += up_vol + down_vol
                if vah_idx < max_idx:
                    vah_idx += 1
                if val_idx > 0:
                    val_idx -= 1
                    
        return val_idx, vah_idx, float(current_vol)
