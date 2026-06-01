# Tron Payment SDK

**完整的 USDT-TRC20 支付解决方案**

一个功能完整、易于集成的 Tron 链 USDT 支付 SDK，提供从地址派生、支付监听、到资金归集的全套功能。

## ✨ 特性

- **HD 钱包** — 基于 BIP44 标准派生唯一收款地址
- **支付监听** — 监听链上 TRC20 转账，自动确认订单
- **资金归集** — 将收款地址 USDT 归集到冷钱包（需签名服务）
- **余额同步** — 定期从链上同步地址余额
- **事件回调** — 支付确认后可触发自定义逻辑
- **HTTP 示例** — `server.py` 提供下单 API 与支付页

---

## 📦 安装

```bash
pip install -r requirements.txt
```

**依赖：** Python ≥ 3.8、MongoDB、TronGrid API（建议申请 API Key）

---

## ⚙️ 配置

运行时配置从项目根目录 **`.env`** 加载（`PaymentConfig`）。**不要提交 `.env`**。

### 快速创建 `.env`

```bash
cp .env.example .env
```

按下方步骤填写占位项。字段说明见 **`.env.example`** 内注释。

### 使用 `key_management` 准备密钥

助记词与私钥请在 **离线、安全环境** 操作。支付服务器只保存 **xpub**；完整助记词仅用于离线脚本或 **`signing_server`**。

#### 步骤 A：生成新助记词（首次）

```bash
python key_management/generate_seed.py
```

抄写输出的 24 个单词并安全备份。脚本不会写入 `.env`。

#### 步骤 B：导出 `ACCOUNT_XPUB`

编辑 `key_management/derive_xpub.py` 中的 `MNEMONIC`，然后：

```bash
python key_management/derive_xpub.py
```

将输出的 `xpub6...` 写入 `.env` 的 `ACCOUNT_XPUB`（路径 `m/44'/195'/0'`）。用于派生收款地址 `m/44'/195'/0'/0/{index}`，**不能**花费资金。

#### 步骤 C：签名服务（仅归集）

```bash
cd signing_server
cp .env.example .env
# 编辑 .env：MASTER_MNEMONIC_FOR_SIGNING（与 ACCOUNT_XPUB 同一助记词）
pip install -r requirements.txt
uvicorn main:app --host 127.0.0.1 --port 9090
```

根目录 `.env` 中设置 `SIGNING_SERVICE_URL=http://127.0.0.1:9090`。

#### 步骤 D：`COLD_WALLET_ADDRESS`

归集目标地址。可来自 `derive_address.py`（编辑 `YOUR_MNEMONIC` 或 `YOUR_XPUB` 后运行），或任意你控制的 Tron 地址。

```bash
python key_management/derive_address.py
```

#### 步骤 E：网络（手动）

| 网络 | `TRONGRID_API_URL` | `USDT_CONTRACT_ADDRESS` |
|------|--------------------|-------------------------|
| Nile 测试网 | `https://nile.trongrid.io` | `TXYZopYRdj2D9XRtbG411XZZ3kM5VkAeBf` |
| 主网 | `https://api.trongrid.io` | `TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t` |

测试网与主网 **必须成对使用**，不要混配。

#### 步骤 F：归集 TRX 钱包（仅归集）

在 `.env` 中设置 `TRX_SOURCE_PRIVATE_KEY`（hex，无 `0x`）及可选的 `TRX_SOURCE_ADDRESS`，用于能量委托手续费。

#### 配置对照表

| 配置项 | 如何获得 | 必需 |
|--------|----------|------|
| `ACCOUNT_XPUB` | `derive_xpub.py` | 支付 ✅ |
| `TRONGRID_API_URL` | 上表 | ✅ |
| `USDT_CONTRACT_ADDRESS` | 上表 | ✅ |
| `TRONGRID_API_KEY` | [TronGrid](https://www.trongrid.io/) | 推荐 |
| `COLD_WALLET_ADDRESS` | `derive_address.py` 或自有 | 归集 |
| `SIGNING_SERVICE_URL` | 签名服务地址 | 归集 |
| `TRX_SOURCE_PRIVATE_KEY` | 运营 TRX 钱包 | 归集 |
| `SWEEP_MIN_AMOUNT_USDT` | `.env`，默认 `10.0` | 归集可选 |

#### 密钥关系

```
助记词 (离线保管)
    ├── ACCOUNT_XPUB          → 根目录 .env
    ├── MASTER_MNEMONIC...    → signing_server/.env
    └── COLD_WALLET_ADDRESS   → 根目录 .env（派生或独立地址）

收款地址 index=1,2,3...     ← ACCOUNT_XPUB 派生（每笔订单一个）
```

---

## 🚀 快速开始

1. 完成 `.env` 配置（`cp .env.example .env` + `key_management` 步骤）
2. 启动 MongoDB（默认 `mongodb://localhost:27017`）
3. 任选一种运行方式：

```bash
# 终端演示：创建订单、监听支付、可选归集
python examples/basic_usage.py

# HTTP 服务：API + 支付页 /pay/{order_id} + 后台监听
python server.py
```

**仅收款** 只需根目录 `.env` 中的必需项。**归集** 还需冷钱包、签名服务、TRX 源钱包，并单独运行 `signing_server`。

---

## 🔧 HTTP API（`server.py`）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/PH/pay/create` | 创建订单，返回 `payUrl`（支付页）、`address` |
| POST | `/api/PH/pay/order/Query` | 查询订单状态 |
| GET | `/pay/{order_id}` | 支付页（二维码、金额、地址） |
| GET | `/pay/{order_id}/status` | 支付状态 JSON（页面轮询） |
| GET | `/health` | 健康检查 |

集成测试客户端：`examples/server_test.py`（需先启动 `server.py`）。

---

## 🔐 安全建议

1. 勿将 `ACCOUNT_XPUB` 暴露给客户端；勿在支付服务器存放助记词
2. 助记词仅放在 `signing_server`，且服务应内网/防火墙隔离
3. 使用 TronGrid API Key，注意每日请求限额
4. 定期归集至冷钱包；监控异常大额转账
5. 勿将 `.env` 提交到版本库

---

## 🛠️ 目录结构

```
proj_usdt-main/
├── .env.example            # 配置模板（可提交）
├── .env                    # 本地配置（勿提交）
├── server.py               # FastAPI 支付 API + 支付页
├── signing_server/         # 独立签名服务
│   ├── .env.example
│   └── main.py
├── key_management/
│   ├── generate_seed.py
│   ├── derive_xpub.py
│   └── derive_address.py
├── tron_payment/           # SDK 核心
└── examples/
    ├── basic_usage.py
    └── server_test.py
```

### 运行命令汇总

```bash
pip install -r requirements.txt
cp .env.example .env          # 编辑后使用

python examples/basic_usage.py
python server.py

# 归集时额外：
cd signing_server && cp .env.example .env && uvicorn main:app --host 127.0.0.1 --port 9090
python examples/server_test.py
```

---

## 🔗 相关链接

- [Tron 官方文档](https://developers.tron.network/)
- [TronGrid API](https://www.trongrid.io/)
- [BIP44 标准](https://github.com/bitcoin/bips/blob/master/bip-0044.mediawiki)
