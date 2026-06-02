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

#### 步骤 F：运营钱包 `TRX_SOURCE_PRIVATE_KEY`（仅归集）

在 `.env` 中设置 **运营钱包私钥**（hex，无 `0x` 前缀）。该钱包与收款 HD 钱包 **无关**，专门用于归集时的 **能量委托** 和 **激活新地址**。链上地址由私钥自动推导，**无需** 单独配置地址字段。

```env
TRX_SOURCE_PRIVATE_KEY=your_hex_private_key
```

运营钱包需具备：

- 足够 **TRX**（激活地址时每个新收款地址约 **0.1 TRX** + 少量带宽）
- 足够 **冻结用于 Energy 的 TRX**（见下文 **「Sweep 归集与 Energy 委托」**）

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

## ⚡ Sweep 归集与 Energy 委托（`TRX_SOURCE_PRIVATE_KEY`）

`SweepService`（`tron_payment/sweep.py`）把各 **收款地址** 上的 USDT 转到 `COLD_WALLET_ADDRESS`。收款地址通常 **只有 USDT、没有 TRX**，而 TRC20 转账需要 **Energy**（或燃烧 TRX）。若每次归集都给每个地址转 TRX 当手续费，成本高且难管理。

本 SDK 的做法：用 `.env` 中的 **`TRX_SOURCE_PRIVATE_KEY`** 加载一台 **运营钱包**，由它 **冻结 TRX 获得 Energy → 临时委托给收款地址 → 收款地址发 USDT → 撤销委托**，同一笔冻结 TRX 可反复用于多笔归集。

### 三个钱包各做什么

| 钱包 | 配置 | 归集中的角色 |
|------|------|----------------|
| 收款地址 | 由 `ACCOUNT_XPUB` 派生 | 持有 USDT；**交易发起方**（owner） |
| 运营钱包 | `TRX_SOURCE_PRIVATE_KEY` | 激活地址、冻结/委托/撤销 **Energy** |
| 冷钱包 | `COLD_WALLET_ADDRESS` | USDT **到账方** |
| 签名 | `signing_server` 助记词 | 对收款地址的 tx **签名**（与 xpub 同种子） |

运营钱包的 `T...` 地址 **由私钥在代码里自动推导**，不需要在 `.env` 里再写地址。

### Tron Energy 委托是什么

1. **冻结（Freeze / Stake）** — 运营钱包把 TRX 冻结为 **Energy** 资源（Stake 2.0：`freeze_balance`，`resource=ENERGY`）。
2. **委托（Delegate）** — 运营钱包把一部分 **可用冻结 Energy** **借给** 收款地址使用（`delegate_resource`，`lock=False` 表示之后可撤销）。
3. **使用** — 收款地址发起 USDT `transfer` 时，优先消耗 **委托到自己名下的 Energy**，而不是燃烧 TRX。
4. **撤销（Undelegate）** — 归集完成后，运营钱包 **收回** 委托，Energy 额度可给下一个收款地址再用。

委托本身 **不消耗** 被冻结的 TRX 本金，只消耗少量 **带宽** 发链上交易；真正被「用掉」的是 Energy 点数。

### 代码中的常量

| 常量 | 值 | 含义 |
|------|-----|------|
| `DELEGATED_ENERGY_SUN` | 80_000_000 | 每次向收款地址委托约 **80k Energy** |
| `USDT_TRANSFER_FEE_LIMIT_SUN` | 15_000_000 | USDT 交易 **fee_limit** 上限 15 TRX（Energy 不够时才可能烧 TRX） |
| `ADDRESS_ACTIVATION_AMOUNT_SUN` | 100_000 | 未激活地址先发 **0.1 TRX** 激活 |

单笔 USDT 转账常见消耗约 **65k Energy**（冷钱包已有 USDT 时）；首次收 USDT 可能约 **130k**。Energy 消耗与 **USDT 数量无关**。

### 单笔归集详细步骤（`sweep_funds`）

对每个 USDT 余额 ≥ `SWEEP_MIN_AMOUNT_USDT` 的收款地址：

```
┌─────────────────────┐
│ TRX_SOURCE 运营钱包  │  ← TRX_SOURCE_PRIVATE_KEY
└──────────┬──────────┘
           │
           │ ① 若收款地址未上链：转 0.1 TRX 激活 (_activate_address)
           │
           │ ② 若冻结 Energy 不足：freeze_balance 追加冻结 (_ensure_frozen_energy)
           │
           │ ③ delegate_resource → 收款地址 (~80k Energy) (_delegate_energy)
           ▼
┌─────────────────────┐
│ 收款地址 (index=N)   │  ← 仅有 USDT，现拥有委托来的 Energy
└──────────┬──────────┘
           │
           │ ④ 构建 USDT.transfer(收款地址 → 冷钱包)
           │ ⑤ signing_server 按 address_index 签名 txid
           │ ⑥ 广播交易
           │
           ▼
┌─────────────────────┐
│ COLD_WALLET_ADDRESS │
└─────────────────────┘
           │
           │ ⑦ undelegate_resource：运营钱包收回 Energy (_undelegate_energy)
           │ ⑧ 更新 MongoDB 地址余额
           ▼
        下一地址
```

所有需要 **运营钱包签名** 的步骤（激活、冻结、委托、撤销）都用 `TRX_SOURCE_PRIVATE_KEY` 本地签名并广播；只有 **USDT 转出** 那一步用 **signing_server** 里与收款 index 匹配的私钥签名。

### 运营钱包如何准备

1. 新建 **独立** Tron 钱包，导出 hex 私钥写入 `TRX_SOURCE_PRIVATE_KEY`（勿与 `signing_server` 助记词混用，除非刻意同一账户）。
2. 转入足够 **liquid TRX**：激活新地址（约 0.1 TRX/个）、委托/撤销/冻结的带宽。
3. 转入并 **冻结 TRX 换 Energy**（可在 TronLink 手动 Stake，或让 SDK 在 `_ensure_frozen_energy` 中自动冻结）。冻结量建议 **大于** 单次委托 × 并发归集数；代码在委托失败时会尝试 **多冻结 20% 缓冲** 后重试。
4. 监控 Tronscan：运营地址的 **Energy 余额**、**Frozen TRX**、liquid TRX 是否够用。

### 与「直接给收款地址打 TRX」对比

| 方式 | 优点 | 缺点 |
|------|------|------|
| **Energy 委托（本 SDK）** | 同一笔冻结 TRX 可反复用；单笔归集 TRX 消耗低 | 实现复杂；需维护运营钱包冻结额度 |
| **每次转 TRX 当 gas** | 简单 | 每个地址都要打 TRX；剩余 TRX 散落各地址 |

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
