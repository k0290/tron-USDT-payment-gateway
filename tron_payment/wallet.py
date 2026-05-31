# tron_payment/wallet.py
"""
HD 钱包服务 - 地址派生

使用 BIP44 标准从 XPUB 派生唯一的收款地址
"""

import logging
from typing import Optional
from bip_utils import Bip44, Bip44Coins, Bip44Changes
from motor.motor_asyncio import AsyncIOMotorDatabase

from .config import PaymentConfig
from .models import Invoice, Address
from .exceptions import WalletError

logger = logging.getLogger(__name__)


class WalletService:
    """
    HD 钱包服务

    功能：
    - 从 XPUB 派生唯一地址
    - 管理地址索引（原子操作）
    - 创建订单和地址记录
    """

    def __init__(self, config: PaymentConfig, db: AsyncIOMotorDatabase):
        """
        初始化钱包服务

        Args:
            config: 支付配置
            db: MongoDB 数据库实例
        """
        self.config = config
        self.db = db

        if not self.config.ACCOUNT_XPUB:
            raise WalletError("ACCOUNT_XPUB 未配置")

        logger.info("✅ WalletService 初始化成功")

    async def get_next_address_index(self) -> int:
        """
        获取下一个可用的派生索引（原子操作）

        Returns:
            int: 下一个可用的索引（从1开始）
        """
        result = await self.db.address_counter.find_one_and_update(
            {"_id": "address_index"},
            {"$inc": {"value": 1}},
            upsert=True,
            return_document=True,
        )

        index = result["value"] if result else 1
        logger.info(f"获取到新的地址索引: {index}")
        return index

    def derive_address(self, index: int) -> str:
        """
        从 XPUB 派生地址

        Args:
            index: 派生索引

        Returns:
            str: Tron 地址

        Raises:
            WalletError: 派生失败
        """
        try:
            bip44_acc = Bip44.FromExtendedKey(self.config.ACCOUNT_XPUB, Bip44Coins.TRON)
            bip44_addr = bip44_acc.Change(Bip44Changes.CHAIN_EXT).AddressIndex(index)
            address_str = bip44_addr.PublicKey().ToAddress()

            logger.debug(f"成功派生地址: {address_str} (索引: {index})")
            return address_str

        except Exception as e:
            logger.error(f"派生地址失败: {e}", exc_info=True)
            raise WalletError(f"派生地址失败: {e}")

    async def create_invoice(
        self,
        amount: float,
        merchant_id: Optional[str] = None,
        merchant_order_id: Optional[str] = None,
        user_id: Optional[int] = None,
        notify_url: Optional[str] = None,
        back_url: Optional[str] = None,
        pay_method: Optional[str] = None,
    ) -> tuple[Invoice, Address]:
        """
        创建订单并派生唯一的收款地址

        Args:
            amount: 订单金额 (USDT)
            merchant_id: 商户ID (可选)
            merchant_order_id: 商户订单号 (可选)
            user_id: 用户ID (可选)
            notify_url: 支付成功回调地址 (可选)
            back_url: 支付完成后跳转地址 (可选)
            pay_method: 支付渠道编码 (可选)

        Returns:
            tuple[Invoice, Address]: (订单对象, 地址对象)

        Raises:
            WalletError: 创建失败
        """
        try:
            # 1. 获取唯一索引
            index = await self.get_next_address_index()

            # 2. 派生地址
            address_str = self.derive_address(index)

            # 3. 创建订单
            invoice = Invoice(
                merchant_id=merchant_id,
                amount_due=amount,
                address=address_str,
                merchant_order_id=merchant_order_id,
                user_id=user_id,
                notify_url=notify_url,
                back_url=back_url,
                pay_method=pay_method,
            )

            # 4. 创建地址记录
            address = Address(address=address_str, index=index, invoice_id=invoice.id)

            # 5. 保存到数据库
            await self.db.invoices.insert_one(invoice.model_dump())
            await self.db.addresses.insert_one(address.model_dump())

            logger.info(
                f"✅ 订单创建成功: ID={invoice.id}, "
                f"金额={amount} USDT, 地址={address_str}"
            )

            return invoice, address

        except Exception as e:
            logger.error(f"创建订单失败: {e}", exc_info=True)
            raise WalletError(f"创建订单失败: {e}")

    async def get_invoice(self, invoice_id: str) -> Optional[Invoice]:
        """
        查询订单

        Args:
            invoice_id: 订单ID

        Returns:
            Invoice or None
        """
        # doc = await self.db.invoices.find_one({"_id": invoice_id})
        doc = await self.db.invoices.find_one({"id": invoice_id})
        if doc:
            return Invoice(**doc)
        return None

    async def get_address(self, address_str: str) -> Optional[Address]:
        """
        查询地址

        Args:
            address_str: Tron 地址

        Returns:
            Address or None
        """
        doc = await self.db.addresses.find_one({"address": address_str})
        if doc:
            return Address(**doc)
        return None
