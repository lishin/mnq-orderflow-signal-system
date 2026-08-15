from __future__ import annotations

import logging
from ib_async import IB, Future, ContractDetails

from .config import ContractConfig

logger = logging.getLogger(__name__)

class ContractManager:
    """Resolves and caches the futures contract to trade."""

    def __init__(self, ib: IB, config: ContractConfig):
        self.ib = ib
        self.config = config
        self._contract: Future | None = None

    async def resolve(self) -> Future:
        """Resolves the contract. Uses expiry if provided, otherwise auto-detects front month."""
        if self._contract is not None:
            return self._contract
            
        contract = Future(
            symbol=self.config.symbol,
            exchange=self.config.exchange,
            currency=self.config.currency,
            lastTradeDateOrContractMonth=self.config.expiry if self.config.expiry else ""
        )
        
        try:
            logger.info(f"Qualifying contract: {contract}")
            if not self.config.expiry:
                logger.info("No expiry specified, querying front month contract...")
                details = await self.ib.reqContractDetailsAsync(contract)
                if not details:
                    raise ValueError(f"Could not find contract details for {contract.symbol}")
                
                # Sort by expiry to get front month
                details.sort(key=lambda x: x.contract.lastTradeDateOrContractMonth)
                contract = details[0].contract
                logger.info(f"Auto-detected front month: {contract.lastTradeDateOrContractMonth}")
            else:
                qualifications = await self.ib.qualifyContractsAsync(contract)
                if not qualifications:
                     raise ValueError(f"Could not qualify contract: {contract}")
                contract = qualifications[0]
                
            self._contract = contract
            return self._contract
        except Exception as e:
            logger.error(f"Failed to resolve contract: {e}")
            raise

    @property
    def contract(self) -> Future:
        """Returns the cached qualified contract. Raises ValueError if not resolved."""
        if self._contract is None:
             raise ValueError("Contract has not been resolved. Call resolve() first.")
        return self._contract
        
    @property
    def tick_size(self) -> float:
        """Returns the tick size for the instrument."""
        if self.config.symbol == "MNQ":
            return 0.25
        return 0.25 # Default fallback
