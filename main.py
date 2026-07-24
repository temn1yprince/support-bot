import json
import logging
import os
from pathlib import Path

from telegram import Update
from telegram.constants import ChatType
from telegram.ext import (
    Application,
    ApplicationBuilder,
    ContextTypes,
    MessageHandler,
    CommandHandler,
    filters,
)

# ---------------------------------------------------------------------------
# Настройки (берутся из переменных окружения — задаются в Railway → Variables)
# ---------------------------------------------------------------------------
BOT_TOKEN = os.environ["BOT_TOKEN"]                 # токен бота от @BotFather
ADMIN_CHAT_ID = int(os.environ["ADMIN_CHAT_ID"])    # ваш personal chat_id (число)

# Файл, в котором храним связку "id сообщения у админа" -> "id пользователя".
# Она нужна, чтобы бот понимал, кому именно отправить ваш ответ, когда вы
# отвечаете (Reply) на пересланное сообщение.
MAP_FILE = Path(__file__).parent / "support_map.json"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Хранилище связок message_id -> user_id (простой json-файл на диске)
# ---------------------------------------------------------------------------
def load_map() -> dict:
    if MAP_FILE.exists():
        try:
            return json.loads(MAP_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def save_map(data: dict) -> None:
    MAP_FILE.write_text(json.dumps(data), encoding="utf-8")


# ---------------------------------------------------------------------------
# /start — приветствие для пользователя
# ---------------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat.id == ADMIN_CHAT_ID:
        await update.message.reply_text(
            "Это бот тех.поддержки.\n\n"
            "Когда пользователь напишет боту — вы увидите его сообщение здесь "
            "вместе с именем/юзернеймом.\n"
            "Чтобы ответить конкретному человеку — сделайте Reply (ответ) "
            "на его сообщение и напишите текст (или пришлите фото/файл и т.д.)."
        )
    else:
        await update.message.reply_text(
            "Здравствуйте! Напишите ваш вопрос, и мы ответим вам как можно скорее."
        )


# ---------------------------------------------------------------------------
# Сообщение от обычного пользователя -> пересылаем админу одним сообщением
# ---------------------------------------------------------------------------
def build_header(update: Update) -> str:
    user = update.effective_user
    name = user.full_name or "Без имени"
    username = f"@{user.username}" if user.username else "нет username"
    return f"👤 {name} ({username})\nID: {user.id}"


async def handle_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    if message is None:
        return

    header = build_header(update)
    user_id = update.effective_user.id

    sent = None

    # Обычный текст — просто одно сообщение "шапка + текст"
    if message.text:
        combined = f"{header}\n\n{message.text}"
        sent = await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=combined)

    # Фото / видео / документ / голосовое / аудио — используем copy_message
    # и подменяем подпись (caption), чтобы шапка и содержимое были одним сообщением
    elif message.photo or message.video or message.document or message.voice or message.audio:
        caption = header if not message.caption else f"{header}\n\n{message.caption}"
        sent = await context.bot.copy_message(
            chat_id=ADMIN_CHAT_ID,
            from_chat_id=update.effective_chat.id,
            message_id=message.message_id,
            caption=caption,
        )
    else:
        # Стикеры, видеосообщения (кружки) и т.п. не поддерживают caption в Telegram API,
        # поэтому для них шапку отправляем отдельным сообщением перед самим стикером/кружком.
        await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=header)
        sent = await context.bot.copy_message(
            chat_id=ADMIN_CHAT_ID,
            from_chat_id=update.effective_chat.id,
            message_id=message.message_id,
        )

    if sent is not None:
        data = load_map()
        data[str(sent.message_id)] = user_id
        save_map(data)


# ---------------------------------------------------------------------------
# Ответ админа -> отправляем конкретному пользователю
# ---------------------------------------------------------------------------
async def handle_admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    if message is None or message.reply_to_message is None:
        await update.message.reply_text(
            "Чтобы ответить пользователю, сделайте Reply (ответ) на его сообщение."
        )
        return

    data = load_map()
    replied_id = str(message.reply_to_message.message_id)
    user_id = data.get(replied_id)

    if user_id is None:
        await update.message.reply_text(
            "Не нашёл, кому это адресовано. Отвечайте (Reply) прямо на сообщение "
            "пользователя, пересланное ботом."
        )
        return

    try:
        await context.bot.copy_message(
            chat_id=user_id,
            from_chat_id=ADMIN_CHAT_ID,
            message_id=message.message_id,
        )
        await update.message.reply_text("✅ Отправлено пользователю.")
    except Exception as exc:  # пользователь мог заблокировать бота и т.п.
        logger.exception("Не удалось отправить ответ пользователю")
        await update.message.reply_text(f"⚠️ Не удалось отправить: {exc}")


# ---------------------------------------------------------------------------
# Сборка приложения
# ---------------------------------------------------------------------------
def main() -> None:
    application: Application = ApplicationBuilder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))

    # Сообщения от админа в личке с ботом
    application.add_handler(
        MessageHandler(
            filters.Chat(ADMIN_CHAT_ID) & filters.ChatType.PRIVATE & ~filters.COMMAND,
            handle_admin_reply,
        )
    )

    # Сообщения от всех остальных пользователей (личка с ботом)
    application.add_handler(
        MessageHandler(
            filters.ChatType.PRIVATE & ~filters.Chat(ADMIN_CHAT_ID) & ~filters.COMMAND,
            handle_user_message,
        )
    )

    logger.info("Бот запущен, ожидаю сообщения...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
