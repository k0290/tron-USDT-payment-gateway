# tron_payment/sweep.py
"""
资金归集服务

将收款地址的 USDT 自动归集到冷钱包
"""

import logging
import asyncio
import httpx
import tronpy
from tronpy import AsyncTron
from tronpy.providers.async_http import AsyncHTTPProvider
from tronpy.keys import PrivateKey
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorDatabase
from bip_utils import Bip39SeedGenerator, Bip44, Bip44Coins, Bip44Changes

from .config import PaymentConfig
from .exceptions import SweepError

logger = logging.getLogger(__name__)

# 常量
USDT_SWEEP_THRESHOLD_DEFAULT = 10  # 默认归集阈值（10 USDT）
USDT_TRANSFER_FEE_LIMIT_SUN = (
    15_000_000  # USDT 转账的 fee_limit（15 TRX，单位：sun）- 这是最大限制，不是实际费用
)
DELEGATED_ENERGY_SUN = (
    80_000_000  # 委托的能量（80k Energy，单位：sun）- 足够支付 USDT 转账
)
ADDRESS_ACTIVATION_AMOUNT_SUN = 100_000  # 地址激活所需的最小 TRX（0.1 TRX，单位：sun）


class SweepService:
    """
    资金归集服务

    功能：
    - 扫描有余额的地址
    - 构建 USDT 转账交易
    - 调用签名服务签名交易
    - 广播交易到区块链
    - 将 USDT 归集到冷钱包

    注意：
    - 需要配置 COLD_WALLET_ADDRESS（冷钱包地址）
    - 需要配置 SIGNING_SERVICE_URL（签名服务地址）
    - 签名服务接口：POST /sign-transaction
      请求参数：{"txid": "...", "address_index": 123}
      返回：{"signature": "..."}
    """

    def __init__(self, config: PaymentConfig, db: AsyncIOMotorDatabase):
        """
        初始化归集服务

        Args:
            config: 支付配置
            db: MongoDB 数据库
        """
        self.config = config
        self.db = db

        if not self.config.COLD_WALLET_ADDRESS:
            logger.warning("⚠️ COLD_WALLET_ADDRESS 未配置，归集功能不可用")

        if not self.config.SIGNING_SERVICE_URL:
            logger.warning("⚠️ SIGNING_SERVICE_URL 未配置，归集功能不可用")

        logger.info("✅ SweepService 初始化成功")

    async def check_signing_service(self) -> bool:
        """
        检查签名服务是否配置

        Returns:
            bool: 是否已配置
        """
        if not self.config.SIGNING_SERVICE_URL:
            logger.warning(
                "签名服务 URL 未配置 (SIGNING_SERVICE_URL)，资金归集功能将被禁用"
            )
            return False

        if not self.config.COLD_WALLET_ADDRESS:
            logger.warning(
                "冷钱包地址未配置 (COLD_WALLET_ADDRESS)，资金归集功能将被禁用"
            )
            return False

        logger.info(f"✅ 签名服务已配置: {self.config.SIGNING_SERVICE_URL}")
        logger.info(f"✅ 冷钱包地址: {self.config.COLD_WALLET_ADDRESS}")
        return True

    def _get_trx_source_private_key(self):
        """
        获取 TRX 源钱包的私钥

        Returns:
            PrivateKey: TRX 源钱包私钥对象
        """
        if not self.config.TRX_SOURCE_PRIVATE_KEY:
            raise SweepError("TRX_SOURCE_PRIVATE_KEY 必须配置")

        try:
            return PrivateKey(bytes.fromhex(self.config.TRX_SOURCE_PRIVATE_KEY))
        except Exception as e:
            logger.error(f"解析 TRX_SOURCE_PRIVATE_KEY 失败: {e}")
            raise SweepError(f"Invalid TRX_SOURCE_PRIVATE_KEY: {e}")

    async def _get_available_frozen_energy(
        self, address: str, client: AsyncTron
    ) -> int:
        """
        获取地址可用的冻结能量余额（未委托的冻结能量）

        注意：这个方法返回的是总冻结能量，不包括已委托的部分。
        实际可委托的能量 = 总冻结能量 - 已委托能量

        Args:
            address: 地址
            client: Tron 客户端

        Returns:
            int: 总冻结能量（单位：sun），不包括已委托部分
        """
        try:
            account_info = await client.get_account(address)
            # 获取冻结的能量余额（frozenV2 包含所有冻结的资源）
            frozen_balance = 0
            frozen_v2 = account_info.get("frozenV2", [])
            for frozen in frozen_v2:
                if frozen.get("type") == "ENERGY":
                    frozen_balance += frozen.get("amount", 0)

            logger.debug(
                f"地址 {address} 总冻结能量: {frozen_balance / 1_000_000:.0f}k Energy"
            )
            return frozen_balance
        except Exception as e:
            logger.warning(f"获取地址 {address} 的冻结能量余额失败: {e}")
            return 0

    async def _ensure_frozen_energy(
        self,
        source_address: str,
        source_private_key: PrivateKey,
        required_energy_sun: int,
        client: AsyncTron,
    ) -> bool:
        """
        确保主钱包有足够的冻结能量，如果没有则冻结更多

        Args:
            source_address: 主钱包地址
            source_private_key: 主钱包私钥
            required_energy_sun: 需要的能量（单位：sun）
            client: Tron 客户端

        Returns:
            bool: 是否成功
        """
        try:
            # 检查当前可用的冻结能量
            available_energy = await self._get_available_frozen_energy(
                source_address, client
            )

            logger.info(
                f"主钱包 {source_address} 当前可用冻结能量: {available_energy / 1_000_000:.0f}k Energy"
            )

            if available_energy >= required_energy_sun:
                logger.info("已有足够的冻结能量，无需额外冻结")
                return True

            # 需要冻结的能量数量
            energy_to_freeze = required_energy_sun - available_energy
            energy_to_freeze_trx = energy_to_freeze / 1_000_000

            logger.info(
                f"需要冻结 {energy_to_freeze_trx:.0f} TRX 以获得 {energy_to_freeze / 1_000_000:.0f}k Energy"
            )

            # 检查余额是否足够
            source_balance = await client.get_account_balance(source_address)
            required_balance = energy_to_freeze_trx + 0.1  # 加上手续费

            if source_balance < required_balance:
                logger.error(
                    f"主钱包 {source_address} 余额不足: {source_balance:.6f} TRX, "
                    f"需要至少 {required_balance:.6f} TRX 用于冻结能量"
                )
                return False

            # 构建冻结能量交易
            txn = (
                await client.trx.freeze_balance(
                    source_address, int(energy_to_freeze), resource="ENERGY"
                )
                .fee_limit(1_000_000)  # 1 TRX fee limit
                .build()
            )

            # 使用私钥签名交易
            txn_ret = txn.sign(source_private_key)

            # 广播交易
            result = await txn_ret.broadcast()

            if result.get("result", False) or result.get("txid"):
                txid = result.get("txid") or (
                    result.txid if hasattr(result, "txid") else None
                )
                logger.info(
                    f"✅ 成功冻结 {energy_to_freeze_trx:.0f} TRX 获得能量，交易哈希: {txid}"
                )

                # 等待交易确认
                await asyncio.sleep(3)
                return True
            else:
                error_msg = result.get("message", "Unknown error")
                logger.error(f"冻结能量失败: {error_msg}")
                return False

        except Exception as e:
            logger.error(f"确保冻结能量时发生错误: {e}", exc_info=True)
            return False

    async def _activate_address(self, to_address: str, client: AsyncTron) -> bool:
        """
        激活目标地址（如果尚未激活）

        Tron 网络要求地址必须先被激活（接收至少一次 TRX 转账）
        才能接收能量委托或执行智能合约调用。

        Args:
            to_address: 目标地址
            client: Tron 客户端

        Returns:
            bool: 是否成功（如果地址已激活，返回 True）
        """
        try:
            # 检查地址是否已激活
            try:
                await client.get_account(to_address)
                logger.debug(f"地址 {to_address} 已激活")
                return True
            except tronpy.exceptions.AddressNotFound:
                # 地址未激活，需要激活
                logger.info(f"地址 {to_address} 未激活，正在激活...")

                # 获取源钱包私钥和地址
                source_private_key = self._get_trx_source_private_key()
                source_address = source_private_key.public_key.to_base58check_address()

                # 检查源钱包余额
                source_balance = await client.get_account_balance(source_address)
                required_balance = (
                    ADDRESS_ACTIVATION_AMOUNT_SUN / 1_000_000
                ) + 0.1  # 0.1 TRX + 手续费
                if source_balance < required_balance:
                    logger.error(
                        f"主钱包 {source_address} 余额不足: {source_balance:.6f} TRX, "
                        f"需要至少 {required_balance:.6f} TRX 用于激活地址"
                    )
                    return False

                # 构建 TRX 转账交易（激活地址）
                txn = (
                    await client.trx.transfer(
                        source_address, to_address, ADDRESS_ACTIVATION_AMOUNT_SUN
                    )
                    .fee_limit(1_000_000)  # 1 TRX fee limit
                    .build()
                )

                # 使用私钥签名交易
                txn_ret = txn.sign(source_private_key)

                # 广播交易
                result = await txn_ret.broadcast()

                if result.get("result", False) or result.get("txid"):
                    txid = result.get("txid") or (
                        result.txid if hasattr(result, "txid") else None
                    )
                    logger.info(f"✅ 成功激活地址 {to_address}，交易哈希: {txid}")

                    # 等待交易确认
                    await asyncio.sleep(3)
                    return True
                else:
                    error_msg = result.get("message", "Unknown error")
                    logger.error(f"激活地址失败: {error_msg}")
                    return False

        except Exception as e:
            logger.error(f"激活地址时发生错误: {e}", exc_info=True)
            return False

    async def _delegate_energy(self, to_address: str, client: AsyncTron) -> bool:
        """
        从主钱包向目标地址委托能量（Energy）

        使用能量委托代替发送 TRX，可以大幅节省成本。
        能量委托是免费的（只需要冻结 TRX），委托后可以撤销并重复使用。

        Args:
            to_address: 目标地址（支付地址）
            client: Tron 客户端

        Returns:
            bool: 是否成功
        """
        try:
            # 获取源钱包私钥和地址
            source_private_key = self._get_trx_source_private_key()
            source_address = source_private_key.public_key.to_base58check_address()

            logger.info(
                f"准备从主钱包 {source_address} 向 {to_address} 委托 {DELEGATED_ENERGY_SUN / 1_000_000:.0f}k Energy..."
            )

            # 首先确保目标地址已激活（可能需要多次检查）
            address_activated = False
            for activation_attempt in range(3):
                address_activated = await self._activate_address(to_address, client)
                if address_activated:
                    # 再次验证地址确实已激活（等待区块链确认）
                    try:
                        await asyncio.sleep(2)  # 等待激活交易确认
                        account_info = await client.get_account(to_address)
                        if account_info:
                            logger.info(f"✅ 地址 {to_address} 已确认激活")
                            break
                    except tronpy.exceptions.AddressNotFound:
                        if activation_attempt < 2:
                            logger.info(
                                f"地址激活中，等待后重试（尝试 {activation_attempt + 1}/3）..."
                            )
                            await asyncio.sleep(3)
                            continue
                        else:
                            logger.error(f"地址 {to_address} 激活后仍未在链上可见")
                            return False

            if not address_activated:
                logger.error(f"无法激活地址 {to_address}，跳过委托")
                return False

            # 先检查并确保有足够的冻结能量（考虑可能已有部分被委托）
            # 我们冻结比需要量多 20% 以确保有足够的可用能量
            buffer_energy = int(DELEGATED_ENERGY_SUN * 1.2)
            energy_ready = await self._ensure_frozen_energy(
                source_address, source_private_key, buffer_energy, client
            )

            if not energy_ready:
                logger.error("无法确保足够的冻结能量，跳过委托")
                return False

            # 等待冻结生效
            await asyncio.sleep(2)

            # 尝试委托能量，如果失败则冻结更多能量后重试
            max_retries = 2
            for attempt in range(max_retries):
                # 构建能量委托交易
                # lock=False 表示不锁定，可以随时撤销
                txn = (
                    await client.trx.delegate_resource(
                        source_address,
                        to_address,
                        DELEGATED_ENERGY_SUN,
                        resource="ENERGY",
                        lock=False,
                    )
                    .fee_limit(1_000_000)  # 1 TRX fee limit
                    .build()
                )

                # 使用私钥签名交易
                txn_ret = txn.sign(source_private_key)

                # 广播交易
                try:
                    result = await txn_ret.broadcast()

                    if result.get("result", False) or result.get("txid"):
                        txid = result.get("txid") or (
                            result.txid if hasattr(result, "txid") else None
                        )
                        logger.info(
                            f"✅ 成功向 {to_address} 委托 {DELEGATED_ENERGY_SUN / 1_000_000:.0f}k Energy，"
                            f"交易哈希: {txid}"
                        )

                        # 等待交易确认（能量委托需要一些时间生效）
                        await asyncio.sleep(3)
                        return True
                    else:
                        error_msg = result.get("message", "Unknown error")
                        # 检查是否是能量不足的错误
                        if (
                            "delegateBalance must be less than or equal to available FreezeEnergyV2 balance"
                            in error_msg
                        ):
                            if attempt < max_retries - 1:
                                logger.warning(
                                    f"委托能量失败（尝试 {attempt + 1}/{max_retries}）: {error_msg}"
                                )
                                logger.info("冻结更多能量后重试...")

                                # 冻结更多能量（额外冻结所需的数量）
                                energy_ready = await self._ensure_frozen_energy(
                                    source_address,
                                    source_private_key,
                                    DELEGATED_ENERGY_SUN,
                                    client,
                                )

                                if not energy_ready:
                                    logger.error("无法冻结足够的能量")
                                    return False

                                # 等待冻结生效
                                await asyncio.sleep(3)
                                continue
                            else:
                                logger.error(
                                    f"委托能量失败（已重试 {max_retries} 次）: {error_msg}"
                                )
                                return False
                        else:
                            logger.error(f"委托能量失败: {error_msg}")
                            return False

                except tronpy.exceptions.ValidationError as e:
                    error_msg = str(e)

                    # 检查是否是地址未激活的错误
                    if (
                        "not exists" in error_msg
                        or "Account" in error_msg
                        and "not exists" in error_msg
                    ):
                        logger.warning(f"地址 {to_address} 似乎未激活: {error_msg}")
                        if attempt < max_retries - 1:
                            logger.info("重新激活地址后重试...")
                            # 强制重新激活地址
                            await self._activate_address(to_address, client)
                            await asyncio.sleep(5)  # 等待激活生效
                            continue
                        else:
                            logger.error(f"地址激活失败（已重试 {max_retries} 次）")
                            return False

                    # 检查是否是能量不足的错误
                    elif (
                        "delegateBalance must be less than or equal to available FreezeEnergyV2 balance"
                        in error_msg
                    ):
                        if attempt < max_retries - 1:
                            logger.warning(
                                f"委托能量失败（尝试 {attempt + 1}/{max_retries}）: {error_msg}"
                            )
                            logger.info("冻结更多能量后重试...")

                            # 冻结更多能量
                            energy_ready = await self._ensure_frozen_energy(
                                source_address,
                                source_private_key,
                                DELEGATED_ENERGY_SUN,
                                client,
                            )

                            if not energy_ready:
                                logger.error("无法冻结足够的能量")
                                return False

                            # 等待冻结生效
                            await asyncio.sleep(3)
                            continue
                        else:
                            logger.error(
                                f"委托能量失败（已重试 {max_retries} 次）: {error_msg}"
                            )
                            return False
                    else:
                        raise

        except Exception as e:
            logger.error(f"委托能量时发生错误: {e}", exc_info=True)
            return False

    async def _undelegate_energy(self, from_address: str, client: AsyncTron) -> bool:
        """
        撤销从主钱包向目标地址的能量委托

        撤销后，能量可以重新委托给其他地址，实现重复使用。

        Args:
            from_address: 目标地址（支付地址）
            client: Tron 客户端

        Returns:
            bool: 是否成功
        """
        try:
            # 获取源钱包私钥和地址
            source_private_key = self._get_trx_source_private_key()
            source_address = source_private_key.public_key.to_base58check_address()

            logger.info(
                f"准备撤销从主钱包 {source_address} 向 {from_address} 的能量委托..."
            )

            # 构建撤销能量委托交易
            txn = (
                await client.trx.undelegate_resource(
                    source_address,
                    from_address,
                    DELEGATED_ENERGY_SUN,
                    resource="ENERGY",
                )
                .fee_limit(1_000_000)  # 1 TRX fee limit
                .build()
            )

            # 使用私钥签名交易
            txn_ret = txn.sign(source_private_key)

            # 广播交易
            result = await txn_ret.broadcast()

            if result.get("result", False) or result.get("txid"):
                txid = result.get("txid") or (
                    result.txid if hasattr(result, "txid") else None
                )
                logger.info(
                    f"✅ 成功撤销向 {from_address} 的能量委托，交易哈希: {txid}"
                )
                return True
            else:
                error_msg = result.get("message", "Unknown error")
                logger.warning(f"撤销能量委托失败（可能已撤销或不存在）: {error_msg}")
                # 撤销失败不算严重错误，继续执行
                return False

        except Exception as e:
            logger.warning(f"撤销能量委托时发生错误（继续执行）: {e}")
            # 撤销失败不算严重错误，不影响主流程
            return False

    async def sweep_funds(self, min_amount: float = None):
        """
        执行资金归集

        Args:
            min_amount: 最小归集金额（USDT），默认 10 USDT

        工作流程（使用能量委托，节省 TRX）：
        1. 扫描所有地址
        2. 检查 USDT 余额是否 >= min_amount
        3. 从主钱包委托 ~80k Energy 到目标地址
        4. 构建未签名交易（使用委托的能量支付手续费）
        5. 调用签名服务签名
        6. 广播交易
        7. 撤销能量委托（释放能量以便重复使用）
        8. 更新数据库余额

        注意：
        - 能量委托需要冻结等量的 TRX（1 TRX = 1 Energy）
        - 委托的能量可以撤销并重复使用，大幅节省成本
        - 相比直接发送 TRX，这种方式可以节省大量 TRX
        """
        # 先检查签名服务是否配置
        if not await self.check_signing_service():
            logger.info("跳过资金归集任务（签名服务未完全配置）")
            return

        # 设置默认阈值
        if min_amount is None:
            min_amount = USDT_SWEEP_THRESHOLD_DEFAULT

        min_amount_raw = int(min_amount * self.config.USDT_DECIMALS)

        logger.info(f"开始执行地址资金归集任务（最小金额: {min_amount} USDT）...")

        # 初始化 Tron 客户端
        headers = {"TRON-PRO-API-KEY": self.config.TRONGRID_API_KEY or ""}
        async with httpx.AsyncClient(headers=headers, timeout=30.0) as http_client:
            provider = AsyncHTTPProvider(
                endpoint_uri=self.config.TRONGRID_API_URL, client=http_client
            )
            client = AsyncTron(provider=provider)

            try:
                usdt_contract = await client.get_contract(
                    self.config.USDT_CONTRACT_ADDRESS
                )
            except Exception as e:
                logger.error(f"初始化 Tron 客户端或合约失败: {e}", exc_info=True)
                return

            swept_count = 0
            total_swept_amount = 0.0

            # 扫描所有地址
            async for addr_doc in self.db.addresses.find():
                address = addr_doc.get("address")
                address_index = addr_doc.get("index")

                if address is None or address_index is None:
                    continue

                try:
                    # 检查 USDT 余额
                    usdt_balance_raw = await usdt_contract.functions.balanceOf(address)
                    if (
                        usdt_balance_raw is None
                        or int(usdt_balance_raw) < min_amount_raw
                    ):
                        continue

                    usdt_balance = int(usdt_balance_raw) / self.config.USDT_DECIMALS

                    logger.info(
                        f"✅ 地址 {address}: USDT={usdt_balance:.6f}, "
                        f"准备归集到冷钱包"
                    )

                    # 检查是否配置了主钱包（用于委托能量）
                    if not self.config.TRX_SOURCE_PRIVATE_KEY:
                        logger.error(
                            f"未配置 TRX_SOURCE_PRIVATE_KEY，无法委托能量。"
                            f"请配置主钱包私钥以使用能量委托功能。"
                        )
                        continue

                    # 委托能量到目标地址（代替发送 TRX）
                    energy_delegated = await self._delegate_energy(address, client)
                    if not energy_delegated:
                        logger.error(f"向地址 {address} 委托能量失败，跳过归集")
                        continue

                    # 等待能量委托生效
                    await asyncio.sleep(2)

                    # 如果当前地址就是冷钱包，跳过
                    if address.lower() == self.config.COLD_WALLET_ADDRESS.lower():
                        logger.debug(f"地址 {address} 是冷钱包本身，跳过归集")
                        continue

                    # 执行归集（使用委托的能量支付手续费）
                    success = await self._sweep_single_address(
                        address,
                        address_index,
                        usdt_balance_raw,
                        usdt_contract,
                        client,
                        http_client,
                    )

                    # 撤销能量委托（释放能量以便重复使用）
                    # 无论归集成功与否，都尝试撤销能量委托
                    await self._undelegate_energy(address, client)

                    # 等待撤销完成，以便能量可以用于下一个地址
                    await asyncio.sleep(2)

                    if success:
                        swept_count += 1
                        total_swept_amount += usdt_balance

                except Exception as e:
                    logger.error(
                        f"处理地址 {address} 时发生未知错误: {e}", exc_info=True
                    )
                    continue

        logger.info(
            f"✅ 地址资金归集任务执行完毕。"
            f"成功归集: {swept_count} 个地址，总计: {total_swept_amount:.6f} USDT"
        )

    async def _sweep_single_address(
        self,
        address: str,
        address_index: int,
        usdt_balance_raw: int,
        usdt_contract,
        client: AsyncTron,
        http_client: httpx.AsyncClient,
    ) -> bool:
        """
        归集单个地址的资金

        Args:
            address: 地址
            address_index: 地址索引
            usdt_balance_raw: USDT 余额（原始值，带精度）
            usdt_contract: USDT 合约对象
            client: Tron 客户端
            http_client: HTTP 客户端

        Returns:
            bool: 是否成功
        """
        try:
            # 1. 构建未签名交易
            logger.info(f"正在为地址 {address} 构建归集交易...")
            txn_builder = await usdt_contract.functions.transfer(
                self.config.COLD_WALLET_ADDRESS, int(usdt_balance_raw)
            )
            unsigned_txn = (
                await txn_builder.with_owner(address)
                .fee_limit(USDT_TRANSFER_FEE_LIMIT_SUN)
                .build()
            )

            txid = unsigned_txn.txid
            if not txid:
                logger.error(f"为地址 {address} 构建的交易缺少 txID，跳过。")
                return False

            logger.info(f"✅ 交易构建成功，txID: {txid}")

            # 2. 调用签名服务获取签名
            payload = {"txid": txid, "address_index": address_index}

            logger.info(f"正在为地址 {address} 的交易请求签名...")
            try:
                response = await http_client.post(
                    f"{self.config.SIGNING_SERVICE_URL}/sign-transaction",
                    json=payload,
                    timeout=20.0,
                )
                response.raise_for_status()
                json_resp = response.json()

                signature = json_resp.get("signature")
                if not signature:
                    logger.error(f"签名服务未返回有效的 signature 字段: {json_resp}")
                    return False

                logger.info(f"✅ 成功从签名服务获取地址 {address} 的签名")

            except Exception as e:
                logger.error(f"调用签名服务时发生错误: {e}", exc_info=True)
                return False

            # 3. 广播交易
            try:
                signed_txn_payload = {
                    "signature": signature,
                    "txID": unsigned_txn.txid,
                    "raw_data": unsigned_txn._raw_data,
                }

                logger.info(f"准备广播地址 {address} 的交易...")

                # 直接调用 provider 的 make_request 方法
                result = await client.provider.make_request(
                    "wallet/broadcasttransaction", signed_txn_payload
                )

                if result.get("txid") and result.get("result", True):
                    logger.info(
                        f"🎉 成功广播地址 {address} 的归集交易。"
                        f"交易 HASH: {result.get('txid')}"
                    )

                    # 4. 更新数据库中的地址余额为 0
                    try:
                        swept_amount = int(usdt_balance_raw) / self.config.USDT_DECIMALS

                        await self.db.addresses.update_one(
                            {"address": address},
                            {
                                "$set": {
                                    "usdt_balance": 0.0,
                                    "updated_at": datetime.now(timezone.utc),
                                }
                            },
                        )

                        logger.info(
                            f"✅ 地址 {address} USDT 余额已更新为 0"
                            f"（已归集 {swept_amount:.6f} USDT）"
                        )

                    except Exception as e:
                        logger.error(
                            f"更新地址 {address} 余额时发生错误: {e}", exc_info=True
                        )

                    return True

                else:
                    # 广播失败
                    error_message_hex = result.get("message", "")
                    error_message = (
                        bytes.fromhex(error_message_hex).decode(
                            "utf-8", errors="ignore"
                        )
                        if error_message_hex
                        else str(result)
                    )
                    logger.error(f"广播交易失败，来自节点的响应: {error_message}")
                    return False

            except Exception as e:
                logger.error(f"广播已签名交易时发生异常: {e}", exc_info=True)
                return False

        except Exception as e:
            logger.error(f"归集地址 {address} 时发生错误: {e}", exc_info=True)
            return False
