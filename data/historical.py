from __future__ import annotations

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from ib_async import IB, Future, BarData

from core.config import FRVPConfig

logger = logging.getLogger(__name__)


class HistoricalDataFetcher:
    """Fetches historical data from IB for FRVP and other calculations."""

    def __init__(self, ib: IB, contract: Future, config: FRVPConfig):
        self.ib = ib
        self.contract = contract
        self.config = config
        self.tz = ZoneInfo("America/New_York")

    def get_overnight_window(self) -> tuple[datetime, datetime]:
        """
        Calculates the appropriate overnight session window in ET.
        
        CME Futures Overnight Schedule:
        - Mon RTH (09:30): Overnight is Sun 18:00 -> Mon 09:30 ET (15.5 hrs).
        - Tue-Fri RTH (09:30): Overnight is Prev Day 18:00 -> Today 09:30 ET (15.5 hrs).
        - Weekend / Off-hours:
          If market is currently closed (e.g. Saturday or Sunday before 18:00),
          we fallback to the last completed session (Thursday 18:00 -> Friday 09:30 ET).
        """
        now = datetime.now(self.tz)
        weekday = now.weekday()  # Mon=0, Tue=1, ..., Sat=5, Sun=6

        if weekday == 5:  # Saturday -> last completed session was Thu 18:00 -> Fri 09:30
            days_back = 2  # Thursday
            start_time = (now - timedelta(days=days_back)).replace(
                hour=self.config.overnight_start_hour,
                minute=self.config.overnight_start_min,
                second=0,
                microsecond=0
            )
            end_time = (start_time + timedelta(days=1)).replace(
                hour=self.config.overnight_end_hour,
                minute=self.config.overnight_end_min,
                second=0,
                microsecond=0
            )
        elif weekday == 6 and now.hour < self.config.overnight_start_hour:
            # Sunday before 18:00 -> last completed session was Thu 18:00 -> Fri 09:30
            days_back = 3  # Thursday
            start_time = (now - timedelta(days=days_back)).replace(
                hour=self.config.overnight_start_hour,
                minute=self.config.overnight_start_min,
                second=0,
                microsecond=0
            )
            end_time = (start_time + timedelta(days=1)).replace(
                hour=self.config.overnight_end_hour,
                minute=self.config.overnight_end_min,
                second=0,
                microsecond=0
            )
        elif weekday == 6 and now.hour >= self.config.overnight_start_hour:
            # Sunday 18:00+ -> CME opens for Monday! Session is Sun 18:00 -> Mon 09:30
            start_time = now.replace(
                hour=self.config.overnight_start_hour,
                minute=self.config.overnight_start_min,
                second=0,
                microsecond=0
            )
            end_time = (start_time + timedelta(days=1)).replace(
                hour=self.config.overnight_end_hour,
                minute=self.config.overnight_end_min,
                second=0,
                microsecond=0
            )
        elif weekday == 0 and now.hour < self.config.overnight_end_hour:
            # Monday morning before 09:30 -> started Sunday 18:00
            start_time = (now - timedelta(days=1)).replace(
                hour=self.config.overnight_start_hour,
                minute=self.config.overnight_start_min,
                second=0,
                microsecond=0
            )
            end_time = now.replace(
                hour=self.config.overnight_end_hour,
                minute=self.config.overnight_end_min,
                second=0,
                microsecond=0
            )
        else:
            # Regular Tuesday - Friday
            if now.hour < self.config.overnight_end_hour:
                # Early morning before 09:30 -> started yesterday 18:00
                start_time = (now - timedelta(days=1)).replace(
                    hour=self.config.overnight_start_hour,
                    minute=self.config.overnight_start_min,
                    second=0,
                    microsecond=0
                )
                end_time = now.replace(
                    hour=self.config.overnight_end_hour,
                    minute=self.config.overnight_end_min,
                    second=0,
                    microsecond=0
                )
            else:
                # During day (after 09:30) or evening (after 18:00) -> use most recent completed overnight
                start_time = (now - timedelta(days=1)).replace(
                    hour=self.config.overnight_start_hour,
                    minute=self.config.overnight_start_min,
                    second=0,
                    microsecond=0
                )
                end_time = now.replace(
                    hour=self.config.overnight_end_hour,
                    minute=self.config.overnight_end_min,
                    second=0,
                    microsecond=0
                )

        # Ensure end_time does not exceed current time if in progress
        # (IBKR rejects endDateTime in future)
        return start_time, end_time

    async def fetch_overnight_bars(self) -> list[BarData]:
        """Fetches 1-minute trade bars for the overnight session."""
        start_time, end_time = self.get_overnight_window()
        now = datetime.now(self.tz)

        # Clamping end_time to now if end_time is in the future
        request_end = min(end_time, now) if end_time > now else end_time
        
        logger.info(f"Fetching overnight bars for window {start_time.strftime('%Y-%m-%d %H:%M')} to {request_end.strftime('%Y-%m-%d %H:%M')} ET")

        # IBKR duration string rule:
        # Use "1 D" or "2 D" to avoid "greater than 86400 seconds" error
        duration_days = max(1, (request_end.date() - start_time.date()).days + 1)
        duration_str = f"{duration_days} D"

        try:
            bars = await self.ib.reqHistoricalDataAsync(
                contract=self.contract,
                endDateTime=request_end,
                durationStr=duration_str,
                barSizeSetting="1 min",
                whatToShow="TRADES",
                useRTH=False,
                formatDate=1,
                keepUpToDate=False
            )
            
            # Filter returned bars to only include those strictly in [start_time, end_time]
            filtered_bars = []
            for b in bars:
                # b.date can be datetime or string depending on IB response
                if isinstance(b.date, datetime):
                    bar_dt = b.date if b.date.tzinfo else b.date.replace(tzinfo=self.tz)
                else:
                    try:
                        bar_dt = datetime.strptime(str(b.date), "%Y%m%d %H:%M:%S").replace(tzinfo=self.tz)
                    except ValueError:
                        bar_dt = datetime.strptime(str(b.date), "%Y%m%d").replace(tzinfo=self.tz)
                
                if start_time <= bar_dt <= request_end:
                    filtered_bars.append(b)

            logger.info(f"Fetched {len(bars)} total bars, filtered to {len(filtered_bars)} overnight session bars.")
            return filtered_bars if filtered_bars else bars
        except Exception as e:
            logger.error(f"Failed to fetch historical data: {e}")
            raise
