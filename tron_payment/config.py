# tron_payment/config.py
"""
配置管理
"""

from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings


class PaymentConfig(BaseSettings):
    """
    支付系统配置

    必需配置：
    - ACCOUNT_XPUB: BIP44 扩展公钥
    - TRONGRID_API_URL: TronGrid API 地址
    - USDT_CONTRACT_ADDRESS: USDT TRC20 合约地址

    可选配置：
    - TRONGRID_API_KEY: TronGrid API 密钥（推荐）
    - COLD_WALLET_ADDRESS: 冷钱包地址（归集功能需要）
    - SIGNING_SERVICE_URL: 签名服务地址（归集功能需要）
    """

    # 必需配置
    ACCOUNT_XPUB: str = Field(..., description="BIP44 扩展公钥，用于派生支付地址")
    TRONGRID_API_URL: str = Field(..., description="TronGrid API 地址")
    USDT_CONTRACT_ADDRESS: str = Field(..., description="USDT TRC20 合约地址")

    # 可选配置
    TRONGRID_API_KEY: Optional[str] = Field(None, description="TronGrid API 密钥")
    COLD_WALLET_ADDRESS: Optional[str] = Field(None, description="冷钱包地址")
    SIGNING_SERVICE_URL: Optional[str] = Field(None, description="签名服务URL")

    # TRX 源钱包配置（用于向支付地址发送 TRX 作为手续费）
    TRX_SOURCE_PRIVATE_KEY: Optional[str] = Field(
        None, description="TRX 源钱包私钥（hex格式，用于发送 TRX 手续费）"
    )
    TRX_SOURCE_ADDRESS: Optional[str] = Field(
        None, description="TRX 源钱包地址（可选，用于验证）"
    )

    SWEEP_MIN_AMOUNT_USDT: float = Field(
        default=10.0,
        gt=0,
        description="归集最小金额（USDT），地址余额低于此值不归集",
    )

    # USDT 精度
    USDT_DECIMALS: int = Field(default=1_000_000, description="USDT 精度（6位小数）")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


# 默认配置（测试网）
DEFAULT_TESTNET_CONFIG = {
    "TRONGRID_API_URL": "https://nile.trongrid.io",
    "USDT_CONTRACT_ADDRESS": "TXYZopYRdj2D9XRtbG411XZZ3kM5VkAeBf",  # Nile 测试网
}

# 默认配置（主网）
DEFAULT_MAINNET_CONFIG = {
    "TRONGRID_API_URL": "https://api.trongrid.io",
    "USDT_CONTRACT_ADDRESS": "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t",  # 主网
}
