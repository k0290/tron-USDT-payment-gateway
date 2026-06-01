"""
用于测试 examples/fastapi_integration.py 的完整测试脚本

功能：
- 创建订单（包含 notifyUrl 和 backUrl）
- 监听 notifyUrl 回调（使用本地回调服务器）
- 查询订单状态（验证 backUrl 返回）
- 测试支付检测和回调机制

使用方法:
  1. 启动 FastAPI 应用（在另一个终端）:
       cd /home/tron-payment-sdk
       python -m examples.fastapi_integration

  2. 确保 .env 文件包含:
       PAY_MCH_ID=your_merchant_id
       PAY_MCH_KEY=your_merchant_key

  3. 运行此测试脚本:
       cd /home/tron-payment-sdk
       python examples/test_fastapi_integration.py
"""

import os
import time
import hashlib
import threading
from decimal import Decimal
from typing import Optional, Dict, List
from http.server import HTTPServer, BaseHTTPRequestHandler
import json

import httpx


# ============ 配置 ============
BASE_URL = "http://127.0.0.1:8000"
CALLBACK_SERVER_PORT = 8888
CALLBACK_URL = f"http://127.0.0.1:{CALLBACK_SERVER_PORT}/callback"

MERCHANT_ID = os.getenv("PAY_MCH_ID", "1848")
MERCHANT_KEY = os.getenv("PAY_MCH_KEY", "vtxVKIXq95VC5ilPwd2W6jCIVfqFNoUc")

# 存储接收到的回调
received_callbacks: List[Dict] = []
callback_lock = threading.Lock()


# ============ 签名计算 ============
def build_sign_string(params: dict, merchant_key: str) -> str:
    """
    按照服务器端相同的方式构建签名字符串:
      1. 按参数名 ASCII 排序
      2. 跳过空值/None 和 'sign' 字段
      3. 用 '&' 连接为 k=v 格式
      4. 末尾追加 &key=<merchant_key>
    """
    items = [
        (k, str(v))
        for k, v in params.items()
        if k != "sign" and v is not None and str(v) != ""
    ]
    items.sort(key=lambda kv: kv[0])
    base = "&".join(f"{k}={v}" for k, v in items)
    return f"{base}&key={merchant_key}"


def calc_sign(params: dict, merchant_key: str) -> str:
    """计算 MD5(签名字符串) 并转为大写，与 fastapi_integration.py 中的逻辑一致。"""
    sign_str = build_sign_string(params, merchant_key)
    return hashlib.md5(sign_str.encode("utf-8")).hexdigest().upper()


