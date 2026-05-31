# key_management/derive_address.py
"""
从助记词或 XPUB 派生 Tron 地址

此脚本帮助您获取 Tron 地址，用作 COLD_WALLET_ADDRESS。

⚠️ 安全警告 ⚠️
如果使用助记词，请在安全的离线环境中运行此脚本。
切勿在连接到互联网的服务器上暴露您的助记词。
"""

from bip_utils import Bip39SeedGenerator, Bip44, Bip44Coins, Bip44Changes

# ============================================
# 选项 1：从助记词派生地址
# ============================================
# 替换为您自己的助记词（12 或 24 个词）
YOUR_MNEMONIC = "chapter aisle join stem like figure dumb mail solve ketchup street open"

# ============================================
# 选项 2：从 XPUB 派生地址
# ============================================
# 如果您已有 XPUB，请改用此选项
YOUR_XPUB = ""


def derive_address_from_mnemonic(mnemonic: str, address_index: int = 0) -> str:
    """从助记词派生 Tron 地址 (BIP44 路径: m/44'/195'/0'/0/address_index)"""
    if not mnemonic or mnemonic == "your twelve or twenty four word mnemonic phrase goes here":
        raise ValueError("请将 YOUR_MNEMONIC 替换为您实际的助记词短语")
    
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


if __name__ == "__main__":
    print("=" * 60)
    print("Tron 地址派生工具")
    print("=" * 60)
    print()
    
    # 首先尝试从助记词派生
    if YOUR_MNEMONIC and YOUR_MNEMONIC != "your twelve or twenty four word mnemonic phrase goes here":
        try:
            address = derive_address_from_mnemonic(YOUR_MNEMONIC, address_index=0)
            print("✅ 从助记词派生:")
            print(f"   地址 (索引 0): {address}")
            print()
            print("📝 将此地址用作您的 COLD_WALLET_ADDRESS")
            print(f"   COLD_WALLET_ADDRESS={address}")
            print()
            print("🔗 测试网浏览器:")
            print(f"   https://nile.tronscan.org/#/address/{address}")
        except Exception as e:
            print(f"❌ 从助记词派生时出错: {e}")
    
    # 尝试从 XPUB 派生
    elif YOUR_XPUB:
        try:
            address = derive_address_from_xpub(YOUR_XPUB, address_index=0)
            print("✅ 从 XPUB 派生:")
            print(f"   地址 (索引 0): {address}")
            print()
            print("📝 将此地址用作您的 COLD_WALLET_ADDRESS")
            print(f"   COLD_WALLET_ADDRESS={address}")
            print()
            print("🔗 测试网浏览器:")
            print(f"   https://nile.tronscan.org/#/address/{address}")
        except Exception as e:
            print(f"❌ 从 XPUB 派生时出错: {e}")
    
    else:
        print("❌ 请在此脚本中设置 YOUR_MNEMONIC 或 YOUR_XPUB")
        print()
        print("选项 1: 使用您的助记词短语设置 YOUR_MNEMONIC")
        print("选项 2: 使用您的扩展公钥设置 YOUR_XPUB")
        print()
        print("然后运行: python key_management/derive_address.py")
