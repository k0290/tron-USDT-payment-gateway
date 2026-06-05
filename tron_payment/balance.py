# tron_payment/balance.py
"""
余额同步服务

定期从链上同步地址的 USDT 和 TRX 余额
"""

import logging
import httpx
import tronpy
from tronpy import AsyncTron
from motor.motor_asyncio import AsyncIOMotorDatabase

from .config import PaymentConfig
from .exceptions import BalanceError
from .tron_helpers import build_async_tron_provider, get_usdt_contract

logger = logging.getLogger(__name__)


class BalanceSyncService:
    """
    余额同步服务

    功能：
    - 从链上查询地址余额
    - 更新数据库中的余额记录
    """

    def __init__(self, config: PaymentConfig, db: AsyncIOMotorDatabase):
        """
        初始化余额同步服务

        Args:
            config: 支付配置
            db: MongoDB 数据库
        """
        self.config = config
        self.db = db

        logger.info("✅ BalanceSyncService 初始化成功")

    async def sync_all_balances(self):
        """
        同步所有地址的余额

        推荐每5分钟执行一次
        """
        logger.info("开始同步地址余额...")

        async with httpx.AsyncClient(timeout=30.0) as http_client:
            provider = build_async_tron_provider(self.config, http_client)
            client = AsyncTron(provider=provider)

            try:
                usdt_contract = await get_usdt_contract(
                    client, self.config.USDT_CONTRACT_ADDRESS
                )
            except Exception as e:
                logger.error(f"初始化合约失败: {e}", exc_info=True)
                return

            synced_count = 0
            updated_count = 0

            async for addr_doc in self.db.addresses.find():
                try:
                    # 查询 USDT 余额
                    usdt_balance_raw = await usdt_contract.functions.balanceOf(addr_doc["address"])
                    usdt_balance = 0.0
                    if usdt_balance_raw is not None:
                        usdt_balance = int(usdt_balance_raw) / self.config.USDT_DECIMALS

                    # 查询 TRX 余额
                    try:
                        trx_balance = float(await client.get_account_balance(addr_doc["address"]))
                    except tronpy.exceptions.AddressNotFound:
                        trx_balance = 0.0

                    # 检查是否需要更新
                    if (abs(addr_doc.get("usdt_balance", 0) - usdt_balance) > 0.000001 or
                        abs(addr_doc.get("trx_balance", 0) - trx_balance) > 0.000001):

                        await self.db.addresses.update_one(
                            {"_id": addr_doc["_id"]},
                            {
                                "$set": {
                                    "usdt_balance": usdt_balance,
                                    "trx_balance": trx_balance
                                }
                            }
                        )
                        updated_count += 1
                        logger.debug(f"更新余额: {addr_doc['address']}, USDT={usdt_balance}")

                    synced_count += 1

                except Exception as e:
                    logger.error(f"同步地址 {addr_doc['address']} 失败: {e}")
                    continue

        logger.info(f"✅ 余额同步完成: 总计{synced_count}, 更新{updated_count}")
