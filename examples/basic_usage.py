# examples/basic_usage.py
"""
简单英文演示 - Tron 支付 SDK

演示核心功能：
- 创建发票/订单
- 监控支付
- 余额同步
- 资金归集
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import logging
from motor.motor_asyncio import AsyncIOMotorClient
import httpx

from tron_payment import (
    PaymentConfig,
    WalletService,
    BlockchainMonitor,
    BalanceSyncService,
    SweepService,
    PaymentEvent
)

# 设置日志级别
# 更改为 logging.INFO 查看更多详细信息，或 logging.DEBUG 查看详细输出
logging.basicConfig(
    level=logging.INFO,  # 从 WARNING 改为 INFO 以查看归集日志
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# 归集服务日志记录器 - 设置为 INFO 以查看归集活动
# 如果您想隐藏归集日志，设置为 logging.CRITICAL + 1
sweep_logger = logging.getLogger('tron_payment.sweep')
sweep_logger.setLevel(logging.INFO)  # 更改为 INFO 以查看归集日志

# 用于输出的自定义日志记录器
def print_step(step, message):
    print(f"\n[{step}] {message}")

def print_info(message):
    print(f"  → {message}")

def print_success(message):
    print(f"  ✓ {message}")

def print_error(message):
    print(f"  ✗ {message}")


async def on_payment_confirmed(event: PaymentEvent):
    """支付确认回调函数 - 简化输出"""
    print("\n" + "=" * 60)
    print("🎉 支付已确认！")
    print("=" * 60)
    print(f"订单 ID:      {event.invoice.id}")
    print(f"金额:         {event.invoice.amount_due} USDT")
    print(f"付款地址:     {event.invoice.payer_address}")
    print(f"交易哈希:     {event.invoice.txid}")
    print(f"状态:         {event.invoice.status}")
    print("=" * 60 + "\n")


async def run_blockchain_monitor(blockchain_monitor: BlockchainMonitor):
    """后台任务：监控区块链上的支付"""
    while True:
        try:
            await blockchain_monitor.check_payments()
            await asyncio.sleep(30)  # 每 30 秒检查一次
        except asyncio.CancelledError:
            break
        except Exception as e:
            print_error(f"监控错误: {e}")
            await asyncio.sleep(30)


async def run_balance_sync(balance_service: BalanceSyncService):
    """后台任务：同步地址余额"""
    # 初始同步
    try:
        await balance_service.sync_all_balances()
    except Exception as e:
        print_error(f"初始余额同步失败: {e}")

    while True:
        try:
            await asyncio.sleep(300)  # 每 5 分钟同步一次
            await balance_service.sync_all_balances()
        except asyncio.CancelledError:
            break
        except Exception as e:
            print_error(f"余额同步错误: {e}")


async def run_sweep_service(sweep_service: SweepService, config: PaymentConfig):
    """后台任务：将资金归集到冷钱包"""
    # 检查归集服务是否已配置 - 如果未配置则立即退出
    if not config.COLD_WALLET_ADDRESS or not config.SIGNING_SERVICE_URL:
        # 如果未配置则静默跳过（这是可选的）
        return
    
    # 使用服务自身的检查方法进行二次确认
    if not await sweep_service.check_signing_service():
        # 服务检查也失败，退出
        return
    
    await asyncio.sleep(10)  # 初始延迟

    while True:
        try:
            # sweep_funds 有自己的检查，但我们会捕获错误以防万一
            await sweep_service.sweep_funds(min_amount=10.0)
            # await asyncio.sleep(3600)  # 每小时归集一次
            await asyncio.sleep(60)  # 每分钟归集一次
        except asyncio.CancelledError:
            break
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.RequestError) as e:
            # 静默忽略连接错误 - 归集服务是可选的
            # 这些错误表示签名服务器不可用
            pass
        except Exception as e:
            # 记录其他错误（但不崩溃）
            error_msg = str(e)
            error_type = type(e).__name__
            
            # 抑制连接相关错误
            if "ConnectError" in error_type or "ConnectionError" in error_msg or "Failed to connect" in error_msg or "connection" in error_msg.lower():
                pass  # 静默忽略
            else:
                # 仅记录非连接错误
                print_error(f"归集错误: {e}")
            
            # await asyncio.sleep(3600)
            await asyncio.sleep(60)


async def main():
    """主函数"""
    
    print("=" * 60)
    print("Tron 支付 SDK - 简单演示（中文版）")
    print("运行中: examples/basic_usage_en.py")
    print("=" * 60)

    # 1. 初始化配置
    print_step("1/5", "正在初始化配置...")
    
    # PaymentConfig 自动从 .env 文件加载
    # 在项目根目录创建一个 .env 文件，包含以下变量：
    #
    # 必需设置：
    #   ACCOUNT_XPUB=xpub6CskmQCtpVZXQsgBvQVQqojBtejwSP3aht5SQEh2Qh6a5fYAyqEaKMcQSYvosUpVvffjXceNefMhP1ZUgrkb4txRwWje2DfN6JJJyaxJR36
    #   TRONGRID_API_URL=https://nile.trongrid.io
    #   USDT_CONTRACT_ADDRESS=TXYZopYRdj2D9XRtbG411XZZ3kM5VkAeBf
    #
    # 可选设置（用于资金归集）：
    #   COLD_WALLET_ADDRESS=TBC6VKsCWeHnYJ7X6nGetUFp9kTdVDdbFE
    #   SIGNING_SERVICE_URL=http://localhost:9090
    #   TRX_SOURCE_PRIVATE_KEY=your_hex_private_key_here
    #
    # 可选设置（用于 API 访问）：
    #   TRONGRID_API_KEY=your_api_key_here
    
    try:
        # 从 .env 文件加载配置
        # PaymentConfig 会自动从项目根目录的 .env 文件中读取
        config = PaymentConfig()
        print_success("配置已从 .env 文件加载")
        print_info(f"网络: {config.TRONGRID_API_URL}")
        print_info(f"USDT 合约: {config.USDT_CONTRACT_ADDRESS[:20]}...")
    except Exception as e:
        print_error(f"加载配置失败: {e}")
        print_info("请创建包含必需配置变量的 .env 文件")
        print_info("请查看上方注释了解必需的变量")
        return

    # 2. 连接数据库
    print_step("2/5", "正在连接数据库...")
    try:
        mongo_client = AsyncIOMotorClient("mongodb://localhost:27017")
        db = mongo_client.payment_demo
        # 测试连接
        await mongo_client.admin.command('ping')
        print_success("数据库已连接")
    except Exception as e:
        print_error(f"数据库连接失败: {e}")
        print_info("请确保 MongoDB 正在 mongodb://localhost:27017 上运行")
        return

    # 3. 初始化服务
    print_step("3/5", "正在初始化服务...")
    wallet_service = WalletService(config, db)
    blockchain_monitor = BlockchainMonitor(
        config,
        db,
        on_payment_confirmed=on_payment_confirmed
    )
    balance_service = BalanceSyncService(config, db)
    
    # 在初始化之前检查归集服务是否可用
    sweep_available = bool(config.COLD_WALLET_ADDRESS and config.SIGNING_SERVICE_URL)
    
    # 仅在配置后才初始化归集服务
    sweep_service = None
    if sweep_available:
        sweep_service = SweepService(config, db)
        print_success("所有服务已初始化（包括归集服务）")
    else:
        # 明确验证归集服务未配置
        if config.COLD_WALLET_ADDRESS:
            print_info(f"COLD_WALLET_ADDRESS 已设置: {config.COLD_WALLET_ADDRESS[:10]}...")
        else:
            print_info("COLD_WALLET_ADDRESS: 未配置")
            
        if config.SIGNING_SERVICE_URL:
            print_info(f"SIGNING_SERVICE_URL 已设置: {config.SIGNING_SERVICE_URL}")
        else:
            print_info("SIGNING_SERVICE_URL: 未配置")
        
        print_success("所有服务已初始化")
        print_info("归集服务未初始化（已跳过）")

    # 4. 创建发票
    print_step("4/5", "正在创建测试发票...")
    try:
        invoice, address = await wallet_service.create_invoice(
            amount=10.0,
            merchant_id="merchant_demo",
            merchant_order_id="ORDER_DEMO_001"
        )

        print("\n" + "=" * 60)
        print("✅ 发票已创建")
        print("=" * 60)
        print(f"订单 ID:     {invoice.id}")
        print(f"金额:        {invoice.amount_due} USDT")
        print(f"状态:        {invoice.status}")
        print(f"支付地址:    {address.address}")
        print(f"区块链浏览器: https://nile.tronscan.org/#/address/{address.address}")
        print("=" * 60)
        print(f"\n💡 请向上方地址发送恰好 {invoice.amount_due} USDT (TRC20)")
        print("   脚本将在收到支付时自动检测。\n")
    except Exception as e:
        print_error(f"创建发票失败: {e}")
        return

    # 5. 启动后台任务
    print_step("5/5", "正在启动后台任务...")
    print_info("监控支付（每 30 秒）")
    print_info("同步余额（每 5 分钟）")
    if sweep_available:
        print_info("归集资金（每小时）")
    else:
        print_info("归集资金（已禁用）")
    print("\n按 Ctrl+C 停止\n")

    # 创建后台任务
    tasks = [
        asyncio.create_task(run_blockchain_monitor(blockchain_monitor)),
        asyncio.create_task(run_balance_sync(balance_service)),
    ]
    
    # 仅在配置了归集服务且服务已初始化时添加归集任务
    if sweep_available and sweep_service is not None:
        tasks.append(asyncio.create_task(run_sweep_service(sweep_service, config)))

    try:
        # 等待所有任务
        await asyncio.gather(*tasks)
    except KeyboardInterrupt:
        print("\n\n" + "=" * 60)
        print("正在停止所有任务...")
        print("=" * 60)

        # 取消所有任务
        for task in tasks:
            task.cancel()

        # 等待任务取消
        await asyncio.gather(*tasks, return_exceptions=True)

        print_success("所有任务已停止")
        print("=" * 60 + "\n")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n已退出\n")
    except Exception as e:
        print_error(f"错误: {e}")
