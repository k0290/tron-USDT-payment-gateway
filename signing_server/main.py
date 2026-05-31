# signing_server/main.py (FINAL - SIMPLIFIED TO PERFECTION)

import logging
import os
from typing import List
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from bip_utils import Bip39SeedGenerator, Bip44, Bip44Coins, Bip44Changes
from tronpy.keys import PrivateKey
from dotenv import load_dotenv

# --- 配置和初始化 (保持不变) ---
load_dotenv()
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(name)s - %(message)s"
)
logger = logging.getLogger(__name__)
app = FastAPI(title="Secure Signing Service")
MASTER_MNEMONIC = os.getenv("MASTER_MNEMONIC_FOR_SIGNING")
if not MASTER_MNEMONIC:
    raise RuntimeError("关键环境变量 MASTER_MNEMONIC_FOR_SIGNING 未设置!")
try:
    SEED_BYTES = Bip39SeedGenerator(MASTER_MNEMONIC).Generate()
    BIP44_MST_ROOT = Bip44.FromSeed(SEED_BYTES, Bip44Coins.TRON)
    BIP44_ACCOUNT = BIP44_MST_ROOT.Purpose().Coin().Account(0)
    logger.info("BIP44钱包初始化成功。")
except Exception as e:
    logger.error(f"BIP44钱包初始化失败: {e}", exc_info=True)
    raise


# --- API 数据模型 ---
class UnsignedTxPayload(BaseModel):
    # 服务端只需要 txid 来签名
    txid: str = Field(..., description="客户端计算好的交易ID")
    address_index: int = Field(..., ge=0)


class SignedTxResponse(BaseModel):
    # 响应模型只包含签名
    signature: List[str] = Field(
        ..., description="由私钥生成的签名列表（通常只有一个）"
    )


@app.post("/sign-transaction", response_model=SignedTxResponse)
async def sign_transaction(payload: UnsignedTxPayload):
    logger.info(f"收到对索引 {payload.address_index} 的签名请求，txID: {payload.txid}")
    try:
        # 1. 派生私钥
        bip44_address = BIP44_ACCOUNT.Change(Bip44Changes.CHAIN_EXT).AddressIndex(
            payload.address_index
        )
        private_key = PrivateKey(bip44_address.PrivateKey().Raw().ToBytes())

        # 2. 直接对 txID 哈希进行签名
        txid_hash_bytes = bytes.fromhex(payload.txid)
        signature_bytes = private_key.sign_msg_hash(txid_hash_bytes)
        signature_hex = signature_bytes.hex()
        logger.info("已成功生成交易签名。")

        # 3. 只返回签名
        return {"signature": [signature_hex]}

    except Exception as e:
        logger.error(
            f"在为索引 {payload.address_index} 签名的过程中发生严重错误: {e}",
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail=f"Internal signing error: {e}")
