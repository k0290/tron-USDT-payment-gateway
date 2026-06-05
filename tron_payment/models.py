# tron_payment/models.py
"""
数据模型定义
"""

from datetime import datetime, timezone
from typing import Optional, Callable, Any
from pydantic import BaseModel, Field
import uuid


class Invoice(BaseModel):
    """
    发票/订单模型

    表示一笔待支付的订单
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="订单唯一ID")
    merchant_id: Optional[str] = Field(None, description="商户ID")
    merchant_order_id: Optional[str] = Field(None, description="商户订单ID")
    user_id: Optional[int] = Field(None, description="用户ID（如Telegram ID）")
    amount_due: float = Field(..., gt=0, description="应付金额 (USDT)")
    amount_paid: float = Field(default=0.0, ge=0, description="已收到金额 (USDT)")
    status: str = Field(default="pending", description="订单状态: pending/paid/expired")
    notify_url: Optional[str] = Field(None, description="支付成功回调地址")
    back_url: Optional[str] = Field(None, description="支付完成后跳转地址")
    pay_method: Optional[str] = Field(None, description="支付渠道编码")
    address: Optional[str] = Field(None, description="收款地址")
    payer_address: Optional[str] = Field(None, description="付款人地址")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: Optional[datetime] = Field(None, description="订单过期时间")
    paid_at: Optional[datetime] = Field(None, description="支付时间")
    txid: Optional[str] = Field(None, description="交易哈希")

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}


class Address(BaseModel):
    """
    地址模型

    表示一个派生的收款地址
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    address: str = Field(..., description="Tron 地址")
    index: int = Field(..., description="派生索引")
    invoice_id: Optional[str] = Field(None, description="关联的订单ID")
    usdt_balance: float = Field(default=0.0, description="USDT 余额")
    trx_balance: float = Field(default=0.0, description="TRX 余额")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}


class PaymentCallback(BaseModel):
    """
    支付回调数据模型
    """

    invoice_id: str = Field(..., description="订单ID")
    merchant_order_id: Optional[str] = Field(None)
    status: str = Field(..., description="订单状态")
    amount: float = Field(..., description="支付金额")
    payer_address: Optional[str] = Field(None, description="付款人地址")
    txid: str = Field(..., description="交易哈希")
    paid_at: datetime = Field(..., description="支付时间")

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}


class PaymentEvent(BaseModel):
    """
    支付事件模型

    用于通知应用支付状态变化
    """

    event_type: str = Field(
        ..., description="事件类型: payment_confirmed/payment_failed"
    )
    invoice: Invoice = Field(..., description="订单信息")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    extra_data: Optional[dict] = Field(None, description="额外数据")