# ============ 回调服务器（用于接收 notifyUrl 回调） ============
class CallbackHandler(BaseHTTPRequestHandler):
    """处理 notifyUrl 回调的 HTTP 服务器"""

    def do_POST(self):
        """处理 POST 请求（notifyUrl 回调）"""
        if self.path == "/callback":
            content_length = int(self.headers.get("Content-Length", 0))
            post_data = self.rfile.read(content_length)
            
            try:
                callback_data = json.loads(post_data.decode("utf-8"))
                print(f"\n[回调服务器] 收到 notifyUrl 回调:")
                print(f"  - 订单号: {callback_data.get('systemOrderNo')}")
                print(f"  - 商户订单号: {callback_data.get('mchOrderId')}")
                print(f"  - 金额: {callback_data.get('amount')}")
                print(f"  - 支付状态: {'已支付' if callback_data.get('isPaid') == 1 else '未支付'}")
                print(f"  - 签名: {callback_data.get('sign')[:16]}...")
                
                # 验证签名
                callback_data_for_sign = {
                    k: v for k, v in callback_data.items() if k != "sign"
                }
                server_sign = calc_sign(callback_data_for_sign, MERCHANT_KEY)
                client_sign = callback_data.get("sign", "")
                
                if server_sign == client_sign:
                    print(f"  ✅ 签名验证成功")
                    with callback_lock:
                        received_callbacks.append(callback_data)
                else:
                    print(f"  ❌ 签名验证失败: 服务器签名={server_sign}, 回调签名={client_sign}")
                
                # 返回 "success" (小写) 表示成功
                self.send_response(200)
                self.send_header("Content-type", "text/plain")
                self.end_headers()
                self.wfile.write(b"success")
                
            except Exception as e:
                print(f"\n[回调服务器] 处理回调时出错: {e}")
                self.send_response(500)
                self.send_header("Content-type", "text/plain")
                self.end_headers()
                self.wfile.write(f"error: {e}".encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        """禁用默认日志输出"""
        pass


def start_callback_server():
    """启动回调服务器"""
    server = HTTPServer(("127.0.0.1", CALLBACK_SERVER_PORT), CallbackHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    print(f"[回调服务器] 已启动，监听端口 {CALLBACK_SERVER_PORT}")
    print(f"[回调服务器] 回调地址: {CALLBACK_URL}")
    return server


# ============ 测试函数 ============
def test_health_check(client: httpx.Client):
    """测试健康检查"""
    print("\n" + "=" * 60)
    print("测试 1: 健康检查")
    print("=" * 60)
    
    try:
        resp = client.get("/health")
        print(f"[健康检查] 状态码: {resp.status_code}")
        print(f"[健康检查] 响应体: {resp.text}")
        
        if resp.status_code == 200:
            print("✅ 健康检查通过")
            return True
        else:
            print("❌ 健康检查失败")
            return False
    except Exception as e:
        print(f"❌ 健康检查请求失败: {e}")
        return False


def test_create_order(client: httpx.Client, notify_url: str, back_url: str):
    """测试创建订单"""
    print("\n" + "=" * 60)
    print("测试 2: 创建订单（包含 notifyUrl 和 backUrl）")
    print("=" * 60)
    
    mch_order_id = f"TEST_{int(time.time())}"
    amount_str = "10.00"
    
    create_params = {
        "amount": amount_str,
        "backUrl": back_url,
        "mchId": MERCHANT_ID,
        "mchOrderId": mch_order_id,
        "notifyUrl": notify_url,
        "payMethod": "USDT_TRC20",
    }
    sign_create = calc_sign(create_params, MERCHANT_KEY)
    
    create_payload = {
        **create_params,
        "sign": sign_create,
    }
    
    print(f"[创建订单] 商户订单号: {mch_order_id}")
    print(f"[创建订单] 金额: {amount_str} USDT")
    print(f"[创建订单] notifyUrl: {notify_url}")
    print(f"[创建订单] backUrl: {back_url}")
    print(f"[创建订单] 请求 JSON: {json.dumps(create_payload, indent=2, ensure_ascii=False)}")
    
    try:
        resp = client.post("/api/PH/pay/create", json=create_payload)
        print(f"[创建订单] 状态码: {resp.status_code}")
        print(f"[创建订单] 响应体: {resp.text}")
        
        if resp.status_code != 200:
            print("❌ 创建订单失败")
            return None, None, None
        
        create_json = resp.json()
        if create_json.get("code") != 200 or not create_json.get("data"):
            print("❌ 创建订单失败或无数据")
            return None, None, None
        
        system_order_id = create_json["data"]["systemOrderId"]
        pay_url = create_json["data"]["payUrl"]
        pay_address = create_json["data"].get("address", pay_url)

        print(f"\n✅ 订单创建成功")
        print(f"  - 系统订单号: {system_order_id}")
        print(f"  - 支付页面: {pay_url}")
        print(f"  - 收款地址: {pay_address}")
        print(f"  - 区块浏览器: https://nile.tronscan.org/#/address/{pay_address}")

        return mch_order_id, system_order_id, pay_url
        
    except Exception as e:
        print(f"❌ 创建订单请求失败: {e}")
        return None, None, None


def test_query_order(client: httpx.Client, mch_order_id: str):
    """测试查询订单"""
    print("\n" + "=" * 60)
    print("测试 3: 查询订单状态（验证 backUrl）")
    print("=" * 60)
    
    query_params = {
        "mchId": MERCHANT_ID,
        "mchOrderId": mch_order_id,
    }
    sign_query = calc_sign(query_params, MERCHANT_KEY)
    
    query_payload = {
        **query_params,
        "sign": sign_query,
    }
    
    print(f"[查询订单] 商户订单号: {mch_order_id}")
    print(f"[查询订单] 请求 JSON: {json.dumps(query_payload, indent=2, ensure_ascii=False)}")
    
    try:
        resp = client.post("/api/PH/pay/order/Query", json=query_payload)
        print(f"[查询订单] 状态码: {resp.status_code}")
        print(f"[查询订单] 响应体: {resp.text}")
        
        if resp.status_code != 200:
            print("❌ 查询订单失败")
            return None
        
        query_json = resp.json()
        if query_json.get("code") != 200 or not query_json.get("data"):
            print("❌ 查询订单失败或无数据")
            return None
        
        data = query_json["data"]
        is_paid = data.get("isPaid", 0)
        back_url = data.get("backUrl")
        
        print(f"\n✅ 订单查询成功")
        print(f"  - 支付状态: {'已支付' if is_paid == 1 else '未支付'}")
        print(f"  - 订单金额: {data.get('amount')} USDT")
        print(f"  - 实际支付: {data.get('payAmount')} USDT")
        print(f"  - 创建时间: {data.get('createdAt')}")
        print(f"  - 支付时间: {data.get('paidAt') or '未支付'}")
        print(f"  - backUrl: {back_url or '未设置'}")
        
        return query_json
        
    except Exception as e:
        print(f"❌ 查询订单请求失败: {e}")
        return None


def wait_for_callback(timeout: int = 120):
    """等待 notifyUrl 回调（最多等待 timeout 秒）"""
    print("\n" + "=" * 60)
    print(f"测试 4: 等待 notifyUrl 回调（最多 {timeout} 秒）")
    print("=" * 60)
    print(f"[提示] 要触发回调，请向支付地址转账对应的 USDT 金额")
    print(f"[提示] 支付系统每 10 秒检查一次，通常在 1 分钟内检测到支付")
    
    start_time = time.time()
    check_interval = 2  # 每 2 秒检查一次
    
    while time.time() - start_time < timeout:
        with callback_lock:
            if received_callbacks:
                callback = received_callbacks[-1]  # 获取最新的回调
                print(f"\n✅ 收到 notifyUrl 回调！")
                print(f"  - 商户订单号: {callback.get('mchOrderId')}")
                print(f"  - 系统订单号: {callback.get('systemOrderNo')}")
                print(f"  - 金额: {callback.get('amount')} USDT")
                print(f"  - 实际支付: {callback.get('payAmount')} USDT")
                print(f"  - 支付状态: {'已支付' if callback.get('isPaid') == 1 else '未支付'}")
                print(f"  - 支付渠道: {callback.get('payMethod')}")
                print(f"  - 签名: {callback.get('sign')}")
                return callback
        
        elapsed = int(time.time() - start_time)
        if elapsed % 10 == 0:  # 每 10 秒打印一次
            print(f"[等待回调] 已等待 {elapsed} 秒...")
        time.sleep(check_interval)
    
    print(f"\n⏰ 等待超时（{timeout} 秒），未收到回调")
    print(f"[提示] 如果已支付但未收到回调，请检查：")
    print(f"  1. 支付金额是否完全匹配")
    print(f"  2. 支付地址是否正确")
    print(f"  3. 区块链监听服务是否正常运行")
    return None


def main():
    """主测试函数"""
    print("\n" + "=" * 60)
    print("Tron Payment SDK - FastAPI 集成测试")
    print("=" * 60)
    
    # 检查配置
    if not MERCHANT_ID or not MERCHANT_KEY:
        print("❌ 错误: 环境变量中未设置 PAY_MCH_ID 或 PAY_MCH_KEY")
        print("请在 .env 文件中配置这些变量")
        return
    
    print(f"\n配置信息:")
    print(f"  - BASE_URL: {BASE_URL}")
    print(f"  - MERCHANT_ID: {MERCHANT_ID}")
    print(f"  - CALLBACK_URL: {CALLBACK_URL}")
    
    # 启动回调服务器
    callback_server = start_callback_server()
    time.sleep(1)  # 等待服务器启动
    
    # 设置回调 URL 和返回 URL
    notify_url = CALLBACK_URL
    back_url = "https://example.com/payment/success?orderId={order_id}"
    
    try:
        with httpx.Client(base_url=BASE_URL, timeout=30.0) as client:
            # 测试 1: 健康检查
            if not test_health_check(client):
                print("\n❌ 健康检查失败，请确保 FastAPI 服务正在运行")
                return
            
            # 测试 2: 创建订单
            mch_order_id, system_order_id, pay_url = test_create_order(
                client, notify_url, back_url
            )
            if not mch_order_id:
                print("\n❌ 创建订单失败，测试终止")
                return
            
            # 测试 3: 查询订单（立即查询，应该还是未支付状态）
            print("\n等待 2 秒后查询订单状态...")
            time.sleep(2)
            query_result = test_query_order(client, mch_order_id)
            
            if query_result and query_result["data"]["isPaid"] == 0:
                print("\n✅ 订单状态正确（未支付）")
                print("\n" + "=" * 60)
                print("下一步：")
                print("=" * 60)
                print(f"1. 向以下地址转账 10.00 USDT (TRC20):")
                print(f"   {pay_url}")
                print(f"\n2. 支付后，系统将在 10-60 秒内检测到支付")
                print(f"3. 检测到支付后，系统会发送 notifyUrl 回调")
                print(f"4. 回调服务器会自动验证签名并显示结果")
                print("=" * 60)
                
                # 测试 4: 等待回调（可选）
                user_input = input("\n是否等待支付回调？(y/n，默认 n): ").strip().lower()
                if user_input == "y":
                    callback = wait_for_callback(timeout=120)
                    
                    if callback:
                        # 再次查询订单，验证 backUrl
                        print("\n等待 2 秒后再次查询订单状态...")
                        time.sleep(2)
                        final_query = test_query_order(client, mch_order_id)
                        
                        if final_query and final_query["data"]["isPaid"] == 1:
                            back_url_result = final_query["data"].get("backUrl")
                            if back_url_result:
                                print(f"\n✅ backUrl 已返回: {back_url_result}")
                            else:
                                print(f"\n⚠️  backUrl 未返回（可能未设置）")
                else:
                    print("\n⏭️  跳过等待回调，测试完成")
            else:
                print("\n⚠️  订单状态异常，请检查")
    
    except KeyboardInterrupt:
        print("\n\n⚠️  测试被用户中断")
    except Exception as e:
        print(f"\n❌ 测试过程中发生错误: {e}", exc_info=True)
    finally:
        print("\n" + "=" * 60)
        print("测试完成")
        print("=" * 60)
        print(f"\n统计信息:")
        print(f"  - 收到的回调数量: {len(received_callbacks)}")
        if received_callbacks:
            print(f"  - 最新回调: {received_callbacks[-1].get('mchOrderId')}")


if __name__ == "__main__":
    main()
