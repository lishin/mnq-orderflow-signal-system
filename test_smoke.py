"""Smoke tests for core analytics — no IBKR connection needed."""
from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from dataclasses import dataclass
from datetime import datetime, timezone

# ── 1.  Volume Profile ──────────────────────────────────────────────
from analytics.volume_profile import VolumeProfileCalculator, FRVPResult


@dataclass
class MockBar:
    open: float
    high: float
    low: float
    close: float
    volume: float


def test_volume_profile_basic():
    """POC should be the price bin with the highest volume."""
    bars = [
        MockBar(open=100.0, high=101.0, low=99.0, close=100.5, volume=1000),
        MockBar(open=100.5, high=100.75, low=100.25, close=100.5, volume=5000),  # narrow, heavy
        MockBar(open=100.5, high=102.0, low=99.5, close=101.0, volume=500),
    ]
    calc = VolumeProfileCalculator(tick_size=0.25, value_area_pct=0.70, algorithm="steidlmayer_2bin")
    result = calc.calculate_from_bars(bars)

    assert result.poc is not None
    assert result.vah >= result.poc >= result.val
    assert result.va_pct_actual >= 0.70
    assert result.total_volume > 0
    # POC should be in the 100.25-100.75 range (where bar 2 concentrated)
    assert 100.0 <= result.poc <= 101.0
    print(f"  VP: POC={result.poc}, VAH={result.vah}, VAL={result.val}, VA%={result.va_pct_actual*100:.1f}%")


def test_volume_profile_greedy():
    bars = [
        MockBar(open=50.0, high=52.0, low=48.0, close=50.5, volume=3000),
        MockBar(open=50.5, high=51.0, low=50.0, close=50.75, volume=8000),
    ]
    calc = VolumeProfileCalculator(tick_size=0.25, value_area_pct=0.70, algorithm="greedy_1bin")
    result = calc.calculate_from_bars(bars)
    assert result.vah >= result.poc >= result.val
    assert result.va_pct_actual >= 0.70
    print(f"  VP greedy: POC={result.poc}, VAH={result.vah}, VAL={result.val}")


def test_value_area_helpers():
    calc = VolumeProfileCalculator(tick_size=0.25, value_area_pct=0.70)
    bars = [MockBar(open=100, high=105, low=95, close=100, volume=10000)]
    result = calc.calculate_from_bars(bars)
    assert result.is_in_value_area(result.poc)
    assert result.distance_from_vah_ticks(result.vah) == 0
    print(f"  VA helpers: in_va(poc)=True, dist_vah(vah)=0")


# ── 2.  Trade Classifier ────────────────────────────────────────────
from analytics.trade_classifier import TradeClassifier, ClassifiedTrade


def test_classifier_at_ask():
    """Trade at or above ask → aggressive buy (+1)."""
    tc = TradeClassifier(tick_size=0.25)
    t = tc.classify(datetime.now(timezone.utc), price=100.50, size=10, bid=100.25, ask=100.50)
    assert t.direction == 1
    assert t.tick_index == int(round(100.50 / 0.25))
    print(f"  Classifier: at ask → direction={t.direction}")


def test_classifier_at_bid():
    """Trade at or below bid → aggressive sell (-1)."""
    tc = TradeClassifier(tick_size=0.25)
    t = tc.classify(datetime.now(timezone.utc), price=100.25, size=5, bid=100.25, ask=100.50)
    assert t.direction == -1
    print(f"  Classifier: at bid → direction={t.direction}")


def test_classifier_tick_rule():
    """Trade between bid/ask → tick rule based on price change."""
    tc = TradeClassifier(tick_size=0.25)
    # First trade: no history → uses default direction (+1)
    tc.classify(datetime.now(timezone.utc), price=100.00, size=1, bid=99.75, ask=100.25)
    # Second trade: price went up → buy
    t2 = tc.classify(datetime.now(timezone.utc), price=100.10, size=1, bid=99.75, ask=100.25)
    assert t2.direction == 1
    # Third trade: price went down → sell
    t3 = tc.classify(datetime.now(timezone.utc), price=100.00, size=1, bid=99.75, ask=100.25)
    assert t3.direction == -1
    print(f"  Classifier tick rule: up={t2.direction}, down={t3.direction}")


