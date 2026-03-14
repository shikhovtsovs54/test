"""Pydantic-схемы для API."""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64, strip_whitespace=True)
    password: str = Field(..., min_length=1, max_length=128)
    referrer_id: Optional[int] = None
    referral_code: Optional[str] = None  # если указан, реферер определяется по коду
    levels: List[int] = Field(..., min_length=1)  # [1,2,3,4]


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=128)


class TelegramAuthRequest(BaseModel):
    """Данные от Telegram Web App для авторизации по initData."""
    init_data: str = Field(..., min_length=1)
    referrer_telegram_id: Optional[int] = None  # из диплинка ?start=ref_tg_id


class BotOnStartRequest(BaseModel):
    """Данные, которые бот передаёт при /start (update.message.from_user + start_param)."""
    telegram_id: int
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    referrer_telegram_id: Optional[int] = None  # из start_param диплинка
    bot_secret: Optional[str] = None  # секрет можно передать в теле (если заголовок обрезается)


class UserResponse(BaseModel):
    id: int
    username: str
    telegram_id: Optional[int] = None
    referrer_id: Optional[int]
    balance: float
    referral_code: Optional[str] = None
    created_at: datetime
    is_active: bool

    class Config:
        from_attributes = True


class SupportCreateRequest(BaseModel):
    telegram_username: str = Field(..., min_length=1, max_length=64)
    message: Optional[str] = Field(None, max_length=1024)


class WithdrawalCreateRequest(BaseModel):
    amount: float = Field(..., ge=10, description="Минимум 10$")
    trc20_wallet: str = Field(..., min_length=8, max_length=128)


class UserMatrixResponse(BaseModel):
    id: int
    user_id: int
    matrix_level: int
    status: str
    created_at: datetime
    closed_at: Optional[datetime]

    class Config:
        from_attributes = True


class MatrixPositionResponse(BaseModel):
    id: int
    matrix_id: int
    user_id: int
    position: int
    username: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class MatrixDetailResponse(BaseModel):
    matrix: UserMatrixResponse
    positions: List[MatrixPositionResponse]


class PurchaseRequest(BaseModel):
    levels: List[int] = Field(..., min_length=1)


class AddFundsRequest(BaseModel):
    amount: float = Field(..., gt=0, le=1_000_000)


class TreeResponse(BaseModel):
    id: int
    username: str
    referrals: List["TreeResponse"] = []


TreeResponse.model_rebuild()


class TransactionResponse(BaseModel):
    id: int
    user_id: int
    amount: float
    type: str
    description: Optional[str]
    matrix_id: Optional[int]
    created_at: datetime

    class Config:
        from_attributes = True


class StatsResponse(BaseModel):
    total_users: int
    total_transactions: int
    total_matrix_bonus_paid: float
    total_admin_fee: float
    holding_pool_count: int
