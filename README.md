# Tron Payment SDK

🚀 **完整的 USDT-TRC20 支付解决方案**

一个功能完整、易于集成的 Tron 链 USDT 支付 SDK，提供从地址派生、支付监听、到资金归集的全套功能。

## ✨ 特性

- ✅ **HD 钱包** - 基于 BIP44 标准派生唯一收款地址
- ✅ **支付监听** - 实时监听区块链交易，自动确认订单
- ✅ **资金归集** - 自动将收款地址的 USDT 归集到冷钱包
- ✅ **余额同步** - 定期从链上同步地址余额
- ✅ **事件回调** - 支持自定义支付确认回调
- ✅ **易于集成** - 支持 FastAPI、Django 等主流框架
- ✅ **类型安全** - 使用 Pydantic 进行数据验证
- ✅ **异步优先** - 基于 asyncio，高性能

---

## 📦 安装

### 方式一：从源码安装

```bash
cd /www/tron-payment-sdk
pip install -e .
```

### 方式二：从 requirements.txt 安装

```bash
pip install -r requirements.txt
```

### 依赖项

- Python >= 3.8
- MongoDB（用于存储订单和地址数据）
- TronGrid API 访问（推荐获取 API Key）

---

## ⚙️ 配置

### 1. 创建配置文件

复制 `.env.example` 为 `.env` 并填写配置：

```bash
cp .env.example .env
```


### 2. 必需配置

| 配置项 | 说明 | 示例 |
|--------|------|------|
| `ACCOUNT_XPUB` | BIP44 扩展公钥 | xpub6CaP9vCGGP... |
| `TRONGRID_API_URL` | TronGrid API 地址 | https://nile.trongrid.io (测试网)<br/>https://api.trongrid.io (主网) |
| `USDT_CONTRACT_ADDRESS` | USDT TRC20 合约地址 | TXYZopYRdj2D9X... (测试网)<br/>TR7NHqjeKQxGTC... (主网) |

### 3. 可选配置

| 配置项 | 说明 | 用途 |
|--------|------|------|
| `TRONGRID_API_KEY` | TronGrid API 密钥 | 提高 API 限额 |
| `COLD_WALLET_ADDRESS` | 冷钱包地址 | 资金归集功能 |
| `SIGNING_SERVICE_URL` | 签名服务地址 | 资金归集功能 |

---

## 🚀 快速开始

### 基础使用

```python
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from tron_payment import PaymentConfig, WalletService, BlockchainMonitor, PaymentEvent

# 1. 配置
config = PaymentConfig(
    ACCOUNT_XPUB="your_xpub_here",
    TRONGRID_API_URL="https://nile.trongrid.io",
    USDT_CONTRACT_ADDRESS="TXYZopYRdj2D9XRtbG411XZZ3kM5VkAeBf"
)

# 2. 连接数据库
mongo_client = AsyncIOMotorClient("mongodb://localhost:27017")
db = mongo_client.payment_db

# 3. 初始化服务
wallet_service = WalletService(config, db)
blockchain_monitor = BlockchainMonitor(config, db)

# 4. 创建订单
async def create_order():
    invoice, address = await wallet_service.create_invoice(
        amount=10.0,
        merchant_id="merchant_123"
    )

    print(f"订单ID: {invoice.id}")
    print(f"支付地址: {address.address}")
    print(f"金额: {invoice.amount_due} USDT")

    return invoice

# 5. 监听支付
async def monitor_payments():
    while True:
        await blockchain_monitor.check_payments()
        await asyncio.sleep(30)  # 每30秒检查一次

# 运行
asyncio.run(create_order())
asyncio.run(monitor_payments())
```

---

## 📚 详细文档

### 1. WalletService - 钱包服务

**功能：** 派生地址、创建订单

#### 初始化

```python
from tron_payment import WalletService, PaymentConfig
from motor.motor_asyncio import AsyncIOMotorClient

config = PaymentConfig(...)
db = AsyncIOMotorClient("mongodb://localhost:27017").your_db
wallet_service = WalletService(config, db)
```

#### 创建订单

```python
invoice, address = await wallet_service.create_invoice(
    amount=100.0,              # 必需：订单金额（USDT）
    merchant_id="m123",        # 可选：商户ID
    merchant_order_id="O001",  # 可选：商户订单号
    user_id=123456,            # 可选：用户ID（如Telegram ID）
    notify_url="https://..."   # 可选：支付回调地址
)

print(f"订单ID: {invoice.id}")
print(f"支付地址: {address.address}")
```

#### 查询订单

```python
invoice = await wallet_service.get_invoice("order_id")
if invoice:
    print(f"状态: {invoice.status}")
    print(f"金额: {invoice.amount_due}")
```

---

### 2. BlockchainMonitor - 区块链监听

**功能：** 监听支付、确认订单

#### 初始化（带回调）

```python
from tron_payment import BlockchainMonitor, PaymentEvent

async def on_payment_confirmed(event: PaymentEvent):
    """支付确认回调"""
    invoice = event.invoice
    print(f"🎉 收到支付！")
    print(f"  订单: {invoice.id}")
    print(f"  金额: {invoice.amount_due} USDT")
    print(f"  交易: {invoice.txid}")

    # 自定义业务逻辑
    # - 发送通知
    # - 更新订单
    # - 触发 webhook

blockchain_monitor = BlockchainMonitor(
    config,
    db,
    on_payment_confirmed=on_payment_confirmed
)
```

#### 监听支付（后台任务）

