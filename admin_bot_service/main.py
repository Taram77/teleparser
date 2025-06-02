import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.exc import IntegrityError
import config
from database import SessionLocal, Channel, Setting
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("admin_bot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

bot = Bot(token=config.BOT_TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher(storage=MemoryStorage())

# State for adding channels
class ChannelForm(StatesGroup):
    waiting_for_channel_id = State()

# State for changing welcome text
class WelcomeTextForm(StatesGroup):
    waiting_for_new_text = State()

# Middleware для передачи сессии БД в хэндлеры
async def db_session_middleware(handler, event, data):
    db = SessionLocal()
    data["db"] = db
    try:
        return await handler(event, data)
    finally:
        db.close()

dp.message.middleware(db_session_middleware) # Применяем middleware

@dp.message(lambda message: message.chat.id != config.ADMIN_CHAT_ID)
async def handle_non_admin_messages(message: types.Message):
    """Отвечаем на сообщения от неадминов."""
    await message.reply("Извините, этот бот предназначен только для администраторов.")

@dp.message(commands=["start"])
async def command_start_handler(message: types.Message):
    """Обрабатывает команду /start."""
    text = (
        "Привет, администратор!\n\n"
        "Я бот для поиска собственников недвижимости.\n"
        "Доступные команды:\n"
        "/channels - Управление каналами для мониторинга\n"
        "/text - Изменить текст приветственного сообщения\n"
        "/status - Получить статус агрегатора (в разработке)\n"
        "/stop - Остановить агрегатор (в разработке)\n"
    )
    await message.answer(text)

@dp.message(commands=["channels"])
async def command_channels_handler(message: types.Message, db: SessionLocal):
    """Показывает список каналов и предлагает добавить/удалить."""
    channels = db.query(Channel).all()
    if not channels:
        response = "Пока нет добавленных каналов."
    else:
        response = "<b>Мониторинг каналов:</b>\n"
        for ch in channels:
            status = "🟢 Активен" if ch.is_active else "🔴 Неактивен"
            response += f"- <code>{ch.telegram_id}</code>: {ch.title} ({status})\n"
    
    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text="➕ Добавить канал", callback_data="add_channel")],
            [types.InlineKeyboardButton(text="✏️ Изменить статус канала", callback_data="toggle_channel_status")]
        ]
    )
    await message.answer(response, reply_markup=keyboard)

@dp.callback_query(lambda c: c.data == "add_channel")
async def callback_add_channel(callback_query: types.CallbackQuery, state: FSMContext):
    await callback_query.answer()
    await callback_query.message.answer("Пожалуйста, введите ID или ссылку на канал (например, <code>@channel_username</code> или <code>-1001234567890</code>):")
    await state.set_state(ChannelForm.waiting_for_channel_id)

@dp.message(ChannelForm.waiting_for_channel_id)
async def process_channel_id(message: types.Message, state: FSMContext, db: SessionLocal):
    channel_input = message.text.strip()
    # Здесь нужно было бы получить Telegram ID канала по username/ссылке
    # Но для aiogram это сложнее, чем для Telethon. 
    # В реальном проекте Aggregator Service мог бы иметь endpoint для этого,
    # или админ должен вводить только числовой ID.
    
    try:
        telegram_id = int(channel_input) # Предполагаем, что админ вводит ID
        # Можно попробовать получить информацию о канале через бота (но он не всегда может видеть приватные)
        # chat = await bot.get_chat(telegram_id)
        # title = chat.title
        title = f"Канал {telegram_id}" # Заглушка, если нет возможности получить название

        existing_channel = db.query(Channel).filter_by(telegram_id=telegram_id).first()
        if existing_channel:
            await message.answer(f"Канал <code>{telegram_id}</code> (<b>{existing_channel.title}</b>) уже существует.")
        else:
            new_channel = Channel(telegram_id=telegram_id, title=title, is_active=True)
            db.add(new_channel)
            db.commit()
            await message.answer(f"Канал <code>{telegram_id}</code> (<b>{title}</b>) добавлен для мониторинга.")
    except ValueError:
        await message.answer("Неверный формат ID. Пожалуйста, введите числовой ID.")
    except IntegrityError:
        db.rollback()
        await message.answer(f"Канал <code>{telegram_id}</code> уже существует в базе данных.")
    except Exception as e:
        logger.error(f"Error adding channel {channel_input}: {e}", exc_info=True)
        await message.answer(f"Произошла ошибка при добавлении канала: {e}")
    finally:
        await state.clear()
        await command_channels_handler(message, db) # Показать обновленный список


