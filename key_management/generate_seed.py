# key_management/generate_seed.py
from bip_utils import Bip39MnemonicGenerator, Bip39WordsNum, Bip39SeedGenerator

# --- 安全警告 ---
# 请在安全的、离线的环境中运行此脚本。

# 1. 生成 24 个单词的助记词
mnemonic = Bip39MnemonicGenerator().FromWordsNumber(Bip39WordsNum.WORDS_NUM_24)
print(f"助记词 (Mnemonic): {mnemonic}")
print("\n--- 请立即在安全的地方备份这组助记词！---\n")

# 2. 从助记词生成种子
seed_bytes = Bip39SeedGenerator(mnemonic).Generate()
print(f"BIP39 种子 (Hex): {seed_bytes.hex()}")
