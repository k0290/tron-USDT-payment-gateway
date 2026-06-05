# tron_payment/__init__.py
"""
Tron Payment SDK - USDT-TRC20 支付解决方案

提供完整的 Tron 链 USDT 支付功能：
- HD 钱包地址派生
- 区块链支付监听
- 资金自动归集
- 余额实时同步
"""

__version__ = "1.0.0"
__author__ = "Your Team"

from .config import PaymentConfig
from .wallet import WalletService
from .blockchain import BlockchainMonitor
from .sweep import SweepService
from .energy_rent import EnergyRentService
from .balance import BalanceSyncService
from .models import Invoice, Address, PaymentCallback, PaymentEvent
from .exceptions import (
    PaymentSDKError,
    WalletError,
    BlockchainError,
    ConfigError
)

__all__ = [
    "PaymentConfig",
    "WalletService",
    "BlockchainMonitor",
    "SweepService",
    "EnergyRentService",
    "BalanceSyncService",
    "Invoice",
    "Address",
    "PaymentCallback",
    "PaymentEvent",
    "PaymentSDKError",
    "WalletError",
    "BlockchainError",
    "ConfigError",
]
