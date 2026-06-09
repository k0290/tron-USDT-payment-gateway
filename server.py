# examples/fastapi_integration.py
"""
FastAPI 集成示例

演示如何在 FastAPI 项目中集成 Tron Payment SDK
"""

import sys
import os
# 添加父目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import base64
import io
import json
import logging
import hashlib
import httpx
import qrcode
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI
from pydantic import BaseModel
from motor.motor_asyncio import AsyncIOMotorClient

from tron_payment import (
    PaymentConfig,
    WalletService,
    BlockchainMonitor,
    BalanceSyncService,
    SweepService,
    PaymentEvent,
)

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 全局变量 / 服务实例
wallet_service = None
blockchain_monitor = None
balance_service = None
sweep_service = None
db = None
payment_config = None

# Sweep interval (seconds) between sweep runs
SWEEP_INTERVAL_SECONDS = 3600

# 第三方支付对接配置（从全局 .env 读取）
MERCHANT_KEY = "vtxVKIXq95VC5ilPwd2W6jCIVfqFNoUc"


def _build_sign_string(params: dict, merchant_key: str) -> str:
    """
    按第三方文档的规则构建签名字符串：
    1. 按参数名 ASCII 排序
    2. 只参与非空参数，且不包含 sign 本身
    3. 用 & 连接为 query string
    4. 末尾追加 &key=商户密钥
    """
    items = [
        (k, str(v))
        for k, v in params.items()
        if k != "sign" and v is not None and str(v) != ""
    ]
    items.sort(key=lambda kv: kv[0])  # 按参数名 ASCII 排序
    base = "&".join(f"{k}={v}" for k, v in items)
    return f"{base}&key={merchant_key}"


def _calc_sign(params: dict, merchant_key: str) -> str:
    """计算 MD5 签名（大写十六进制），与示例一致。"""
    sign_str = _build_sign_string(params, merchant_key)
    md5 = hashlib.md5(sign_str.encode("utf-8")).hexdigest()
    return md5.upper()


def _parse_datetime(value) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        try:
            if value.endswith("Z"):
                value = value[:-1] + "+00:00"
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            return None
    else:
        return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _invoice_payment_deadline_ms(invoice_doc: dict) -> Optional[int]:
    """支付截止时间（毫秒时间戳）= created_at + EXPIRE_TIME_WINDOW。"""
    created_at = _parse_datetime(invoice_doc.get("created_at"))
    if created_at is None or payment_config is None:
        return None
    deadline = created_at + timedelta(seconds=payment_config.EXPIRE_TIME_WINDOW)
    return int(deadline.timestamp() * 1000)


def _invoice_expire_time_str(invoice_doc: dict) -> str:
    """支付截止时间 ISO 字符串。"""
    deadline_ms = _invoice_payment_deadline_ms(invoice_doc)
    if deadline_ms is None:
        return ""
    return datetime.fromtimestamp(
        deadline_ms / 1000, tz=timezone.utc
    ).isoformat()


def _address_qr_code_base64(address: str) -> str:
    """收款地址二维码 PNG，返回 data:image/png;base64,... 字符串。"""
    if not address:
        return ""
    img = qrcode.make(address, box_size=8, border=1)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    encoded = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