# ── 3.  Footprint Aggregator ────────────────────────────────────────
from analytics.footprint import FootprintAggregator


def test_footprint_bar_creation():
    """Trades in the same minute should aggregate into one bar."""
    fp = FootprintAggregator(tick_size=0.25, big_trade_threshold=100)
    completed = []
    fp.on_bar_complete.append(completed.append)

    tc = TradeClassifier(tick_size=0.25)
    base_time = datetime(2024, 9, 20, 9, 35, 0, tzinfo=timezone.utc)

    # 5 trades in the same minute
    for i in range(5):
        t = tc.classify(
            timestamp=base_time,
            price=100.0 + i * 0.25,
            size=50,
            bid=99.75,
            ask=100.0 + i * 0.25,
        )
        fp.add_trade(t)

    # Trigger bar completion by sending a trade in the next minute
    next_min = datetime(2024, 9, 20, 9, 36, 0, tzinfo=timezone.utc)
    t = tc.classify(next_min, 101.0, 10, bid=100.75, ask=101.0)
    fp.add_trade(t)

    assert len(completed) == 1
    bar = completed[0]
    assert bar.trade_count == 5
    assert bar.total_volume == 250
    assert bar.open == 100.0
    assert bar.high == 101.0
    assert bar.low == 100.0
    print(f"  Footprint: trades={bar.trade_count}, vol={bar.total_volume}, delta={bar.total_delta:.0f}")


# ── 4.  Absorption Detector ────────────────────────────────────────
from analytics.absorption import AbsorptionDetector


def test_absorption_no_false_positive():
    """Normal bar should not trigger absorption."""
    @dataclass
    class MockConfig:
        big_trade_threshold: int = 100
        dynamic_threshold_enabled: bool = False
        dynamic_threshold_percentile: int = 95
        dynamic_threshold_window: int = 300
        absorption_lookback_bars: int = 3
        absorption_imbalance_ratio: float = 2.5
        absorption_price_proximity_ticks: int = 8

    from analytics.footprint import FootprintBar
    bar = FootprintBar(
        timestamp=datetime.now(timezone.utc),
        open=100.0, high=100.5, low=99.5, close=100.25,
        bid_vol_by_tick={}, ask_vol_by_tick={},
        total_delta=0, total_volume=100, trade_count=10, big_trade_count=0,
    )
    detector = AbsorptionDetector(config=MockConfig(), tick_size=0.25)
    events = detector.check_bar(bar, frvp=None)
    assert len(events) == 0
    print(f"  Absorption: no false positive OK")


# ── 5.  Signal Engine ───────────────────────────────────────────────
from strategy.signal_engine import SignalEngine, Signal
from core.config import SignalConfig


def test_signal_engine_no_signal_without_frvp():
    """Engine should not produce signals without FRVP set."""
    from analytics.footprint import FootprintBar
    eng = SignalEngine(config=SignalConfig(), tick_size=0.25)
    bar = FootprintBar(
        timestamp=datetime.now(timezone.utc),
        open=100.0, high=100.5, low=99.5, close=100.25,
        bid_vol_by_tick={}, ask_vol_by_tick={},
        total_delta=50, total_volume=200, trade_count=20, big_trade_count=1,
    )
    signals_received = []
    eng.on_signal.append(signals_received.append)
    eng.on_bar_complete(bar)
    assert len(signals_received) == 0
    print(f"  SignalEngine: no signal without FRVP OK")


# ── Run All ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    tests = [
        test_volume_profile_basic,
        test_volume_profile_greedy,
        test_value_area_helpers,
        test_classifier_at_ask,
        test_classifier_at_bid,
        test_classifier_tick_rule,
        test_footprint_bar_creation,
        test_absorption_no_false_positive,
        test_signal_engine_no_signal_without_frvp,
    ]
    passed = 0
    failed = 0
    for test in tests:
        try:
            print(f"[RUN]  {test.__name__}")
            test()
            print(f"[PASS] {test.__name__}")
            passed += 1
        except Exception as e:
            print(f"[FAIL] {test.__name__}: {e}")
            failed += 1

    print(f"\n{'='*50}")
    print(f"Results: {passed} passed, {failed} failed, {passed+failed} total")
    if failed:
        sys.exit(1)
    print("All tests passed!")
