# tron_payment/blockchain.py
"""
区块链监听服务

监听 Tron 链上的 USDT 转账，自动确认订单支付
"""

import logging
import httpx
import asyncio
from typing import Optional, Callable, Any
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorDatabase

from .config import PaymentConfig
from .models import Invoice, PaymentEvent
from .exceptions import BlockchainError

logger = logging.getLogger(__name__)


class BlockchainMonitor:
    """
    区块链支付监听器

    功能：
    - 监听待支付订单
    - 查询链上交易
    - 确认支付并更新订单状态
    - 触发支付回调
    """

    def __init__(
        self,
        config: PaymentConfig,
        db: AsyncIOMotorDatabase,
        on_payment_confirmed: Optional[Callable[[PaymentEvent], Any]] = None,
    ):
        """
        初始化区块链监听器

        Args:
            config: 支付配置
            db: MongoDB 数据库
            on_payment_confirmed: 支付确认回调函数
        """
        self.config = config
        self.db = db
        self.on_payment_confirmed = on_payment_confirmed

        logger.info("✅ BlockchainMonitor 初始化成功")

    async def check_payments(self):
        """
        检查所有待支付订单的链上交易

        这个方法应该被周期性调用（推荐30秒一次）
        """
        logger.debug("开始检查待支付订单...")

        pending_count = 0
        async for _ in self.db.invoices.find({"status": "pending"}):
            pending_count += 1

        if pending_count == 0:
            logger.debug("没有待支付订单")
            return

        logger.info(f"发现 {pending_count} 个待支付订单，开始检查...")

        async for invoice_doc in self.db.invoices.find({"status": "pending"}):
            try:
                await self._check_single_invoice(invoice_doc)
            except Exception as e:
                logger.error(
                    f"检查订单 {invoice_doc.get('id', invoice_doc.get('_id'))} 时发生错误: {e}",
                    exc_info=True,
                )

    async def _check_single_invoice(self, invoice_doc: dict):
        """检查单个订单的支付状态"""
        invoice_id = invoice_doc.get("id") or invoice_doc.get("_id")
        address = invoice_doc.get("address")
        amount_due = invoice_doc.get("amount_due")

        if not address or amount_due is None:
            logger.warning(
                f"订单 {invoice_id} 缺少必要字段: address={address}, amount_due={amount_due}"
            )
            return

        amount_due_raw = int(amount_due * self.config.USDT_DECIMALS)

        # 处理 created_at - MongoDB 可能返回 datetime 对象或字符串
        created_at = invoice_doc.get("created_at")
        if isinstance(created_at, str):
            # 尝试解析 ISO 格式字符串
            try:
                if created_at.endswith("Z"):
                    created_at = created_at[:-1] + "+00:00"
                created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                logger.warning(
                    f"订单 {invoice_id} 的 created_at 格式无法解析: {created_at}"
                )
                return
        elif not isinstance(created_at, datetime):
            logger.warning(
                f"订单 {invoice_id} 的 created_at 类型不正确: {type(created_at)}, 值: {created_at}"
            )
            return

        # 确保时区信息存在
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)

        min_timestamp = int(created_at.timestamp() * 1000)

        logger.debug(
            f"检查订单 {invoice_id}: 地址={address}, "
            f"金额={amount_due} USDT ({amount_due_raw} raw), "
            f"创建时间={created_at.isoformat()}"
        )

        # 查询 TronGrid API
        api_url = (
            f"{self.config.TRONGRID_API_URL}/v1/accounts/{address}/transactions/trc20"
        )
        headers = {"TRON-PRO-API-KEY": self.config.TRONGRID_API_KEY or ""}
        params = {
            "limit": 50,
            "only_to": "true",
            "contract_address": self.config.USDT_CONTRACT_ADDRESS,
            "min_block_timestamp": min_timestamp,
        }

        try:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.get(api_url, headers=headers, params=params)
                response.raise_for_status()

            data = response.json()

            if not data.get("success"):
                error_msg = data.get("error", "Unknown error")
                logger.warning(f"TronGrid API 返回错误: {error_msg}")
                return

            transactions = data.get("data", [])
            if not transactions:
                logger.debug(f"订单 {invoice_id} 地址 {address} 暂无交易记录")
                return

            logger.debug(
                f"订单 {invoice_id} 找到 {len(transactions)} 笔交易，开始匹配..."
            )

            # 查找匹配的交易
            for tx in transactions:
                try:
                    tx_amount = int(tx.get("value", 0))
                    tx_id = tx.get("transaction_id")
                    tx_timestamp = tx.get("block_timestamp", 0)

                    # 检查交易是否已被其他订单使用
                    if tx_id:
                        existing_invoice = await self.db.invoices.find_one(
                            {"txid": tx_id}
                        )
                        if existing_invoice:
                            existing_id = existing_invoice.get(
                                "id"
                            ) or existing_invoice.get("_id")
                            if str(existing_id) != str(invoice_id):
                                logger.debug(
                                    f"交易 {tx_id} 已被订单 {existing_id} 使用，跳过"
                                )
                                continue

                    # 检查金额是否匹配
                    if tx_amount == amount_due_raw:
                        logger.info(
                            f"✅ 找到匹配支付: 订单={invoice_id}, "
                            f"金额={amount_due} USDT, TX={tx_id}, "
                            f"时间戳={tx_timestamp}"
                        )
                        await self._confirm_payment(invoice_doc, tx)
                        return  # 找到匹配后立即返回
                    else:
                        logger.debug(
                            f"交易 {tx_id} 金额不匹配: "
                            f"期望={amount_due_raw}, 实际={tx_amount}"
                        )
                except Exception as e:
                    logger.warning(f"处理交易时出错: {e}, 交易数据: {tx}")
                    continue

        except httpx.HTTPError as e:
            logger.error(f"查询订单 {invoice_id} 的交易时网络错误: {e}")
        except Exception as e:
            logger.error(f"检查订单 {invoice_id} 时发生未知错误: {e}", exc_info=True)

    async def _confirm_payment(self, invoice_doc: dict, tx: dict):
        """确认支付并更新订单"""
        invoice_id = invoice_doc.get("id") or invoice_doc.get("_id")
        tx_id = tx.get("transaction_id")

        if not tx_id:
            logger.error(f"交易数据缺少 transaction_id: {tx}")
            return

        # 使用原子操作更新订单状态，确保只更新 pending 状态的订单
        # 这样可以防止竞态条件（多个检查同时进行时）
        # 构建查询条件：优先使用 _id（MongoDB ObjectId），如果没有则使用 id（UUID）
        update_filter = {"status": "pending"}  # 只更新待支付状态的订单

        if invoice_doc.get("_id"):
            update_filter["_id"] = invoice_doc["_id"]
        elif invoice_doc.get("id"):
            update_filter["id"] = invoice_doc["id"]
        else:
            logger.error(f"订单文档缺少 _id 和 id 字段，无法更新: {invoice_doc}")
            return

        update_result = await self.db.invoices.find_one_and_update(
            update_filter,
            {
                "$set": {
                    "status": "paid",
                    "paid_at": datetime.now(timezone.utc),
                    "txid": tx_id,
                    "payer_address": tx.get("from"),
                }
            },
            return_document=True,
        )

        if not update_result:
            logger.warning(
                f"订单 {invoice_id} 更新失败，可能已被其他进程更新或状态已改变"
            )
            return

        logger.info(f"✅ 订单 {invoice_id} 状态已更新为 paid，交易: {tx_id}")

        # 更新地址余额
        address = invoice_doc.get("address")
        amount_due = invoice_doc.get("amount_due")
        if address and amount_due:
            try:
                await self.db.addresses.update_one(
                    {"address": address},
                    {
                        "$inc": {"usdt_balance": amount_due},
                        "$set": {"updated_at": datetime.now(timezone.utc)},
                    },
                )
                logger.debug(f"地址 {address} 余额已更新，增加 {amount_due} USDT")
            except Exception as e:
                logger.error(f"更新地址 {address} 余额时出错: {e}", exc_info=True)

        # 触发回调
        if self.on_payment_confirmed:
            try:
                invoice = Invoice(**update_result)
                event = PaymentEvent(event_type="payment_confirmed", invoice=invoice)
                if asyncio.iscoroutinefunction(self.on_payment_confirmed):
                    await self.on_payment_confirmed(event)
                else:
                    self.on_payment_confirmed(event)
            except Exception as e:
                logger.error(f"支付回调执行失败: {e}", exc_info=True)

        logger.info(f"✅ 订单 {invoice_id} 支付确认完成")
