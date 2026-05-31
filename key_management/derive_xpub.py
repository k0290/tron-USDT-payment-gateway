# key_management/derive_xpub.py
from bip_utils import Bip39SeedGenerator, Bip44, Bip44Coins, Bip44Levels

# --- 安全警告 ---
# 此脚本处理私钥，请在安全的、离线的环境中运行。
# 绝不要在连接到互联网的服务器上运行此脚本或暴露你的助记词。

# 将下面替换为你自己生成的助记词
# MNEMONIC = "milk sock book smart hockey throw purse breeze sign news aim"
MNEMONIC = "chapter aisle join stem like figure dumb mail solve ketchup street open"

def derive_tron_account_xpub(mnemonic: str, account_index: int = 0) -> str:
    """从助记词派生 TRON 账户的 xpub (m/44'/195'/account')"""
    seed_bytes = Bip39SeedGenerator(mnemonic).Generate()
    
    # 创建 BIP44 master 密钥
    bip44_mst_ctx = Bip44.FromSeed(seed_bytes, Bip44Coins.TRON)
    
    # 派生到账户级别: m/44'/195'/account'
    bip44_acc_ctx = bip44_mst_ctx.Purpose().Coin().Account(account_index)
    
    # 返回账户的 xpub (扩展公钥)
    return bip44_acc_ctx.PublicKey().ToExtended()

if __name__ == "__main__":
    if MNEMONIC == "your twenty four words mnemonic phrase goes here replace this text":
        print("错误: 请先在脚本中替换为你自己的助记词。")
    else:
        # 派生第 0 个账户的 xpub
        account_0_xpub = derive_tron_account_xpub(MNEMONIC, account_index=0)
        print(f"TRON Account #0 xPub (m/44'/195'/0'):")
        print(account_0_xpub)
        