@dp.callback_query(lambda c: c.data == "toggle_channel_status")
async def callback_toggle_channel_status(callback_query: types.CallbackQuery, db: SessionLocal):
    await callback_query.answer()
    channels = db.query(Channel).all()
    if not channels:
        await callback_query.message.answer("Нет каналов для изменения статуса.")
        return

    keyboard_buttons = []
    for ch in channels:
        status_text = "🟢 Активен" if ch.is_active else "🔴 Неактивен"
        keyboard_buttons.append(
            [types.InlineKeyboardButton(text=f"{ch.title} ({ch.telegram_id}) - {status_text}", callback_data=f"toggle_channel_{ch.telegram_id}")]
        )
    
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    await callback_query.message.answer("Выберите канал для изменения статуса:", reply_markup=keyboard)

@dp.callback_query(lambda c: c.data.startswith("toggle_channel_"))
async def callback_toggle_channel_status_confirm(callback_query: types.CallbackQuery, db: SessionLocal):
    await callback_query.answer()
    channel_id = int(callback_query.data.split("_")[2])
    channel = db.query(Channel).filter_by(telegram_id=channel_id).first()

    if channel:
        channel.is_active = not channel.is_active
        db.commit()
        status_text = "активирован" if channel.is_active else "деактивирован"
        await callback_query.message.edit_text(f"Статус канала <b>{channel.title}</b> (<code>{channel.telegram_id}</code>) изменен на: {status_text}.", reply_markup=None)
        await command_channels_handler(callback_query.message, db)
    else:
        await callback_query.message.answer("Канал не найден.")

@dp.message(commands=["text"])
async def command_text_handler(message: types.Message, state: FSMContext, db: SessionLocal):
    current_text_setting = db.query(Setting).filter_by(key="INITIAL_QUESTION_TEXT").first()
    current_text = current_text_setting.value if current_text_setting else config.INITIAL_QUESTION_TEXT
    
    await message.answer(
        f"Текущий текст приветственного сообщения:\n\n<code>{current_text}</code>\n\n"
        "Введите новый текст:"
    )
    await state.set_state(WelcomeTextForm.waiting_for_new_text)

@dp.message(WelcomeTextForm.waiting_for_new_text)
async def process_new_welcome_text(message: types.Message, state: FSMContext, db: SessionLocal):
    new_text = message.text.strip()
    if not new_text:
        await message.answer("Текст не может быть пустым. Попробуйте еще раз.")
        return
    
    setting = db.query(Setting).filter_by(key="INITIAL_QUESTION_TEXT").first()
    if setting:
        setting.value = new_text
    else:
        setting = Setting(key="INITIAL_QUESTION_TEXT", value=new_text, description="Текст первого вопроса при обращении к собственнику.")
        db.add(setting)
    
    db.commit()
    config.INITIAL_QUESTION_TEXT = new_text # Обновляем конфиг в рантайме (для агрегатора это нужно будет обновлять по-другому)
    await message.answer("Текст приветственного сообщения обновлен!")
    await state.clear()

async def main_admin_bot():
    logger.info("Starting Admin Bot Service...")
    await dp.start_polling(bot)
    logger.info("Admin Bot Service stopped.")

if __name__ == "__main__":
    asyncio.run(main_admin_bot())
