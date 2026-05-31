# tron_payment/exceptions.py
"""
自定义异常类
"""


class PaymentSDKError(Exception):
    """SDK 基础异常"""

    pass


class ConfigError(PaymentSDKError):
    """配置错误"""

    pass


class WalletError(PaymentSDKError):
    """钱包相关错误"""

    pass


class BlockchainError(PaymentSDKError):
    """区块链相关错误"""

    pass


class SweepError(PaymentSDKError):
    """资金归集错误"""

    pass


class BalanceError(PaymentSDKError):
    """余额同步错误"""

    pass