```python
import asyncio

async def run_monitor():
    """作为后台任务运行"""
    while True:
        try:
            await blockchain_monitor.check_payments()
        except Exception as e:
            print(f"监听出错: {e}")
        await asyncio.sleep(30)  # 推荐30秒

# 启动
task = asyncio.create_task(run_monitor())
```

---

### 3. BalanceSyncService - 余额同步

**功能：** 从链上同步地址余额

#### 使用

```python
from tron_payment import BalanceSyncService

balance_service = BalanceSyncService(config, db)

# 同步所有地址余额
await balance_service.sync_all_balances()
```

#### 后台任务

```python
async def run_balance_sync():
    while True:
        await balance_service.sync_all_balances()
        await asyncio.sleep(300)  # 每5分钟
```

---

### 4. SweepService - 资金归集

**功能：** 将收款地址的 USDT 归集到冷钱包

⚠️ **重要：** 需要配合签名服务使用

#### 使用

```python
from tron_payment import SweepService

sweep_service = SweepService(config, db)

# 归集资金（最小金额1 USDT）
await sweep_service.sweep_funds(min_amount=1.0)
```

#### 后台任务

```python
async def run_sweep():
    while True:
        await sweep_service.sweep_funds(min_amount=10.0)
        await asyncio.sleep(3600)  # 每小时
```

---

## 🔧 框架集成

### FastAPI 集成

完整示例见 `examples/fastapi_integration.py`

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from tron_payment import PaymentConfig, WalletService, BlockchainMonitor

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时初始化
    global wallet_service, blockchain_monitor

    config = PaymentConfig(...)
    db = ...

    wallet_service = WalletService(config, db)
    blockchain_monitor = BlockchainMonitor(config, db)

    # 启动后台任务
    monitor_task = asyncio.create_task(run_monitor())

    yield

    # 关闭时清理
    monitor_task.cancel()

app = FastAPI(lifespan=lifespan)

@app.post("/orders/create")
async def create_order(amount: float):
    invoice, address = await wallet_service.create_invoice(amount=amount)
    return {"order_id": invoice.id, "address": address.address}
```

---

## 📊 数据模型

### Invoice（订单）

```python
{
    "id": "uuid",                    # 订单唯一ID
    "merchant_id": "m123",           # 商户ID
    "merchant_order_id": "O001",     # 商户订单号
    "user_id": 123456,               # 用户ID
    "amount_due": 100.0,             # 应付金额
    "status": "pending",             # 状态：pending/paid/expired
    "address": "TXxxx...",           # 收款地址
    "payer_address": "TYyyy...",     # 付款人地址
    "txid": "abc123...",             # 交易哈希
    "created_at": "2025-01-01T00:00:00",
    "paid_at": "2025-01-01T01:00:00",
    "notify_url": "https://..."      # 回调地址
}
```

### Address（地址）

```python
{
    "id": "uuid",
    "address": "TXxxx...",           # Tron 地址
    "index": 1,                      # 派生索引
    "invoice_id": "uuid",            # 关联订单ID
    "usdt_balance": 100.0,           # USDT 余额
    "trx_balance": 10.0,             # TRX 余额
    "created_at": "2025-01-01T00:00:00",
    "updated_at": "2025-01-01T01:00:00"
}
```

---

## 🔐 安全建议

1. **XPUB 保护** - 永远不要暴露 XPUB 到客户端
2. **API 密钥** - 使用 TronGrid API Key 避免限流
3. **签名服务** - 资金归集的签名服务应部署在安全的离线环境
4. **冷钱包** - 定期将资金归集到冷钱包
5. **监控告警** - 监控异常交易和大额转账

---

## 🛠️ 开发指南

### 目录结构

```
tron-payment-sdk/
|-- signing_server          # 签名服务
|-- key_management          # 生成xpub脚本
├── tron_payment/           # 主包
│   ├── __init__.py
│   ├── config.py          # 配置管理
│   ├── models.py          # 数据模型
│   ├── wallet.py          # 钱包服务
│   ├── blockchain.py      # 区块链监听
│   ├── sweep.py           # 资金归集
│   ├── balance.py         # 余额同步
│   └── exceptions.py      # 异常定义
├── examples/               # 示例代码
│   ├── basic_usage.py
│   └── fastapi_integration.py
├── requirements.txt        # 依赖
├── setup.py               # 安装配置
└── README.md              # 文档
```

### 运行测试

```bash
# 基础示例
python examples/basic_usage.py

# FastAPI 集成
python examples/fastapi_integration.py
```

---

## 📖 常见问题

### Q: 如何生成 XPUB？

A: 使用 BIP44 标准生成：

```bash
# 使用 bip-utils
python -c "from bip_utils import *; mnemonic = Bip39MnemonicGenerator().FromWordsNumber(12); seed = Bip39SeedGenerator(mnemonic).Generate(); bip44 = Bip44.FromSeed(seed, Bip44Coins.TRON); account = bip44.Purpose().Coin().Account(0); print(f'Mnemonic: {mnemonic}'); print(f'XPUB: {account.PublicKey().Raw().ToExtended()}')"
```

### Q: 支持哪些网络？

A: 支持 Tron 主网和 Nile 测试网，通过配置切换


## 🔗 相关链接

- [Tron 官方文档](https://developers.tron.network/)
- [TronGrid API](https://www.trongrid.io/)
- [BIP44 标准](https://github.com/bitcoin/bips/blob/master/bip-0044.mediawiki)
