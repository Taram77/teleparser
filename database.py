from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    Boolean,
    DateTime,
    ForeignKey,
    Text,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime, timezone
import config

Base = declarative_base()

class Channel(Base):
    __tablename__ = "channels"
    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(
        Integer, unique=True, nullable=False, index=True
    )  # ID канала в Telegram
    title = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    messages = relationship("TelegramMessage", back_populates="channel")


class TelegramMessage(Base):
    __tablename__ = "telegram_messages"
    id = Column(Integer, primary_key=True, index=True)
    channel_id = Column(
        Integer, ForeignKey("channels.telegram_id"), nullable=False
    )
    message_id = Column(
        Integer, nullable=False
    )  # ID сообщения внутри канала
    author_telegram_id = Column(
        Integer, nullable=True, index=True
    )  # ID автора сообщения
    author_username = Column(String, nullable=True)
    message_text = Column(Text, nullable=False)
    original_link = Column(String, nullable=True)
    is_processed = Column(Boolean, default=False)
    is_relevant = Column(Boolean, default=False)  # После фильтрации
    owner_status = Column(
        String, default="UNKNOWN"
    )  # UNKNOWN, OWNER, AGENT, NO_RESPONSE, DM_FAILED
    processed_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    last_dialog_attempt = Column(DateTime, nullable=True)

    channel = relationship("Channel", back_populates="messages")
    user = relationship("TelegramUser", back_populates="messages", uselist=False)


class TelegramUser(Base):
    __tablename__ = "telegram_users"
    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(Integer, unique=True, nullable=False, index=True)
    username = Column(String, nullable=True)
    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)
    is_owner_confirmed = Column(Boolean, default=False)
    dialog_state = Column(
        String, default="NONE"
    )  # NONE, QUESTION_SENT, WAITING_FOR_REPLY, REPLIED
    created_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )

    messages = relationship("TelegramMessage", back_populates="user")

class Setting(Base):
    __tablename__ = "settings"
    key = Column(String, primary_key=True, index=True)
    value = Column(Text, nullable=False)
    description = Column(String, nullable=True)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


engine = create_engine(config.DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def create_db_and_tables():
    Base.metadata.create_all(engine)
    print("Database tables created/checked.")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
