from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import uvicorn
from aiogram import Bot
import config
from database import SessionLocal, TelegramMessage, TelegramUser, Channel, Setting
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("admin_api.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


app = FastAPI(title="Admin Bot Internal API")
bot = Bot(token=config.BOT_TOKEN)

class OwnerNotification(BaseModel):
    message_text: str
    author_id: int
    username: str | None = None
    original_link: str | None = None
    owner_status: str # Should be "OWNER"

@app.post("/notify_owner")
async def notify_owner_endpoint(data: OwnerNotification):
    """
    Endpoint для получения уведомлений от Aggregator Service о подтвержденных собственниках.
    """
    notification_text = (
        "🔥 **Подтвержден собственник!**\n\n"
        f"**Объявление:**\n{data.message_text[:1000]}{'...' if len(data.message_text) > 1000 else ''}\n\n"
        f"**Автор:** [{data.username or data.author_id}](tg://user?id={data.author_id})\n"
        f"**ID:** `{data.author_id}`\n"
    )
    if data.original_link:
        notification_text += f"**Оригинал:** [Сообщение в канале]({data.original_link})\n"

    try:
        await bot.send_message(config.ADMIN_CHAT_ID, notification_text, parse_mode="Markdown")
        logger.info(f"Admin notified about new owner: {data.username or data.author_id}")
        return {"status": "success", "message": "Admin notified"}
    except Exception as e:
        logger.error(f"Failed to send notification to admin chat {config.ADMIN_CHAT_ID}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to send notification: {e}")

async def start_admin_api():
    config_uvicorn = uvicorn.Config(app, host=config.ADMIN_BOT_API_HOST, port=config.ADMIN_BOT_API_PORT, log_level="info")
    server = uvicorn.Server(config_uvicorn)
    logger.info(f"Admin Bot Internal API started on {config.ADMIN_BOT_API_HOST}:{config.ADMIN_BOT_API_PORT}")
    await server.serve()

if __name__ == "__main__":
    asyncio.run(start_admin_api())
