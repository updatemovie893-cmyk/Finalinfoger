from __future__ import annotations
import asyncio
from datetime import datetime
from typing import Optional, List

from sqlalchemy import (
    Column,
    String,
    Integer,
    Float,
    Boolean,
    DateTime,
    Text,
)
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = "sqlite+aiosqlite:///botdata.db"

engine = create_async_engine(DATABASE_URL, echo=False, future=True)
AsyncSessionLocal = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    telegram_id = Column(String, primary_key=True, index=True)
    balance = Column(Float, default=0.0)
    referrals = Column(Integer, default=0)
    referred_by = Column(String, nullable=True)
    joined_at = Column(DateTime, default=datetime.utcnow)
    daily_last_claim = Column(DateTime, nullable=True)
    lookups_count = Column(Integer, default=0)
    phone_number = Column(String, nullable=True)

class LookupHistory(Base):
    __tablename__ = "lookup_history"
    id = Column(String, primary_key=True, index=True)
    telegram_id = Column(String, index=True)
    query = Column(String)
    result_phone = Column(String, nullable=True)
    result_chat_id = Column(String, nullable=True)
    result_username = Column(String, nullable=True)
    result_country = Column(String, nullable=True)
    found = Column(String, default="no")
    created_at = Column(DateTime, default=datetime.utcnow)

class PhoneAlert(Base):
    __tablename__ = "phone_alerts"
    id = Column(String, primary_key=True, index=True)
    telegram_id = Column(String, index=True)
    phone_number = Column(String, index=True)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

# Initialization helper
async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

# User helpers
async def get_or_create_user(session: AsyncSession, telegram_id: str, welcome_points: float = 3.0) -> User:
    user = await session.get(User, telegram_id)
    if user:
        return user
    user = User(telegram_id=telegram_id, balance=welcome_points)
    session.add(user)
    await session.commit()
    # refresh to get defaults
    await session.refresh(user)
    return user

async def get_user(session: AsyncSession, telegram_id: str) -> Optional[User]:
    return await session.get(User, telegram_id)

async def add_points_db(session: AsyncSession, telegram_id: str, points: float) -> float:
    user = await get_or_create_user(session, telegram_id)
    user.balance = (user.balance or 0.0) + float(points)
    await session.commit()
    await session.refresh(user)
    return user.balance

async def deduct_points_db(session: AsyncSession, telegram_id: str, points: float) -> bool:
    user = await get_or_create_user(session, telegram_id)
    if (user.balance or 0.0) < float(points):
        return False
    user.balance = (user.balance or 0.0) - float(points)
    await session.commit()
    await session.refresh(user)
    return True

async def increment_lookup_count_db(session: AsyncSession, telegram_id: str) -> int:
    user = await get_or_create_user(session, telegram_id)
    user.lookups_count = (user.lookups_count or 0) + 1
    await session.commit()
    await session.refresh(user)
    return user.lookups_count

async def get_total_users_db(session: AsyncSession) -> int:
    result = await session.execute("SELECT COUNT(*) FROM users")
    return int(result.scalar() or 0)

async def get_total_lookups_db(session: AsyncSession) -> int:
    result = await session.execute("SELECT SUM(lookups_count) FROM users")
    return int(result.scalar() or 0)

async def record_history_db(session: AsyncSession, **kwargs) -> None:
    entry = LookupHistory(**kwargs)
    session.add(entry)
    await session.commit()

async def get_alerts_for_number(session: AsyncSession, cleaned_number: str) -> List[PhoneAlert]:
    q = await session.execute(
        "SELECT * FROM phone_alerts WHERE phone_number = :num AND active = 1",
        {"num": cleaned_number},
    )
    rows = q.fetchall()
    # Convert raw rows to PhoneAlert instances if needed
    alerts: List[PhoneAlert] = []
    for r in rows:
        # r is a Row object; map to PhoneAlert-like dict
        try:
            pa = PhoneAlert(
                id=r[0], telegram_id=r[1], phone_number=r[2], active=bool(r[3])
            )
            alerts.append(pa)
        except Exception:
            pass
    return alerts
