# Tron Payment SDK - 快速开始指南

## 📋 目录
1. [安装依赖](#1-安装依赖)
2. [准备工作](#2-准备工作)
3. [基础使用](#3-基础使用)
4. [集成到项目](#4-集成到项目)
5. [生产部署](#5-生产部署)

---

## 1. 安装依赖

### 安装 MongoDB

```bash
# Ubuntu/Debian
sudo apt update
sudo apt install mongodb

# 启动 MongoDB
sudo systemctl start mongodb
sudo systemctl enable mongodb
```

### 安装 SDK

```bash
cd /www/tron-payment-sdk
pip install -r requirements.txt
```

---

## 2. 准备工作

### 生成 XPUB（仅首次）

```python
from bip_utils import *

# 生成12个助记词
mnemonic = Bip39MnemonicGenerator().FromWordsNumber(12)
print(f"助记词（请妥善保管）: {mnemonic}")

# 生成种子
seed = Bip39SeedGenerator(mnemonic).Generate()

# 派生 Tron 账户
bip44 = Bip44.FromSeed(seed, Bip44Coins.TRON)
account = bip44.Purpose().Coin().Account(0)

# 获取 XPUB
xpub = account.PublicKey().Raw().ToExtended()
print(f"XPUB: {xpub}")
```

⚠️ **重要：**
- 助记词需要在安全的离线环境生成
- 助记词用于签名服务（归集功能）
- XPUB 用于在线服务（派生地址）

### 配置文件

创建 `.env` 文件：

```bash
# 测试网配置
ACCOUNT_XPUB=your_xpub_here
TRONGRID_API_URL=https://nile.trongrid.io
USDT_CONTRACT_ADDRESS=TXYZopYRdj2D9XRtbG411XZZ3kM5VkAeBf

# 可选：获取 API Key (https://www.trongrid.io/)
TRONGRID_API_KEY=
```

---

## 3. 基础使用

### 测试示例

```bash
# 运行基础示例
python examples/basic_usage.py
```

示例会：
1. 连接数据库
2. 创建一个测试订单
3. 输出支付地址
4. 开始监听支付

### 手动测试

在测试网获取免费 TRX 和 USDT：
- TRX 水龙头: https://nileex.io/join/getJoinPage
- USDT 合约: TXYZopYRdj2D9XRtbG411XZZ3kM5VkAeBf

---

## 4. 集成到项目

### 直接使用

```python
# your_project/payment.py
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from tron_payment import PaymentConfig, WalletService, BlockchainMonitor

# 初始化
config = PaymentConfig(...)
db = AsyncIOMotorClient("mongodb://localhost:27017").your_db

wallet_service = WalletService(config, db)
blockchain_monitor = BlockchainMonitor(config, db)

# 创建订单
async def create_payment_order(amount: float, user_id: str):
    invoice, address = await wallet_service.create_invoice(
        amount=amount,
        user_id=user_id
    )
    return {
        "order_id": invoice.id,
        "pay_address": address.address,
        "amount": invoice.amount_due
    }

# 查询订单
async def get_order_status(order_id: str):
    invoice = await wallet_service.get_invoice(order_id)
    return invoice.status if invoice else None
```

## 5. 生产部署

### 主网配置

修改 `.env`：

```bash
# 主网配置
TRONGRID_API_URL=https://api.trongrid.io
USDT_CONTRACT_ADDRESS=TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t

# 必需：生产环境强烈推荐使用 API Key
TRONGRID_API_KEY=your_api_key_here

# 归集配置
COLD_WALLET_ADDRESS=your_cold_wallet_address
SIGNING_SERVICE_URL=http://your_signing_service
```

### 后台任务

创建 `systemd` 服务：

```ini
# /etc/systemd/system/tron-payment.service
[Unit]
Description=Tron Payment Service
After=network.target mongodb.service

[Service]
Type=simple
User=your_user
WorkingDirectory=/www/your-project
ExecStart=/usr/bin/python3 /www/your-project/payment_api.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

启动服务：

```bash
sudo systemctl daemon-reload
sudo systemctl start tron-payment
sudo systemctl enable tron-payment
sudo systemctl status tron-payment
```

### 监控建议

1. **日志监控** - 使用 ELK/Loki 收集日志
2. **性能监控** - 使用 Prometheus + Grafana
3. **告警配置** - 监控支付延迟、异常订单
4. **数据备份** - 定期备份 MongoDB

---

## 🎯 核心参数说明

### WalletService.create_invoice()

| 参数 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `amount` | float | ✅ | 订单金额 (USDT) |
| `merchant_id` | str | ❌ | 商户ID，用于多商户场景 |
| `merchant_order_id` | str | ❌ | 商户订单号，建议传入 |
| `user_id` | int | ❌ | 用户ID，如 Telegram ID |
| `notify_url` | str | ❌ | 支付成功回调地址 |

### BlockchainMonitor.check_payments()

- **调用频率：** 推荐 30 秒
- **资源消耗：** 取决于待支付订单数量
- **回调触发：** 支付确认后自动触发 `on_payment_confirmed`

### BalanceSyncService.sync_all_balances()

- **调用频率：** 推荐 5 分钟
- **资源消耗：** 取决于地址总数
- **用途：** 实时显示余额、触发归集

### SweepService.sweep_funds()

- **调用频率：** 推荐 1 小时
- **最小金额：** 建议 >= 10 USDT（避免频繁归集）
- **注意：** 需要配合签名服务使用

---

## ❓ 常见问题排查

### 问题1：支付未被检测到

**排查步骤：**
1. 检查 `blockchain_monitor.check_payments()` 是否在运行
2. 确认交易已上链（在区块浏览器查询）
3. 确认金额精确匹配（不能多也不能少）
4. 检查 TronGrid API 是否正常响应

### 问题2：地址派生失败

**排查步骤：**
1. 检查 `ACCOUNT_XPUB` 配置是否正确
2. 确认 MongoDB 连接正常
3. 查看日志中的详细错误信息

### 问题3：余额不更新

**排查步骤：**
1. 检查 `balance_service.sync_all_balances()` 是否在运行
2. 确认 TronGrid API Key 有效
3. 检查网络连接

---

## 📞 获取帮助

1. 查看完整文档：`README.md`
2. 查看示例代码：`examples/basic_usage.py`


---
