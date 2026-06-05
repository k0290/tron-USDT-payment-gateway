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
        None, description="TRX 源钱包私钥（hex格式，用于能量委托与地址激活）"
    )

    SWEEP_MIN_AMOUNT_USDT: float = Field(
        default=10.0,
        gt=0,
        description="归集最小金额（USDT），地址余额低于此值不归集",
    )

    EXPIRE_TIME_WINDOW: int = Field(
        default=3600,
        gt=0,
        description="订单支付有效期（秒），超时后 pending 订单标记为 expired",
    )

    # 能量获取方式：'delegate'（冻结/委托，默认）或 'rent'（从 tronenergy.market 租用）
    ENERGY_MODE: str = Field(
        default="delegate",
        description="能量获取方式：'delegate' 冻结委托 / 'rent' 市场租用",
    )

    # tronenergy.market 租用能量配置（ENERGY_MODE='rent' 时使用）
    TRONENERGY_API_SERVER: str = Field(
        default="https://api.tronenergy.market",
        description="tronenergy.market API 地址",
    )
    TRONENERGY_SERVER_ADDRESS: str = Field(
        default="TEMkRxLtCCdL4BCwbPXbbNWe4a9gtJ7kq7",
        description="tronenergy.market 收款地址（支付能量费用）",
    )
    TRONENERGY_API_KEY: Optional[str] = Field(
        None,
        description="tronenergy.market API Key（信用额度模式，免逐单签名；需与付款地址匹配）",
    )
    TRONENERGY_PAYER_ADDRESS: Optional[str] = Field(
        None,
        description="信用额度模式下的付款地址（必须与 API Key 匹配）",
    )
    RENT_ENERGY_AMOUNT: int = Field(
        default=65_000,
        gt=0,
        description="每次租用的能量点数（单笔 USDT 转账约需 65000）",
    )
    RENT_DURATION_SECONDS: int = Field(
        default=600,
        gt=0,
        description="租用时长（秒），10 分钟足够完成一次归集",
    )
    RENT_PRICE_SUN: int = Field(
        default=50,
        gt=0,
        description="出价（sun/能量/天）。值越高越易成交，同时费用越高",
    )
    RENT_PARTFILL: bool = Field(
        default=True, description="允许多个出借方共同成交订单"
    )
    RENT_WAIT_TIMEOUT: int = Field(
        default=60,
        gt=0,
        description="下单后等待能量到账的最长秒数",
    )
    RENT_FALLBACK_TO_DELEGATE: bool = Field(
        default=True,
        description="租用失败时是否回退到冻结/委托方式（需配置 TRX_SOURCE_PRIVATE_KEY）",
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