async def on_payment_confirmed(event: PaymentEvent):
    """
    支付确认回调
    
    当支付被确认时，向商户的 notifyUrl 发送 HTTP POST 回调
    """
    invoice = event.invoice
    logger.info(f"✅ 支付确认: 订单{invoice.id}, 金额{invoice.amount_due} USDT")
    
    # 如果订单没有设置 notify_url，跳过回调
    if not invoice.notify_url:
        logger.debug(f"订单 {invoice.id} 未设置 notify_url，跳过回调")
        return
    
    # 构建回调数据（按照第三方文档格式）
    # 注意：systemOrderNo 使用订单 ID
    callback_data = {
        "mchId": invoice.merchant_id or "",
        "mchOrderId": invoice.merchant_order_id or "",
        "systemOrderNo": invoice.id,  # 注意：文档中使用 systemOrderNo
        "amount": f"{invoice.amount_due:.2f}",  # 保留两位小数
        "payAmount": f"{invoice.amount_due:.2f}",
        "isPaid": 1 if invoice.status == "paid" else 0,
        "payMethod": invoice.pay_method or "",
    }
    
    # 计算签名（按照文档规则）
    callback_data["sign"] = _calc_sign(callback_data, MERCHANT_KEY)
    
    # 发送 HTTP POST 请求（带重试机制）
    max_retries = 3
    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    invoice.notify_url,
                    json=callback_data,
                    headers={"Content-Type": "application/json"}
                )
                
                # 检查响应（商户应返回 "success"）
                if resp.status_code == 200:
                    response_text = resp.text.strip().lower()
                    if response_text == "success":
                        logger.info(
                            f"✅ notifyUrl 回调成功: {invoice.notify_url}, "
                            f"订单={invoice.id}, 响应='success'"
                        )
                        return
                    else:
                        logger.warning(
                            f"notifyUrl 返回非 'success' 响应: {response_text}, "
                            f"订单={invoice.id}, 尝试 {attempt+1}/{max_retries}"
                        )
                else:
                    logger.warning(
                        f"notifyUrl 返回状态码 {resp.status_code}, "
                        f"订单={invoice.id}, 尝试 {attempt+1}/{max_retries}"
                    )
                    
        except httpx.TimeoutException:
            logger.error(
                f"notifyUrl 回调超时: {invoice.notify_url}, "
                f"订单={invoice.id}, 尝试 {attempt+1}/{max_retries}"
            )
        except Exception as e:
            logger.error(
                f"notifyUrl 回调失败: {invoice.notify_url}, "
                f"订单={invoice.id}, 错误={e}, 尝试 {attempt+1}/{max_retries}",
                exc_info=True
            )
        
        # 如果不是最后一次尝试，等待后重试（指数退避）
        if attempt < max_retries - 1:
            wait_time = 2 ** attempt  # 2, 4, 8 秒
            logger.info(f"等待 {wait_time} 秒后重试...")
            await asyncio.sleep(wait_time)
    
    # 所有重试都失败
    logger.error(
        f"❌ notifyUrl 回调最终失败: {invoice.notify_url}, "
        f"订单={invoice.id}, 已重试 {max_retries} 次"
    )


async def run_blockchain_monitor():
    """后台任务：监听区块链支付（每10秒检查一次，确保1分钟内检测到支付）"""
    
    while True:
        try:
            await blockchain_monitor.check_payments()
        except Exception as e:
            logger.error(f"区块链监听错误: {e}", exc_info=True)
        await asyncio.sleep(10)  # 从30秒改为10秒，加快检测速度


async def run_balance_sync():
    """后台任务：同步余额"""
    while True:
        try:
            await balance_service.sync_all_balances()
        except Exception as e:
            logger.error(f"余额同步错误: {e}", exc_info=True)
        await asyncio.sleep(300)  # 每5分钟


