from __future__ import annotations

import asyncio
import logging
from ib_async import IB

from .config import ConnectionConfig

logger = logging.getLogger(__name__)

class ConnectionManager:
    """Manages the Interactive Brokers connection with auto-reconnect functionality."""
    
    def __init__(self, config: ConnectionConfig):
        self.config = config
        self._ib = IB()
        self._reconnect_task: asyncio.Task | None = None
        self._is_connecting = False

        self._ib.disconnectedEvent += self._on_disconnected
        self._ib.errorEvent += self._on_error

    @property
    def ib(self) -> IB:
        return self._ib

    @property
    def is_connected(self) -> bool:
        return self._ib.isConnected()

    async def connect(self) -> IB:
        """Connects to the IB gateway or TWS asynchronously."""
        if self.is_connected or self._is_connecting:
            return self._ib
            
        self._is_connecting = True
        try:
            logger.info(f"Connecting to IB at {self.config.host}:{self.config.port} with Client ID {self.config.client_id}")
            await self._ib.connectAsync(
                host=self.config.host,
                port=self.config.port,
                clientId=self.config.client_id,
                timeout=self.config.timeout
            )
            logger.info("Successfully connected to IB.")
            return self._ib
        except Exception as e:
            logger.error(f"Failed to connect to IB: {e}")
            raise
        finally:
            self._is_connecting = False

    async def disconnect(self):
        """Cleanly disconnects from IB and prevents auto-reconnect."""
        logger.info("Disconnecting from IB.")
        self._ib.disconnectedEvent -= self._on_disconnected
        if self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()
        self._ib.disconnect()

    def _on_disconnected(self):
        """Event handler for unexpected disconnects."""
        logger.warning("IB disconnected unexpectedly. Scheduling reconnect.")
        if self._reconnect_task is None or self._reconnect_task.done():
            self._reconnect_task = asyncio.create_task(self._reconnect())

    def _on_error(self, reqId: int, errorCode: int, errorString: str, contract: object):
        """Logs IB errors and status codes."""
        # 2100-2199 are informational/market data connectivity notices, not fatal errors
        if 2100 <= errorCode <= 2199:
            logger.info(f"IB Notice {errorCode}: {errorString}")
        elif errorCode in (321, 322, 202, 1100, 1101, 1102):
            logger.warning(f"IB Warning {errorCode} (ReqId {reqId}): {errorString}")
        else:
            logger.error(f"IB Error {errorCode} (ReqId {reqId}): {errorString}")

    async def _reconnect(self):
        """Reconnects to IB with exponential backoff."""
        delay = 1
        max_delay = 60
        retries = 0
        max_retries = 10
        
        while not self.is_connected and retries < max_retries:
            try:
                await asyncio.sleep(delay)
                logger.info(f"Attempting to reconnect... (Try {retries + 1}/{max_retries})")
                await self.connect()
                if self.is_connected:
                    logger.info("Reconnection successful.")
                    return
            except Exception as e:
                logger.error(f"Reconnection attempt {retries + 1} failed: {e}")
                
            retries += 1
            delay = min(delay * 2, max_delay)
            
        logger.error("Exceeded maximum reconnection retries.")
