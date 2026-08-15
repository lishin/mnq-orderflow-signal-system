from __future__ import annotations

import logging
import asyncio
from zoneinfo import ZoneInfo
import aiohttp

from core.config import WebhookConfig
from strategy.signal_engine import Signal

logger = logging.getLogger(__name__)

class TelegramNotifier:
    def __init__(self, config: WebhookConfig):
        self.config = config
        self._session: aiohttp.ClientSession | None = None
        self._sent_signals: set[str] = set()
        
    async def start(self) -> None:
        if self.config.telegram_enabled:
            self._session = aiohttp.ClientSession()
            logger.info("Telegram notifier started.")

    async def stop(self) -> None:
        if self._session:
            await self._session.close()
            logger.info("Telegram notifier stopped.")

    async def send_signal(self, signal: Signal) -> None:
        if not self.config.telegram_enabled or not self._session:
            return

        sig_id = f"{signal.timestamp.timestamp()}_{signal.signal_type}"
        if sig_id in self._sent_signals:
            return
        
        self._sent_signals.add(sig_id)

        is_long = "LONG" in signal.signal_type
        icon = "🟢 BUY SIGNAL" if is_long else "🔴 SELL SIGNAL"
        
        time_str = signal.timestamp.astimezone(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M:%S ET")

        msg = (
            f"{icon}: {signal.signal_type}\n\n"
            f"<b>Entry:</b> <code>{signal.entry:,.2f}</code>\n"
            f"<b>Stop Loss:</b> <code>{signal.stop_loss:,.2f}</code>\n"
            f"<b>Take Profit 1:</b> <code>{signal.take_profit_1:,.2f}</code>\n"
        )
        if signal.take_profit_2:
            msg += f"<b>Take Profit 2:</b> <code>{signal.take_profit_2:,.2f}</code>\n"
            
        msg += (
            f"<b>Confidence:</b> <b>{signal.confidence}%</b>\n"
            f"<b>Reason:</b> <i>{signal.reason}</i>\n\n"
            f"⏱ {time_str}"
        )

        url = f"https://api.telegram.org/bot{self.config.telegram_bot_token}/sendMessage"
        payload = {
            "chat_id": self.config.telegram_chat_id,
            "text": msg,
            "parse_mode": "HTML"
        }

        try:
            for _ in range(2): # Retry once
                async with self._session.post(url, json=payload) as resp:
                    if resp.status == 200:
                        logger.info(f"Telegram message sent for signal {signal.signal_type}")
                        return
                    else:
                        logger.warning(f"Failed to send Telegram message: {resp.status} {await resp.text()}")
                await asyncio.sleep(1)
        except Exception as e:
            logger.error(f"Error sending Telegram message: {e}")

    async def send_status(self, message: str) -> None:
        if not self.config.telegram_enabled or not self._session:
            return

        url = f"https://api.telegram.org/bot{self.config.telegram_bot_token}/sendMessage"
        payload = {
            "chat_id": self.config.telegram_chat_id,
            "text": message
        }

        try:
            async with self._session.post(url, json=payload) as resp:
                if resp.status != 200:
                    logger.warning(f"Failed to send status update: {resp.status}")
        except Exception as e:
            logger.error(f"Error sending status update: {e}")
