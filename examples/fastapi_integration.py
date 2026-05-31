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
import html
import json
import logging
import hashlib
import httpx
from decimal import Decimal, InvalidOperation
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from motor.motor_asyncio import AsyncIOMotorClient

from tron_payment import (
    PaymentConfig,
    WalletService,
    BlockchainMonitor,
    BalanceSyncService,
    PaymentEvent,
)

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 全局变量 / 服务实例
wallet_service = None
blockchain_monitor = None
balance_service = None
db = None
payment_config = None

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


def _format_datetime(value) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _network_label(trongrid_url: str) -> str:
    url = (trongrid_url or "").lower()
    if "nile" in url:
        return "Tron Nile (Testnet)"
    if "shasta" in url:
        return "Tron Shasta (Testnet)"
    return "Tron Mainnet"


def _explorer_address_url(trongrid_url: str, address: str) -> str:
    url = (trongrid_url or "").lower()
    if "nile" in url:
        return f"https://nile.tronscan.org/#/address/{address}"
    if "shasta" in url:
        return f"https://shasta.tronscan.org/#/address/{address}"
    return f"https://tronscan.org/#/address/{address}"


def _render_payment_page(invoice_doc: dict) -> str:
    status = invoice_doc.get("status", "pending")
    is_paid = status == "paid"
    address = invoice_doc.get("address") or ""
    amount = float(invoice_doc.get("amount_due", 0.0) or 0.0)
    order_id = invoice_doc.get("id") or ""
    merchant_id = invoice_doc.get("merchant_id") or "—"
    merchant_order_id = invoice_doc.get("merchant_order_id") or "—"
    pay_method = invoice_doc.get("pay_method") or "USDT-TRC20"
    created_at = _format_datetime(invoice_doc.get("created_at"))
    paid_at = _format_datetime(invoice_doc.get("paid_at"))
    back_url = invoice_doc.get("back_url") or ""
    txid = invoice_doc.get("txid") or ""

    trongrid_url = payment_config.TRONGRID_API_URL if payment_config else ""
    network = _network_label(trongrid_url)
    explorer_url = _explorer_address_url(trongrid_url, address) if address else "#"
    usdt_contract = payment_config.USDT_CONTRACT_ADDRESS if payment_config else ""

    status_label = "Paid" if is_paid else "Awaiting payment"
    status_class = "status-paid" if is_paid else "status-pending"
    amount_display = f"{amount:.2f}"

    paid_block = ""
    if is_paid:
        paid_block = f"""
        <div class="paid-banner">
          <strong>Payment received.</strong>
          {"You will be redirected shortly." if back_url else "Thank you."}
        </div>
        """

    tx_block = ""
    if txid:
        tx_block = f"""
        <div class="meta-row">
          <span class="meta-label">Transaction</span>
          <span class="meta-value mono">{html.escape(txid)}</span>
        </div>
        """

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Pay {html.escape(amount_display)} USDT</title>
  <script src="https://cdn.jsdelivr.net/npm/qrcode/build/qrcode.min.js"></script>
  <style>
    :root {{
      --bg: #0f1419;
      --card: #1a2332;
      --border: #2d3a4f;
      --text: #e7ecf3;
      --muted: #8b9cb3;
      --accent: #c026d3;
      --accent-dim: #86198f;
      --success: #22c55e;
      --pending: #f59e0b;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
      background: radial-gradient(ellipse at top, #1e293b 0%, var(--bg) 55%);
      color: var(--text);
      padding: 24px 16px;
    }}
    .wrap {{ max-width: 480px; margin: 0 auto; }}
    .card {{
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 24px;
      box-shadow: 0 20px 50px rgba(0,0,0,.35);
    }}
    h1 {{ margin: 0 0 4px; font-size: 1.35rem; font-weight: 600; }}
    .subtitle {{ color: var(--muted); font-size: .9rem; margin-bottom: 20px; }}
    .amount {{
      font-size: 2.25rem;
      font-weight: 700;
      letter-spacing: -0.02em;
      margin: 16px 0 4px;
    }}
    .amount span {{ font-size: 1rem; color: var(--muted); font-weight: 500; }}
    .status {{
      display: inline-block;
      padding: 4px 10px;
      border-radius: 999px;
      font-size: .75rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: .04em;
    }}
    .status-pending {{ background: rgba(245,158,11,.15); color: var(--pending); }}
    .status-paid {{ background: rgba(34,197,94,.15); color: var(--success); }}
    .qr-wrap {{
      display: flex;
      justify-content: center;
      margin: 24px 0;
      padding: 16px;
      background: #fff;
      border-radius: 12px;
    }}
    #qrcode canvas, #qrcode img {{ display: block; }}
    .address-box {{
      background: #0d1117;
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 12px 14px;
      margin: 12px 0;
    }}
    .address-label {{ font-size: .75rem; color: var(--muted); margin-bottom: 6px; }}
    .address-value {{
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: .82rem;
      word-break: break-all;
      line-height: 1.45;
    }}
    .actions {{ display: flex; gap: 10px; flex-wrap: wrap; margin-top: 12px; }}
    button, a.btn {{
      flex: 1;
      min-width: 120px;
      padding: 10px 14px;
      border-radius: 8px;
      font-size: .875rem;
      font-weight: 600;
      cursor: pointer;
      text-align: center;
      text-decoration: none;
      border: none;
    }}
    .btn-primary {{
      background: linear-gradient(135deg, var(--accent), var(--accent-dim));
      color: #fff;
    }}
    .btn-secondary {{
      background: transparent;
      color: var(--text);
      border: 1px solid var(--border);
    }}
    .meta {{ margin-top: 24px; border-top: 1px solid var(--border); padding-top: 16px; }}
    .meta-row {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      padding: 8px 0;
      font-size: .85rem;
      border-bottom: 1px solid rgba(45,58,79,.5);
    }}
    .meta-row:last-child {{ border-bottom: none; }}
    .meta-label {{ color: var(--muted); flex-shrink: 0; }}
    .meta-value {{ text-align: right; word-break: break-all; }}
    .mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: .8rem; }}
    .hint {{
      margin-top: 20px;
      padding: 12px;
      background: rgba(192,38,211,.08);
      border: 1px solid rgba(192,38,211,.25);
      border-radius: 10px;
      font-size: .82rem;
      color: var(--muted);
      line-height: 1.5;
    }}
    .paid-banner {{
      margin-bottom: 16px;
      padding: 12px;
      background: rgba(34,197,94,.12);
      border: 1px solid rgba(34,197,94,.35);
      border-radius: 10px;
      color: var(--success);
      font-size: .9rem;
    }}
    .toast {{
      position: fixed;
      bottom: 24px;
      left: 50%;
      transform: translateX(-50%);
      background: #334155;
      color: #fff;
      padding: 10px 18px;
      border-radius: 8px;
      font-size: .875rem;
      opacity: 0;
      transition: opacity .25s;
      pointer-events: none;
    }}
    .toast.show {{ opacity: 1; }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="card">
      {paid_block}
      <span class="status {status_class}">{status_label}</span>
      <h1>USDT Payment</h1>
      <p class="subtitle">{html.escape(network)} · {html.escape(pay_method)}</p>
      <div class="amount">{html.escape(amount_display)} <span>USDT</span></div>

      <div class="qr-wrap"><div id="qrcode"></div></div>

      <div class="address-box">
        <div class="address-label">Deposit address (TRC20)</div>
        <div class="address-value" id="pay-address">{html.escape(address)}</div>
      </div>

      <div class="actions">
        <button type="button" class="btn-primary" id="copy-btn">Copy address</button>
        <a class="btn btn-secondary" href="{html.escape(explorer_url)}" target="_blank" rel="noopener">View on Tronscan</a>
      </div>

      <div class="hint">
        Send <strong>exactly {html.escape(amount_display)} USDT</strong> on TRC20 to the address above.
        Wrong amounts may not be matched automatically. Include enough TRX for network fees.
      </div>

      <div class="meta">
        <div class="meta-row">
          <span class="meta-label">Order ID</span>
          <span class="meta-value mono">{html.escape(order_id)}</span>
        </div>
        <div class="meta-row">
          <span class="meta-label">Merchant order</span>
          <span class="meta-value">{html.escape(merchant_order_id)}</span>
        </div>
        <div class="meta-row">
          <span class="meta-label">Merchant ID</span>
          <span class="meta-value">{html.escape(merchant_id)}</span>
        </div>
        <div class="meta-row">
          <span class="meta-label">Created</span>
          <span class="meta-value">{html.escape(created_at)}</span>
        </div>
        {"<div class=\"meta-row\"><span class=\"meta-label\">Paid at</span><span class=\"meta-value\">" + html.escape(paid_at) + "</span></div>" if paid_at else ""}
        {tx_block}
        {"<div class=\"meta-row\"><span class=\"meta-label\">Token contract</span><span class=\"meta-value mono\">" + html.escape(usdt_contract) + "</span></div>" if usdt_contract else ""}
      </div>
    </div>
  </div>
  <div class="toast" id="toast">Address copied</div>
  <script>
    const payAddress = {json.dumps(address)};
    const orderId = {json.dumps(order_id)};
    const backUrl = {json.dumps(back_url)};
    const isPaid = {"true" if is_paid else "false"};

    QRCode.toCanvas(document.createElement("canvas"), payAddress, {{ width: 220, margin: 1 }}, function(err, canvas) {{
      if (!err) document.getElementById("qrcode").appendChild(canvas);
    }});

    document.getElementById("copy-btn").addEventListener("click", function() {{
      navigator.clipboard.writeText(payAddress).then(function() {{
        const t = document.getElementById("toast");
        t.classList.add("show");
        setTimeout(function() {{ t.classList.remove("show"); }}, 2000);
      }});
    }});

    if (backUrl && isPaid) {{
      setTimeout(function() {{ window.location.href = backUrl; }}, 3000);
    }} else if (!isPaid) {{
      setInterval(async function() {{
        try {{
          const resp = await fetch("/pay/" + orderId + "/status");
          if (!resp.ok) return;
          const data = await resp.json();
          if (data.isPaid) location.reload();
        }} catch (e) {{}}
      }}, 10000);
    }}
  </script>
</body>
</html>"""


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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    global wallet_service, blockchain_monitor, balance_service, db, payment_config

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

    # 启动后台任务
    monitor_task = asyncio.create_task(run_blockchain_monitor())
    balance_task = asyncio.create_task(run_balance_sync())

    logger.info("✅ 支付系统初始化完成")

    yield

    # 关闭时清理
    monitor_task.cancel()
    balance_task.cancel()
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
    payUrl: str
    systemOrderId: str
    address: str


class ThirdPartyCreateResponse(BaseModel):
    """
    第三方文档风格的响应：
    - code: 200 表示成功
    - data.payUrl: 支付页面链接（含订单信息与二维码）
    - data.systemOrderId: 系统订单号
    - data.address: Tron 收款地址
    - message: 失败时的原因
    """

    code: int
    data: Optional[ThirdPartyData] = None
    message: Optional[str] = None


@app.post("/api/PH/pay/create", response_model=ThirdPartyCreateResponse)
async def ph_pay_create(req: ThirdPartyCreateRequest, request: Request):
    """
    按第三方文档要求的下单接口：
    - 路径：/api/PH/pay/create
    - 方法：POST
    - 入参和签名算法与文档一致

    本接口内部会创建一笔区块链收款订单（USDT-TRC20），并返回支付页面链接作为 payUrl。
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

    # 5. 构造支付页面链接
    base_url = str(request.base_url).rstrip("/")
    pay_url = f"{base_url}/pay/{invoice.id}"

    data = ThirdPartyData(
        payUrl=pay_url,
        systemOrderId=invoice.id,
        address=address.address,
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
    payAmount: float     # 实际支付金额（目前等于 amount）
    costFee: float       # 手续费（目前填 0）
    createdAt: str       # 创建时间
    paidAt: str          # 支付时间（未支付时返回空字符串）
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

    # 实际支付金额：当前模型中仅支持全额支付，故等于 amount（未支付则为 0）
    pay_amount = amount if is_paid else 0.0

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

    data = ThirdPartyQueryData(
        isPaid=is_paid,
        isGotReceipt=is_got_receipt,
        amount=amount,
        payAmount=pay_amount,
        costFee=cost_fee,
        createdAt=created_at_str,
        paidAt=paid_at_str,
        backUrl=back_url,
    )

    return ThirdPartyQueryResponse(
        code=200,
        data=data,
        message="success",
    )


@app.get("/pay/{order_id}", response_class=HTMLResponse)
async def payment_page(order_id: str):
    """Hosted payment page with order metadata, QR code, and deposit address."""
    invoice_doc = await db.invoices.find_one({"id": order_id})
    if not invoice_doc:
        raise HTTPException(status_code=404, detail="Order not found")
    return HTMLResponse(content=_render_payment_page(invoice_doc))


@app.get("/pay/{order_id}/status")
async def payment_page_status(order_id: str):
    """JSON status for payment page polling."""
    invoice_doc = await db.invoices.find_one({"id": order_id})
    if not invoice_doc:
        raise HTTPException(status_code=404, detail="Order not found")
    status = invoice_doc.get("status", "pending")
    return {
        "orderId": order_id,
        "status": status,
        "isPaid": status == "paid",
        "amount": float(invoice_doc.get("amount_due", 0.0) or 0.0),
        "address": invoice_doc.get("address"),
        "txid": invoice_doc.get("txid"),
        "backUrl": invoice_doc.get("back_url"),
    }


@app.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
