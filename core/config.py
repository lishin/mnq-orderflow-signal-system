from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

@dataclass
class ConnectionConfig:
    host: str = "127.0.0.1"
    port: int = 7497
    client_id: int = 10
    timeout: int = 15

@dataclass
class ContractConfig:
    symbol: str = "MNQ"
    exchange: str = "CME"
    currency: str = "USD"
    expiry: str = ""

@dataclass
class FRVPConfig:
    tick_size: float = 0.25
    value_area_pct: float = 0.70
    algorithm: str = "steidlmayer_2bin"
    overnight_start_hour: int = 18
    overnight_start_min: int = 0
    overnight_end_hour: int = 9
    overnight_end_min: int = 30

@dataclass
class OrderflowConfig:
    big_trade_threshold: int = 200
    dynamic_threshold_enabled: bool = True
    dynamic_threshold_percentile: int = 95
    dynamic_threshold_window: int = 300
    absorption_lookback_bars: int = 3
    absorption_imbalance_ratio: float = 2.5
    absorption_price_proximity_ticks: int = 8

@dataclass
class SignalConfig:
    cooldown_after_open_secs: int = 300
    sl_buffer_ticks: int = 3
    auto_trade_enabled: bool = False
    auto_trade_quantity: int = 1
    min_confidence_score: int = 60

@dataclass
class WebhookConfig:
    telegram_enabled: bool = False
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

@dataclass
class DashboardConfig:
    refresh_fps: int = 4
    max_signal_log_rows: int = 15

@dataclass
class AppConfig:
    connection: ConnectionConfig = field(default_factory=ConnectionConfig)
    contract: ContractConfig = field(default_factory=ContractConfig)
    frvp: FRVPConfig = field(default_factory=FRVPConfig)
    orderflow: OrderflowConfig = field(default_factory=OrderflowConfig)
    signal: SignalConfig = field(default_factory=SignalConfig)
    webhook: WebhookConfig = field(default_factory=WebhookConfig)
    dashboard: DashboardConfig = field(default_factory=DashboardConfig)

def load_config(path: Path) -> AppConfig:
    if not path.exists():
        logger.warning(f"Config file {path} not found. Using defaults.")
        return AppConfig()
    
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except Exception as e:
        logger.error(f"Error reading config file {path}: {e}")
        return AppConfig()
    
    return AppConfig(
        connection=ConnectionConfig(**data.get("connection", {})),
        contract=ContractConfig(**data.get("contract", {})),
        frvp=FRVPConfig(**data.get("frvp", {})),
        orderflow=OrderflowConfig(**data.get("orderflow", {})),
        signal=SignalConfig(**data.get("signal", {})),
        webhook=WebhookConfig(**data.get("webhook", {})),
        dashboard=DashboardConfig(**data.get("dashboard", {}))
    )
