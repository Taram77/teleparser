import asyncio
from telethon import TelegramClient, events, functions
from telethon.tl.types import ChannelParticipantsBots, ChannelParticipantsAdmins
from telethon.errors import UserIsBlockedError, PeerFloodError, FloodWaitError, UserPrivacyRestrictedError, ChatWriteForbiddenError
import time
import random
import httpx
from datetime import datetime, timedelta, timezone

import config
from database import SessionLocal, Channel, TelegramMessage, TelegramUser
# from aggregator_service.rate_limiter import RateLimiter # Для реального продакшна
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("aggregator.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Для простоты демонстрации, rate limiter будет in-memory. В продакшне лучше Redis.
class InMemoryRateLimiter:
    def __init__(self, limit_per_interval, interval_seconds):
        self.limit_per_interval = limit_per_interval
        self.interval_seconds = interval_seconds
        self.timestamps = []
        self.daily_count = 0
        self.last_reset_day = datetime.now(timezone.utc).day

    async def wait_if_needed(self):
        now = datetime.now(timezone.utc)
        if now.day != self.last_reset_day:
            self.daily_count = 0
            self.last_reset_day = now.day
            logger.info("Daily DM count reset.")

        if self.daily_count >= config.DAILY_DM_LIMIT_PER_ACCOUNT:
            logger.warning(f"Daily DM limit ({config.DAILY_DM_LIMIT_PER_ACCOUNT}) reached. Waiting until next day.")
            # Для простоты, ждем до полуночи следующего дня. В реале - другой механизм.
            tomorrow = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
            await asyncio.sleep((tomorrow - now).total_seconds())
            self.daily_count = 0 # Reset for next day immediately
            self.last_reset_day = tomorrow.day

        self.timestamps = [t for t in self.timestamps if now - t < timedelta(seconds=self.interval_seconds)]
        if len(self.timestamps) >= self.limit_per_interval:
            wait_time = self.interval_seconds - (now - self.timestamps[0]).total_seconds()
            if wait_time > 0:
                logger.info(f"Rate limit hit. Waiting for {wait_time:.2f} seconds.")
                await asyncio.sleep(wait_time)
            self.timestamps = [t for t in self.timestamps if datetime.now(timezone.utc) - t < timedelta(seconds=self.interval_seconds)] # Re-evaluate after wait

    def record_send(self):
        self.timestamps.append(datetime.now(timezone.utc))
        self.daily_count += 1
        logger.info(f"DM sent. Total today: {self.daily_count}. Current window: {len(self.timestamps)}.")

dm_rate_limiter = InMemoryRateLimiter(limit_per_interval=1, interval_seconds=random.randint(config.DM_SEND_INTERVAL_MIN, config.DM_SEND_INTERVAL_MAX))

client = TelegramClient(
    session=f"sessions/{config.PHONE_NUMBER}",  # Session file location
    api_id=config.API_ID,
    api_hash=config.API_HASH,
)

async def notify_admin_bot(message_data: dict):
    """Отправляет уведомление админ-боту по внутреннему API."""
    try:
        async with httpx.AsyncClient() as http_client:
            response = await http_client.post(
                f"{config.ADMIN_BOT_API_URL}/notify_owner", json=message_data
            )
            response.raise_for_status()
            logger.info(f"Notification sent to admin bot: {message_data.get('username')}")
    except httpx.HTTPStatusError as e:
        logger.error(f"Failed to notify admin bot (HTTP error): {e.response.status_code} - {e.response.text}")
    except httpx.RequestError as e:
        logger.error(f"Failed to notify admin bot (Request error): {e}")


async def is_relevant_message(message_text: str) -> bool:
    """Проверяет, является ли сообщение потенциальным объявлением о продаже."""
    text_lower = message_text.lower()
    for keyword in config.CHANNEL_FILTER_KEYWORDS:
        if keyword in text_lower:
            return True
    return False

@client.on(events.NewMessage)
async def handle_new_message(event):
    if not event.is_channel:
        return # Нас интересуют только сообщения в каналах

    channel_id = event.chat_id
    message_id = event.id
    message_text = event.message.message

    db = SessionLocal()
    try:
        # Проверяем, активен ли мониторинг для этого канала
        channel_in_db = db.query(Channel).filter_by(telegram_id=channel_id, is_active=True).first()
        if not channel_in_db:
            return

        # Проверяем, не обрабатывали ли уже это сообщение
        existing_message = db.query(TelegramMessage).filter_by(
            channel_id=channel_id, message_id=message_id
        ).first()
        if existing_message:
            logger.debug(f"Message {message_id} in channel {channel_id} already processed.")
            return

        # Проверяем релевантность сообщения
        if not await is_relevant_message(message_text):
            logger.debug(f"Message {message_id} in channel {channel_id} not relevant.")
            # Записываем как обработанное, но нерелевантное, чтобы не перепроверять
            new_msg = TelegramMessage(
                channel_id=channel_id,
                message_id=message_id,
                message_text=message_text,
                is_processed=True,
                is_relevant=False,
                owner_status="NOT_RELEVANT",
                author_telegram_id=event.message.from_id.user_id if event.message.from_id else None,
                author_username=event.message.from_id.username if event.message.from_id and hasattr(event.message.from_id, 'username') else None,
                original_link=event.message.url,
            )
            db.add(new_msg)
            db.commit()
            return

        # Получаем информацию об авторе
        author_id = None
        author_username = None
        if event.message.from_id:
            if hasattr(event.message.from_id, 'user_id'): # Для User
                 author_id = event.message.from_id.user_id
            elif hasattr(event.message.from_id, 'channel_id'): # Для Channel (редко, но бывает)
                 author_id = event.message.from_id.channel_id
            
            if hasattr(event.message.from_id, 'username'):
                author_username = event.message.from_id.username

        if not author_id:
            logger.warning(f"Could not get author ID for message {message_id} in channel {channel_id}. Skipping DM.")
            new_msg = TelegramMessage(
                channel_id=channel_id,
                message_id=message_id,
                message_text=message_text,
                is_processed=True,
                is_relevant=True, # Отфильтровано как релевантное
                owner_status="NO_AUTHOR_ID",
                original_link=event.message.url,
            )
            db.add(new_msg)
            db.commit()
            return
        
        # Проверяем, не опрашивали ли уже этого пользователя
        existing_user = db.query(TelegramUser).filter_by(telegram_id=author_id).first()
        if existing_user and existing_user.is_owner_confirmed:
            logger.info(f"User {author_id} already confirmed as owner. Skipping DM for message {message_id}.")
            new_msg = TelegramMessage(
                channel_id=channel_id,
                message_id=message_id,
                message_text=message_text,
                is_processed=True,
                is_relevant=True,
                owner_status="ALREADY_OWNER",
                author_telegram_id=author_id,
                author_username=author_username,
                original_link=event.message.url,
                user=existing_user
            )
            db.add(new_msg)
            db.commit()
            return
        
        # Сохраняем сообщение и информацию о пользователе в БД перед отправкой DM
        new_msg = TelegramMessage(
            channel_id=channel_id,
            message_id=message_id,
            message_text=message_text,
            is_processed=False, # Пока не обработано, ждет ответа
            is_relevant=True,
            owner_status="UNKNOWN",
            author_telegram_id=author_id,
            author_username=author_username,
            original_link=event.message.url,
            last_dialog_attempt=datetime.now(timezone.utc)
        )
        db.add(new_msg)
        
        if not existing_user:
            existing_user = TelegramUser(
                telegram_id=author_id,
                username=author_username,
                first_name=event.message.sender.first_name if event.message.sender else None,
                last_name=event.message.sender.last_name if event.message.sender else None,
                dialog_state="QUESTION_SENT" # Помечаем, что вопрос будет отправлен
            )
            db.add(existing_user)
        else:
            existing_user.dialog_state = "QUESTION_SENT"
            existing_user.username = author_username # Обновляем на случай смены

        new_msg.user = existing_user # Связываем сообщение с пользователем
        db.commit()
        db.refresh(new_msg) # Обновляем объект, чтобы получить ID

        # Отправляем DM
        await dm_rate_limiter.wait_if_needed()
        try:
            # Для Telethon, при отправке сообщения пользователю, который не в контактах,
            # мы должны использовать его ID или username.
            # Если username нет, остаётся только ID.
            # `entity=author_id` попытается отправить по ID.
            await client.send_message(
                entity=author_id,
                message=config.INITIAL_QUESTION_TEXT,
                parse_mode='html' # Можно использовать HTML для форматирования
            )
            dm_rate_limiter.record_send()
            new_msg.owner_status = "QUESTION_SENT"
            existing_user.dialog_state = "WAITING_FOR_REPLY"
            db.commit()
            logger.info(f"Sent initial question to user {author_id} for message {message_id}.")
        except (UserIsBlockedError, ChatWriteForbiddenError, UserPrivacyRestrictedError):
            logger.warning(f"User {author_id} blocked bot/has privacy restrictions. Cannot send DM for message {message_id}.")
            new_msg.owner_status = "DM_FAILED_BLOCKED"
            existing_user.dialog_state = "DM_FAILED"
            db.commit()
        except PeerFloodError:
            logger.error(f"PeerFloodError for user {author_id}. Account may be limited. Pausing...")
            new_msg.owner_status = "DM_FAILED_FLOOD"
            existing_user.dialog_state = "DM_FAILED"
            db.commit()
            await asyncio.sleep(random.randint(300, 600)) # Большая пауза
        except FloodWaitError as e:
            logger.error(f"FloodWaitError: {e}. Waiting for {e.seconds} seconds.")
            new_msg.owner_status = "DM_FAILED_FLOOD_WAIT"
            existing_user.dialog_state = "DM_FAILED"
            db.commit()
            await asyncio.sleep(e.seconds + 5) # Ждем немного больше
        except Exception as e:
            logger.error(f"Error sending DM to {author_id} for message {message_id}: {e}", exc_info=True)
            new_msg.owner_status = "DM_FAILED_GENERIC"
            existing_user.dialog_state = "DM_FAILED"
            db.commit()

    except Exception as e:
        logger.error(f"Error processing new channel message {message_id} in {channel_id}: {e}", exc_info=True)
        db.rollback()
    finally:
        db.close()


@client.on(events.NewMessage(incoming=True, func=lambda e: e.is_private))
async def handle_dm_reply(event):
    """Обрабатывает ответы на личные сообщения."""
    sender_id = event.peer_id.user_id # ID пользователя, который ответил
    reply_text = event.message.message.lower()

    db = SessionLocal()
    try:
        user = db.query(TelegramUser).filter_by(telegram_id=sender_id).first()
        if not user or user.dialog_state != "WAITING_FOR_REPLY":
            logger.debug(f"Received DM from {sender_id}, but not in WAITING_FOR_REPLY state.")
            return # Игнорируем, если это не ответ на наш вопрос

        is_owner = False
        is_agent = False

        for keyword in config.OWNER_KEYWORDS:
            if keyword in reply_text:
                is_owner = True
                break
        for keyword in config.AGENT_KEYWORDS:
            if keyword in reply_text:
                is_agent = True
                break

        status_change = False
        if is_owner and not is_agent:
            user.is_owner_confirmed = True
            user.dialog_state = "REPLIED"
            status_change = True
            logger.info(f"User {sender_id} confirmed as OWNER.")
        elif is_agent and not is_owner:
            user.is_owner_confirmed = False
            user.dialog_state = "REPLIED"
            status_change = True
            logger.info(f"User {sender_id} confirmed as AGENT.")
        else:
            # Неопределенный ответ, можно попросить уточнить или пометить как UNKNOWN_REPLY
            user.dialog_state = "UNKNOWN_REPLY"
            logger.info(f"User {sender_id} gave ambiguous reply: '{reply_text}'.")
            # Можно отправить follow-up вопрос
            # await client.send_message(sender_id, "Извините, не совсем понял. Вы собственник или агент?")
            # user.dialog_state = "WAITING_FOR_REPLY_FOLLOW_UP"
            db.commit()
            return # Не меняем статус объявления пока, ждем уточнения или игнорируем
        
        # Обновляем все связанные сообщения, которые ждали ответа от этого пользователя
        pending_messages = db.query(TelegramMessage).filter(
            TelegramMessage.author_telegram_id == sender_id,
            TelegramMessage.owner_status.in_(["QUESTION_SENT", "UNKNOWN"])
        ).all()

        for msg in pending_messages:
            msg.is_processed = True
            if user.is_owner_confirmed:
                msg.owner_status = "OWNER"
                # Отправляем уведомление администратору
                await notify_admin_bot({
                    "message_text": msg.message_text,
                    "author_id": msg.author_telegram_id,
                    "username": user.username,
                    "original_link": msg.original_link,
                    "owner_status": "OWNER"
                })
            else:
                msg.owner_status = "AGENT"
            
        db.commit()

    except Exception as e:
        logger.error(f"Error handling DM reply from {sender_id}: {e}", exc_info=True)
        db.rollback()
    finally:
        db.close()


async def initialize_channels():
    """Загружает активные каналы из БД и присоединяется к ним."""
    db = SessionLocal()
    try:
        active_channels = db.query(Channel).filter_by(is_active=True).all()
        for channel in active_channels:
            try:
                # Получаем полный объект канала
                entity = await client.get_entity(channel.telegram_id)
                # Если это не наш канал, то присоединяемся (если возможно)
                # Это может быть проблема для приватных каналов, если нет invite link
                # Здесь предполагается, что аккаунт агрегатора уже находится в каналах
                logger.info(f"Monitoring channel: {entity.title} ({channel.telegram_id})")

                # Проверка, что бот является участником канала, чтобы читать его
                # Можно использовать get_participants или просто надеяться, что client уже там
                # Например, await client(functions.channels.JoinChannelRequest(entity))
                # Но это может быть рискованно без проверки
            except Exception as e:
                logger.error(f"Could not access channel {channel.telegram_id}: {e}")
                channel.is_active = False # Отключаем проблемный канал
                db.commit()
    finally:
        db.close()


async def main_aggregator():
    logger.info("Starting Aggregator Service...")
    await client.start(phone=config.PHONE_NUMBER)
    logger.info("Telethon client started.")

    await initialize_channels()

    # Запускаем обработчики сообщений
    # Здесь можно добавить другие фоновые задачи, например, периодическую проверку новых каналов
    await client.run_until_disconnected()
    logger.info("Aggregator Service stopped.")

if __name__ == "__main__":
    asyncio.run(main_aggregator())
