import os
from dotenv import load_dotenv

load_dotenv()

# Telegram Bot API (для Admin Bot)
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0")) # ID чата или пользователя, куда слать уведомления

# Telegram User API (для Aggregator Service)
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH")
PHONE_NUMBER = os.getenv("PHONE_NUMBER") # Номер телефона аккаунта агрегатора

# Database
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "postgres")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "telegram_owner_finder")

DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# Redis (опционально)
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("REDIS_DB", "0"))

# Internal API для Admin Bot (для уведомлений от Aggregator)
ADMIN_BOT_API_HOST = os.getenv("ADMIN_BOT_API_HOST", "localhost")
ADMIN_BOT_API_PORT = int(os.getenv("ADMIN_BOT_API_PORT", "8001"))
ADMIN_BOT_API_URL = f"http://{ADMIN_BOT_API_HOST}:{ADMIN_BOT_API_PORT}"

# Aggregator settings
INITIAL_QUESTION_TEXT = os.getenv(
    "INITIAL_QUESTION_TEXT",
    "Здравствуйте! Подскажите, вы собственник квартиры или агент?",
)
OWNER_KEYWORDS = [
    "собственник",
    "хозяин",
    "я",
    "мой",
    "мое",
    "напрямую",
    "сам",
    "без посредников",
]
AGENT_KEYWORDS = ["агент", "посредник", "риелтор", "брокер", "не я", "нет"]
CHANNEL_FILTER_KEYWORDS = [
    "продажа",
    "квартира",
    "м²",
    "цена",
    "руб",
    "собственник",
    "без комиссии",
]

# Anti-ban settings
DM_SEND_INTERVAL_MIN = int(os.getenv("DM_SEND_INTERVAL_MIN", "5")) # Минимальная задержка между DM в секундах
DM_SEND_INTERVAL_MAX = int(os.getenv("DM_SEND_INTERVAL_MAX", "15")) # Максимальная задержка между DM в секундах
DAILY_DM_LIMIT_PER_ACCOUNT = int(os.getenv("DAILY_DM_LIMIT_PER_ACCOUNT", "50")) # Дневной лимит DM с одного аккаунта
