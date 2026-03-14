"""Модели SQLAlchemy для матричного маркетинга."""

from datetime import datetime
from sqlalchemy import (
    Column, Integer, BigInteger, String, Float, Boolean, DateTime,
    ForeignKey, UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(64), nullable=False, index=True)  # уникальность не требуется для tg (см. telegram_id)
    telegram_id = Column(BigInteger, unique=True, nullable=True, index=True)  # ID пользователя в Telegram для авторизации и диплинков
    password_hash = Column(String(255), nullable=True)
    referral_code = Column(String(32), unique=True, nullable=True, index=True)
    referrer_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    balance = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)

    referrer = relationship("User", remote_side=[id], backref="referrals")
    matrices_owned = relationship("UserMatrix", back_populates="owner", foreign_keys="UserMatrix.user_id")
    positions = relationship("MatrixPosition", back_populates="user", foreign_keys="MatrixPosition.user_id")
    transactions = relationship("Transaction", back_populates="user", foreign_keys="Transaction.user_id")
    holding_pool_entries = relationship("HoldingPool", back_populates="user", foreign_keys="HoldingPool.user_id")
    withdrawal_requests = relationship("WithdrawalRequest", back_populates="user", foreign_keys="WithdrawalRequest.user_id")
    support_requests = relationship("SupportRequest", back_populates="user", foreign_keys="SupportRequest.user_id")


class UserMatrix(Base):
    __tablename__ = "user_matrices"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    matrix_level = Column(Integer, nullable=False)  # 1, 2, 3, 4
    status = Column(String(16), default="active")   # 'active', 'closed'
    created_at = Column(DateTime, default=datetime.utcnow)
    closed_at = Column(DateTime, nullable=True)

    owner = relationship("User", back_populates="matrices_owned", foreign_keys=[user_id])
    positions = relationship("MatrixPosition", back_populates="matrix", foreign_keys="MatrixPosition.matrix_id")


class MatrixPosition(Base):
    __tablename__ = "matrix_positions"

    id = Column(Integer, primary_key=True, index=True)
    matrix_id = Column(Integer, ForeignKey("user_matrices.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    position = Column(Integer, nullable=False)  # 1-7
    parent_position_id = Column(Integer, ForeignKey("matrix_positions.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    matrix = relationship("UserMatrix", back_populates="positions", foreign_keys=[matrix_id])
    user = relationship("User", back_populates="positions", foreign_keys=[user_id])
    parent = relationship("MatrixPosition", remote_side=[id], foreign_keys=[parent_position_id])

    __table_args__ = (
        UniqueConstraint("matrix_id", "position", name="uq_matrix_position"),
    )


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    amount = Column(Float, nullable=False)  # + зачисление, - списание
    type = Column(String(32), nullable=False)  # 'purchase', 'matrix_bonus', 'reinvest', 'admin_fee'
    description = Column(String(256), nullable=True)
    matrix_id = Column(Integer, ForeignKey("user_matrices.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="transactions", foreign_keys=[user_id])


class HoldingPool(Base):
    __tablename__ = "holding_pool"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    matrix_level = Column(Integer, nullable=False)
    referrer_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="holding_pool_entries", foreign_keys=[user_id])


class WithdrawalRequest(Base):
    __tablename__ = "withdrawal_requests"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    amount = Column(Float, nullable=False)
    trc20_wallet = Column(String(128), nullable=False)
    status = Column(String(20), default="pending")  # pending, completed, rejected
    created_at = Column(DateTime, default=datetime.utcnow)
    processed_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="withdrawal_requests", foreign_keys=[user_id])


class SupportRequest(Base):
    __tablename__ = "support_requests"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    telegram_username = Column(String(64), nullable=False)
    message = Column(String(1024), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="support_requests", foreign_keys=[user_id])