async def run_sweep_service():
    """后台任务：将收款地址 USDT 归集到冷钱包（需 signing_server + .env 配置）"""
    if sweep_service is None:
        return
    if not await sweep_service.check_signing_service():
        logger.warning("归集任务未启动：签名服务或冷钱包未配置")
        return

    await asyncio.sleep(10)

    while True:
        try:
            await sweep_service.sweep_funds(
                min_amount=payment_config.SWEEP_MIN_AMOUNT_USDT
            )
        except asyncio.CancelledError:
            break
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.RequestError) as e:
            logger.warning(f"归集服务连接失败（签名服务是否已启动？）: {e}")
        except Exception as e:
            logger.error(f"归集错误: {e}", exc_info=True)
        await asyncio.sleep(SWEEP_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    global wallet_service, blockchain_monitor, balance_service, sweep_service, db, payment_config

    # 启动时初始化
    logger.info("初始化支付系统...")

    # 配置 - PaymentConfig 会自动从 .env 文件加载
    # 请在项目根目录创建 .env 文件，包含以下变量：
    #
    # 必需配置：
    #   ACCOUNT_XPUB=your_extended_public_key_here
    #   TRONGRID_API_URL=https://nile.trongrid.io
    #   USDT_CONTRACT_ADDRESS=TXYZopYRdj2D9XRtbG411XZZ3kM5VkAeBf
    #
    # 可选配置：
    #   COLD_WALLET_ADDRESS=TYourColdWalletAddress
    #   SIGNING_SERVICE_URL=http://localhost:9090
    #   TRX_SOURCE_PRIVATE_KEY=your_hex_private_key_here
    #   TRONGRID_API_KEY=your_api_key_here
    #   SWEEP_MIN_AMOUNT_USDT=10.0
    
    try:
        config = PaymentConfig()
        payment_config = config
        logger.info("✅ 配置从 .env 文件加载成功")
    except Exception as e:
        logger.error(f"❌ 配置加载失败: {e}")
        logger.error("请创建 .env 文件并配置必需的变量")
        raise
    # 数据库
    mongo_client = AsyncIOMotorClient("mongodb://localhost:27017")
    db = mongo_client.payment_system
    # 初始化服务
    wallet_service = WalletService(config, db)
    blockchain_monitor = BlockchainMonitor(config, db, on_payment_confirmed)
    balance_service = BalanceSyncService(config, db)

    sweep_available = bool(
        config.COLD_WALLET_ADDRESS
        and config.SIGNING_SERVICE_URL
        and config.TRX_SOURCE_PRIVATE_KEY
    )
    if sweep_available:
        sweep_service = SweepService(config, db)
        logger.info(
            f"✅ 归集服务已启用 → {config.COLD_WALLET_ADDRESS}, "
            f"签名服务 {config.SIGNING_SERVICE_URL}"
        )
    else:
        sweep_service = None
        logger.info(
            "归集服务未启用（需 COLD_WALLET_ADDRESS, SIGNING_SERVICE_URL, TRX_SOURCE_PRIVATE_KEY）"
        )

    # 启动后台任务
    monitor_task = asyncio.create_task(run_blockchain_monitor())
    balance_task = asyncio.create_task(run_balance_sync())
    sweep_task = None
    if sweep_service is not None:
        sweep_task = asyncio.create_task(run_sweep_service())

    logger.info("✅ 支付系统初始化完成")

    yield

    # 关闭时清理
    monitor_task.cancel()
    balance_task.cancel()
    if sweep_task is not None:
        sweep_task.cancel()
    tasks = [monitor_task, balance_task]
    if sweep_task is not None:
        tasks.append(sweep_task)
    await asyncio.gather(*tasks, return_exceptions=True)
    logger.info("⏹ 支付系统已停止")


# 创建 FastAPI 应用
app = FastAPI(title="Tron Payment API", lifespan=lifespan)


# ============ 第三方对接风格的下单接口：/api/PH/pay/create ============

class ThirdPartyCreateRequest(BaseModel):
    """
    第三方文档风格的创建订单请求

    字段说明（与文档一一对应）：
    - mchId: 商户号
    - mchOrderId: 商户订单号（唯一）
    - amount: 金额字符串，保留两位小数，如 "100.00"
    - payMethod: 支付渠道编码
    - notifyUrl: 支付结果回调地址
    - backUrl: 支付完成后跳转地址（可选）
    - sign: 签名（可选，但如果提供则会进行校验）
    """

    mchId: str
    mchOrderId: str
    amount: str
    payMethod: str
    notifyUrl: str
    backUrl: Optional[str] = None
    sign: Optional[str] = None


class ThirdPartyData(BaseModel):
    qrCode: str
    systemOrderId: str
    address: str
    amount: float
    expireTime: str


class ThirdPartyCreateResponse(BaseModel):
    """
    第三方文档风格的响应：
    - code: 200 表示成功
    - data.qrCode: 收款地址二维码 (data:image/png;base64,...)
    - data.systemOrderId: 系统订单号
    - data.address: Tron 收款地址
    - data.amount: 订单金额 (USDT)
    - data.expireTime: 支付截止时间 (ISO 8601)
    - message: 失败时的原因
    """

    code: int
    data: Optional[ThirdPartyData] = None
    message: Optional[str] = None


@app.post("/api/PH/pay/create", response_model=ThirdPartyCreateResponse)
async def ph_pay_create(req: ThirdPartyCreateRequest):
    """
    按第三方文档要求的下单接口：
    - 路径：/api/PH/pay/create
    - 方法：POST
    - 入参和签名算法与文档一致

    本接口内部会创建一笔区块链收款订单（USDT-TRC20），并返回收款地址二维码 (base64 PNG)。
    """
    # 1. 基础校验：商户配置
    if not MERCHANT_KEY:
        logger.error("PAY_MCH_KEY 未在环境变量中配置")
        return ThirdPartyCreateResponse(
            code=500,
            message="Merchant key not set",
        )

    # 2. 解析金额（字符串 -> Decimal -> float），保留两位小数
    try:
        amount_decimal = Decimal(req.amount).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        logger.warning(f"金额格式错误: {req.amount}")
        return ThirdPartyCreateResponse(
            code=400,
            message="Invalid amount format",
        )

    amount_float = float(amount_decimal)

    # 3. 如果提供了签名，则进行校验
    if req.sign:
        params_for_sign = {
            "amount": req.amount,
            "backUrl": req.backUrl,
            "mchId": req.mchId,
            "mchOrderId": req.mchOrderId,
            "notifyUrl": req.notifyUrl,
            "payMethod": req.payMethod,
            # 不包含 sign 本身
        }
        server_sign = _calc_sign(params_for_sign, MERCHANT_KEY)
        client_sign = str(req.sign).upper()

        if server_sign != client_sign:
            logger.warning(
                f"签名校验失败: client_sign={client_sign}, server_sign={server_sign}"
            )
            return ThirdPartyCreateResponse(
                code=403,
                message="Invalid sign",
            )

    # 4. 创建区块链收款订单（使用 WalletService）
    try:
        invoice, address = await wallet_service.create_invoice(
            amount=amount_float,
            merchant_id=req.mchId,
            merchant_order_id=req.mchOrderId,
            notify_url=req.notifyUrl,
            back_url=req.backUrl,
            pay_method=req.payMethod,
        )
    except Exception as e:
        logger.error(f"创建区块链订单失败: {e}", exc_info=True)
        return ThirdPartyCreateResponse(
            code=500,
            message="Create order failed",
        )

    invoice_doc = invoice.model_dump()

    data = ThirdPartyData(
        qrCode=_address_qr_code_base64(address.address),
        systemOrderId=invoice.id,
        address=address.address,
        amount=amount_float,
        expireTime=_invoice_expire_time_str(invoice_doc),
    )

    return ThirdPartyCreateResponse(
        code=200,
        data=data,
        message="success",
    )


# ============ 第三方对接风格的订单查询接口：/api/PH/pay/order/Query ============


class ThirdPartyQueryRequest(BaseModel):
    """
    第三方文档风格的订单查询请求

    字段说明：
    - mchId: 商户号
    - mchOrderId: 商户订单号（唯一）
    - sign: 签名（必填）
    """

    mchId: str
    mchOrderId: str
    sign: str


class ThirdPartyQueryData(BaseModel):
    isPaid: int          # 0 = 未支付, 1 = 已支付
    isGotReceipt: int    # 0/1 收款状态（这里与 isPaid 保持一致或按需扩展）
    amount: float        # 订单金额
    amountPaid: float    # 已支付金额（含部分支付）
    amountRemaining: float  # 待支付金额
    costFee: float       # 手续费（目前填 0）
    createdAt: str       # 创建时间
    paidAt: str          # 支付时间（未支付时返回空字符串）
    address: str         # Tron 收款地址
    qrCode: str          # 收款地址二维码 (data:image/png;base64,...)
    backUrl: Optional[str] = None  # 支付完成后跳转地址（仅在已支付时返回）


class ThirdPartyQueryResponse(BaseModel):
    code: int
    data: Optional[ThirdPartyQueryData] = None
    message: Optional[str] = None


@app.post("/api/PH/pay/order/Query", response_model=ThirdPartyQueryResponse)
async def ph_pay_order_query(req: ThirdPartyQueryRequest):
    """
    按第三方文档要求的订单查询接口：
    - 路径：/api/PH/pay/order/Query
    - 方法：POST
    - 入参和签名算法与文档一致
    """
    # 1. 基础校验：商户配置
    if not MERCHANT_KEY:
        logger.error("PAY_MCH_KEY 未在环境变量中配置")
        return ThirdPartyQueryResponse(
            code=500,
            message="Merchant config not set",
        )

    # 2. 校验签名
    params_for_sign = {
        "mchId": req.mchId,
        "mchOrderId": req.mchOrderId,
    }
    server_sign = _calc_sign(params_for_sign, MERCHANT_KEY)
    client_sign = str(req.sign).upper()

    if server_sign != client_sign:
        logger.warning(
            f"查询签名校验失败: client_sign={client_sign}, server_sign={server_sign}"
        )
        return ThirdPartyQueryResponse(
            code=403,
            message="Invalid sign",
        )

    # 3. 查询订单（通过 merchant_order_id + merchant_id 进行匹配）
    try:
        invoice_doc = await db.invoices.find_one(
            {
                "merchant_order_id": req.mchOrderId,
                "merchant_id": req.mchId,
            }
        )
    except Exception as e:
        logger.error(f"查询订单时数据库错误: {e}", exc_info=True)
        return ThirdPartyQueryResponse(
            code=500,
            message="Database error",
        )

    if not invoice_doc:
        logger.info(f"未找到订单: mchOrderId={req.mchOrderId}, mchId={req.mchId}")
        return ThirdPartyQueryResponse(
            code=404,
            message="Order not found",
        )

    # 4. 组装返回数据
    status = invoice_doc.get("status", "pending")
    is_paid = 1 if status == "paid" else 0

    # 收款状态 isGotReceipt：目前与 isPaid 保持一致（如需区分到账/归集状态，可在此扩展逻辑）
    is_got_receipt = is_paid

    amount = float(invoice_doc.get("amount_due", 0.0) or 0.0)

    amount_paid = float(invoice_doc.get("amount_paid", 0.0) or 0.0)
    amount_remaining = max(0.0, amount - amount_paid)

    # 手续费：当前 SDK 不单独计费，这里返回 0
    cost_fee = 0.0

    created_at = invoice_doc.get("created_at")
    if hasattr(created_at, "isoformat"):
        created_at_str = created_at.isoformat()
    else:
        created_at_str = str(created_at) if created_at is not None else ""

    paid_at = invoice_doc.get("paid_at")
    if hasattr(paid_at, "isoformat"):
        paid_at_str = paid_at.isoformat()
    else:
        paid_at_str = ""  # 未支付时返回空字符串

    # 返回 backUrl（仅在已支付时返回）
    back_url = None
    if is_paid:
        back_url = invoice_doc.get("back_url")

    pay_address = invoice_doc.get("address") or ""

    data = ThirdPartyQueryData(
        isPaid=is_paid,
        isGotReceipt=is_got_receipt,
        amount=amount,
        amountPaid=amount_paid,
        amountRemaining=amount_remaining,
        costFee=cost_fee,
        createdAt=created_at_str,
        paidAt=paid_at_str,
        address=pay_address,
        qrCode=_address_qr_code_base64(pay_address),
        backUrl=back_url,
    )

    return ThirdPartyQueryResponse(
        code=200,
        data=data,
        message="success",
    )


@app.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
