# key_management/derive_address.py
"""
从助记词或 XPUB 派生 Tron 地址

此脚本帮助您获取 Tron 地址，用作 COLD_WALLET_ADDRESS。

⚠️ 安全警告 ⚠️
如果使用助记词，请在安全的离线环境中运行此脚本。
切勿在连接到互联网的服务器上暴露您的助记词。
"""

import getpass

from bip_utils import Bip39SeedGenerator, Bip44, Bip44Coins, Bip44Changes

# 复用 derive_xpub.py 中的 xpub 派生函数
try:
    from derive_xpub import derive_tron_account_xpub
except ImportError:
    from key_management.derive_xpub import derive_tron_account_xpub


def derive_address_from_mnemonic(mnemonic: str, address_index: int = 0) -> str:
    """从助记词派生 Tron 地址 (BIP44 路径: m/44'/195'/0'/0/address_index)"""
    if not mnemonic:
        raise ValueError("助记词不能为空")
    
    # 从助记词生成种子
    seed = Bip39SeedGenerator(mnemonic).Generate()
    
    # 派生 Tron 账户 (m/44'/195'/0')
    bip44 = Bip44.FromSeed(seed, Bip44Coins.TRON)
    account = bip44.Purpose().Coin().Account(0)
    
    # 派生地址 (m/44'/195'/0'/0/address_index)
    # Bip44Changes.CHAIN_EXT = 0 (外部链，用于接收)
    address_ctx = account.Change(Bip44Changes.CHAIN_EXT).AddressIndex(address_index)
    address = address_ctx.PublicKey().ToAddress()
    
    return address


def derive_address_from_xpub(xpub: str, address_index: int = 0) -> str:
    """从 XPUB 派生 Tron 地址 (BIP44 路径: m/44'/195'/0'/0/address_index)"""
    if not xpub:
        raise ValueError("请提供有效的 XPUB")
    
    # 从 XPUB 加载账户
    account = Bip44.FromExtendedKey(xpub, Bip44Coins.TRON)
    
    # 派生地址 (m/44'/195'/0'/0/address_index)
    address_ctx = account.Change(Bip44Changes.CHAIN_EXT).AddressIndex(address_index)
    address = address_ctx.PublicKey().ToAddress()
    
    return address


def _prompt_address_index() -> int:
    """从终端读取地址索引（默认 0）。"""
    raw = input("地址索引 (默认 0): ").strip()
    if not raw:
        return 0
    try:
        index = int(raw)
        if index < 0:
            raise ValueError
        return index
    except ValueError:
        print("⚠️ 无效索引，使用默认值 0")
        return 0


if __name__ == "__main__":
    print("=" * 60)
    print("Tron 地址派生工具")
    print("=" * 60)
    print()
    print("请选择派生方式:")
    print("  1) 助记词 (Mnemonic)")
    print("  2) 扩展公钥 (XPUB)")
    choice = input("输入 1 或 2 (默认 1): ").strip() or "1"
    print()

    try:
        account_xpub = None
        if choice == "2":
            # 从终端读取 XPUB
            xpub = input("请输入 XPUB: ").strip()
            address_index = _prompt_address_index()
            address = derive_address_from_xpub(xpub, address_index=address_index)
            source_label = "XPUB"
        else:
            # 从终端读取助记词（不回显，避免泄露）
            print("⚠️ 请在安全的离线环境中输入助记词；输入内容不会显示在屏幕上。")
            mnemonic = getpass.getpass("请输入助记词 (12/24 个词): ").strip()
            address_index = _prompt_address_index()
            address = derive_address_from_mnemonic(mnemonic, address_index=address_index)
            # 同时派生账户 xpub（m/44'/195'/0'），用于配置 ACCOUNT_XPUB
            account_xpub = derive_tron_account_xpub(mnemonic, account_index=0)
            source_label = "助记词"

        print()
        print(f"✅ 从{source_label}派生:")
        print(f"   地址 (索引 {address_index}): {address}")
        print()
        print("📝 将此地址用作您的 COLD_WALLET_ADDRESS")
        print(f"   COLD_WALLET_ADDRESS = {address}")

        if account_xpub:
            print()
            print("🔑 账户 XPUB (m/44'/195'/0')：用于配置 ACCOUNT_XPUB")
            print(f"   ACCOUNT_XPUB = {account_xpub}")

        print()
        print("🔗 测试网浏览器:")
        print(f"   https://nile.tronscan.org/#/address/{address}")
    except Exception as e:
        print(f"❌ 派生地址时出错: {e}")
