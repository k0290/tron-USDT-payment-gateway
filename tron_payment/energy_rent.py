# tron_payment/energy_rent.py
"""
能量租用服务（tronenergy.market）

在归集前，向收款地址（子钱包）租用一次性能量，使其能够完成一次 USDT 转账，
租期结束后能量自动到期，无需冻结/撤销 TRX。

两种付款方式：
1. API Key + 信用额度（推荐）：先在 tronenergy.market 充值并申请 API Key，
   下单时只需带上 api_key，费用从信用额度扣除，无需逐单签名。
2. 签名交易：用运营钱包私钥（TRX_SOURCE_PRIVATE_KEY）即时签名一笔 TRX 转账支付订单。

参考官方示例：https://github.com/tronenergymarket/tronenergy-api-examples
接口：POST {API_SERVER}/order/new
"""

import asyncio
import json
import logging

import httpx
from tronpy import AsyncTron
from tronpy.keys import PrivateKey

from .config import PaymentConfig

logger = logging.getLogger(__name__)

ENERGY_RESOURCE = 0  # 0=Energy, 1=Bandwidth
SECONDS_PER_DAY = 86_400


class EnergyRentService:
    """从 tronenergy.market 租用能量并交付到目标地址。"""

    def __init__(self, config: PaymentConfig):
        self.config = config

    def _calc_payment_sun(self, amount: int, duration: int, price: int) -> int:
        """
        计算订单费用（sun）。

        与官方示例一致：不足 1 天的订单按 1 天计费。
        payment = price * amount * (duration + (1天 if duration < 1天 else 0)) / 1天
        """
        billable_duration = duration + (SECONDS_PER_DAY if duration < SECONDS_PER_DAY else 0)
        return int((price * amount * billable_duration) / SECONDS_PER_DAY)

    async def get_available_energy(
        self, target_address: str, client: AsyncTron
    ) -> int:
        """查询目标地址当前可用能量（EnergyLimit - EnergyUsed）。"""
        try:
            resource = await client.get_account_resource(target_address)
        except Exception as e:
            logger.debug(f"查询 {target_address} 能量资源失败: {e}")
            return 0

        energy_limit = int(resource.get("EnergyLimit", 0) or 0)
        energy_used = int(resource.get("EnergyUsed", 0) or 0)
        return max(0, energy_limit - energy_used)

    def required_energy_for_sweep(self) -> int:
        """单笔 USDT 归集所需的能量点数。"""
        return self.config.RENT_ENERGY_AMOUNT

    async def _build_order_params(
        self,
        target_address: str,
        client: AsyncTron,
        amount: int,
    ) -> dict:
        """构建 /order/new 请求参数（自动选择信用额度或签名交易付款）。"""
        duration = self.config.RENT_DURATION_SECONDS
        price = self.config.RENT_PRICE_SUN

        params = {
            "market": "Open",
            "target": target_address,
            "amount": amount,
            "resource": ENERGY_RESOURCE,
            "duration": duration,
            "price": price,
            "partfill": self.config.RENT_PARTFILL,
            "bulk": False,
            "signed_ms": None,
            "signed_tx": None,
            "api_key": None,
        }

        # 模式一：API Key + 信用额度
        if self.config.TRONENERGY_API_KEY and self.config.TRONENERGY_PAYER_ADDRESS:
            params["address"] = self.config.TRONENERGY_PAYER_ADDRESS
            params["api_key"] = self.config.TRONENERGY_API_KEY
            return params

        # 模式二：用运营钱包签名一笔 TRX 转账支付订单
        if self.config.TRX_SOURCE_PRIVATE_KEY:
            priv = PrivateKey(bytes.fromhex(self.config.TRX_SOURCE_PRIVATE_KEY))
            payer_address = priv.public_key.to_base58check_address()
            payment_sun = self._calc_payment_sun(amount, duration, price)

            txn = await client.trx.transfer(
                payer_address,
                self.config.TRONENERGY_SERVER_ADDRESS,
                payment_sun,
            ).build()
            signed_tx = txn.sign(priv)

            params["address"] = payer_address
            params["signed_tx"] = json.dumps(signed_tx.to_json())
            return params

        raise ValueError(
            "租用能量需要配置 TRONENERGY_API_KEY + TRONENERGY_PAYER_ADDRESS，"
            "或配置 TRX_SOURCE_PRIVATE_KEY 用于签名付款。"
        )

    async def rent_energy(
        self,
        target_address: str,
        client: AsyncTron,
        http_client: httpx.AsyncClient,
        amount: int = None,
    ) -> bool:
        """
        向目标地址租用能量。

        Args:
            target_address: 接收能量的地址（子钱包，USDT 转账发起方）
            client: Tron 客户端（签名付款模式下用于构建 TRX 交易）
            http_client: HTTP 客户端
            amount: 租用能量点数；默认使用 RENT_ENERGY_AMOUNT

        Returns:
            bool: 是否成功下单
        """
        rent_amount = amount if amount is not None else self.config.RENT_ENERGY_AMOUNT
        if rent_amount <= 0:
            logger.info(f"地址 {target_address} 无需租用能量（amount={rent_amount}）")
            return True

        try:
            params = await self._build_order_params(
                target_address, client, rent_amount
            )
        except Exception as e:
            logger.error(f"构建租用订单参数失败: {e}")
            return False

        post_url = f"{self.config.TRONENERGY_API_SERVER}/order/new"
        logger.info(
            f"向 {target_address} 租用 {rent_amount} 能量"
            f"（时长 {self.config.RENT_DURATION_SECONDS}s，出价 {self.config.RENT_PRICE_SUN} sun/天）..."
        )

        try:
            response = await http_client.post(post_url, json=params, timeout=30.0)
        except Exception as e:
            logger.error(f"请求 tronenergy.market 失败: {e}")
            return False

        if response.status_code != 200:
            body = response.text
            logger.error(
                f"租用能量下单失败，HTTP {response.status_code}: {body}"
            )
            return False

        data = response.json()
        order = data.get("order")
        errors = data.get("errors")
        if not order or (errors and target_address in errors):
            logger.error(f"租用能量未成交: {data}")
            return False

        logger.info(f"✅ 租用订单已创建: order={order}")
        return True

    async def wait_for_energy(
        self,
        target_address: str,
        client: AsyncTron,
        required_energy: int = None,
    ) -> bool:
        """
        轮询等待目标地址的可用能量达到要求（租用的能量委托到账后才发 USDT）。

        Args:
            target_address: 目标地址
            client: Tron 客户端
            required_energy: 需要的可用能量点数，默认按配置租用量的 95%

        Returns:
            bool: 能量是否到账
        """
        if required_energy is None:
            required_energy = self.required_energy_for_sweep()

        timeout = self.config.RENT_WAIT_TIMEOUT
        poll_interval = 3
        waited = 0

        while waited < timeout:
            try:
                resource = await client.get_account_resource(target_address)
                energy_limit = resource.get("EnergyLimit", 0)
                energy_used = resource.get("EnergyUsed", 0)
                available = energy_limit - energy_used
                if available >= required_energy:
                    logger.info(
                        f"✅ 目标地址 {target_address} 可用能量 {available} 已满足需求"
                    )
                    return True
                logger.debug(
                    f"等待能量到账：{available}/{required_energy}（已等待 {waited}s）"
                )
            except Exception as e:
                logger.debug(f"查询能量资源失败（继续等待）: {e}")

            await asyncio.sleep(poll_interval)
            waited += poll_interval

        logger.error(
            f"等待能量到账超时（{timeout}s），目标地址 {target_address}"
        )
        return False
