# tron_payment/tron_helpers.py
"""TronGrid / tronpy 客户端辅助工具。"""

import asyncio
import logging
from typing import Callable, Optional, TypeVar

import httpx
from tronpy import AsyncTron
from tronpy.providers.async_http import AsyncHTTPProvider

from .config import PaymentConfig

logger = logging.getLogger(__name__)

T = TypeVar("T")

MAX_RATE_LIMIT_RETRIES = 5


def build_async_tron_provider(
    config: PaymentConfig, http_client: httpx.AsyncClient
) -> AsyncHTTPProvider:
    """创建 TronGrid Provider，确保使用项目配置的 API Key。"""
    if not config.TRONGRID_API_KEY:
        logger.warning(
            "TRONGRID_API_KEY 未配置，tronpy 将使用共享默认 Key，容易触发 429 限流"
        )

    return AsyncHTTPProvider(
        endpoint_uri=config.TRONGRID_API_URL,
        client=http_client,
        api_key=config.TRONGRID_API_KEY,
    )


async def retry_on_rate_limit(
    operation: Callable[[], T],
    *,
    label: str = "TronGrid request",
) -> T:
    """对 429 Too Many Requests 进行指数退避重试。"""
    last_error: Optional[Exception] = None

    for attempt in range(MAX_RATE_LIMIT_RETRIES):
        try:
            return await operation()
        except httpx.HTTPStatusError as e:
            last_error = e
            if e.response.status_code != 429 or attempt >= MAX_RATE_LIMIT_RETRIES - 1:
                raise

            wait_seconds = min(30, 2**attempt)
            logger.warning(
                f"{label} 触发 429 限流，{wait_seconds}s 后重试 "
                f"({attempt + 1}/{MAX_RATE_LIMIT_RETRIES})"
            )
            await asyncio.sleep(wait_seconds)

    if last_error:
        raise last_error
    raise RuntimeError(f"{label} failed without exception")


async def get_usdt_contract(client: AsyncTron, contract_address: str):
    """获取 USDT 合约对象（带 429 重试）。"""
    return await retry_on_rate_limit(
        lambda: client.get_contract(contract_address),
        label=f"get_contract({contract_address})",
    )
