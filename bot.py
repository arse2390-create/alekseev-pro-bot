import asyncio
import logging
import os
import re
import sqlite3
from typing import Any

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.enums import ChatType
from aiogram.types import Message
from aiogram.webhook.aiohttp_server import SimpleRequestHandler
from dotenv import load_dotenv
from google import genai
from telethon import TelegramClient
from telethon.sessions import StringSession


load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_API_ID = os.getenv("TELEGRAM_API_ID", "")
TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH", "")
TELEGRAM_GROUP_ID = int(os.getenv("TELEGRAM_GROUP_ID", "-1003948369276"))
TELEGRAM_USER_SESSION = os.getenv(
    "TELEGRAM_USER_SESSION", "alekseev_user_mtproto"
)
TELEGRAM_USER_SESSION_STRING = os.getenv("TELEGRAM_USER_SESSION_STRING", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
RUNTIME_MODE = os.getenv("RUNTIME_MODE", "polling").lower()
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")
WEBHOOK_PATH = "/telegram/webhook"
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL", "")
PORT = int(os.getenv("PORT", "10000"))

SYSTEM_PROMPT = """Ты — официальный ИИ-помощник Владимира Алексеева, автора
канала «АЛЕКСЕЕВ.ПРО» о лайфстайле, здоровье и бизнесе.

Пиши естественно, от лица автора, спокойным, тёплым и экспертным тоном.
Подстраивайся под стиль собеседника: дружеский ответ на дружеский комментарий,
деловой — на деловой. Лёгкая ирония допустима, если её первым использовал
подписчик. Предпочитай короткий ответ: не добавляй мотивационную речь,
объяснения и встречный вопрос, если они не нужны. Владимир часто использует
обычные скобки вместо эмодзи: «Спасибо)», «Места надо знать)))».

Запрещено: мат, грубость, политика, религиозные споры, выдуманные факты,
медицинские диагнозы, гарантии заработка, призывы подписаться и обещание
«я уточню и вернусь». Не раскрывай личные сведения. Спам и бессмысленные
сообщения пропускай. По вопросам сотрудничества направляй к контактам в
профиле канала. Верни только готовый ответ без пояснений.

Никогда не придумывай за Владимира личные факты: распорядок дня, время,
места, покупки, цены, события, знакомства, взгляды, опыт, состояние здоровья
или планы. Используй конкретный факт только тогда, когда он прямо указан в
исходном посте или передан в контексте. Если данных нет, ответь естественно
без конкретики либо мягко уйди от прямого ответа. При прямом вопросе о
неизвестном личном факте мягко уйди от ответа в манере Владимира, например
«Места надо знать)))». Не используй шаблон «Пожалуй, оставлю это за кадром».
Не описывай даже общими словами привычки Владимира, если их нет в контексте.
Не выдавай предположение за факт и не называй придуманные цифры. Если вопрос
состоит из нескольких частей, можно ответить только на ту часть, которую
можно подтвердить по контексту.

ЭТАЛОННЫЕ ОТВЕТЫ ВЛАДИМИРА:
— «У меня определённый график, режим дня и дисциплина».
— «Со временем».
— «Спасибо)».
— «Я активно внедряю в свою жизнь ИИ. С их помощью максимально эффективно
  распределяю свой день».
— Для рекламного поста BRAVO: «Купил у ребят с BRAVO».
— На вопрос о скрытом месте: «Места надо знать)))».
— На вопрос о тренировках: «Программу подбирал специально под себя».

Не копируй эти примеры механически. Используй их как образец краткости,
лексики, пунктуации и степени открытости. Всегда сначала анализируй полный
исходный пост. Если это реклама, используй название бренда, товар, ссылку,
промокод и другие факты только из поста.
"""

SKIP = "[SKIP]"


def validate_secrets() -> None:
    if not TELEGRAM_BOT_TOKEN or "ВСТАВЬТЕ" in TELEGRAM_BOT_TOKEN:
        raise RuntimeError("Добавьте TELEGRAM_BOT_TOKEN в файл .env")
    if not GEMINI_API_KEY or "ВСТАВЬТЕ" in GEMINI_API_KEY:
        raise RuntimeError("Добавьте GEMINI_API_KEY в файл .env")
    if not TELEGRAM_API_ID.isdigit():
        raise RuntimeError("Добавьте числовой TELEGRAM_API_ID в файл .env")
    if not TELEGRAM_API_HASH or "ВСТАВЬТЕ" in TELEGRAM_API_HASH:
        raise RuntimeError("Добавьте TELEGRAM_API_HASH в файл .env")
    if RUNTIME_MODE not in {"polling", "webhook"}:
        raise RuntimeError("RUNTIME_MODE должен быть polling или webhook")
    if RUNTIME_MODE == "webhook":
        if not TELEGRAM_USER_SESSION_STRING:
            raise RuntimeError(
                "Добавьте TELEGRAM_USER_SESSION_STRING для запуска на Render"
            )
        if not RENDER_EXTERNAL_URL:
            raise RuntimeError("Render не передал RENDER_EXTERNAL_URL")
        if not re.fullmatch(r"[A-Za-z0-9_-]{16,256}", WEBHOOK_SECRET):
            raise RuntimeError(
                "WEBHOOK_SECRET должен содержать 16–256 букв, цифр, _ или -"
            )


def init_db() -> sqlite3.Connection:
    db = sqlite3.connect(os.getenv("BOT_DB_PATH", "bot.db"))
    db.execute(
        "CREATE TABLE IF NOT EXISTS processed "
        "(chat_id INTEGER, message_id INTEGER, PRIMARY KEY(chat_id, message_id))"
    )
    db.execute(
        "CREATE TABLE IF NOT EXISTS thread_posts "
        "(chat_id INTEGER, root_message_id INTEGER, post_text TEXT, "
        "PRIMARY KEY(chat_id, root_message_id))"
    )
    db.execute(
        "CREATE TABLE IF NOT EXISTS message_roots "
        "(chat_id INTEGER, message_id INTEGER, root_message_id INTEGER, "
        "PRIMARY KEY(chat_id, message_id))"
    )
    db.commit()
    return db


def already_processed(db: sqlite3.Connection, message: Message) -> bool:
    row = db.execute(
        "SELECT 1 FROM processed WHERE chat_id=? AND message_id=?",
        (message.chat.id, message.message_id),
    ).fetchone()
    return row is not None


def mark_processed(db: sqlite3.Connection, message: Message) -> None:
    db.execute(
        "INSERT OR IGNORE INTO processed(chat_id, message_id) VALUES (?, ?)",
        (message.chat.id, message.message_id),
    )
    db.commit()


def content_of(message: Message) -> str:
    if message.text:
        return message.text
    if message.caption:
        return message.caption
    if message.photo:
        return "Пост содержит фотографию без подписи"
    if message.video:
        return "Пост содержит видео без подписи"
    return "Пост содержит медиа без текста"


def save_post(
    db: sqlite3.Connection, chat_id: int, root_message_id: int, post_text: str
) -> None:
    db.execute(
        "INSERT OR REPLACE INTO thread_posts(chat_id, root_message_id, post_text) "
        "VALUES (?, ?, ?)",
        (chat_id, root_message_id, post_text),
    )
    db.execute(
        "INSERT OR REPLACE INTO message_roots(chat_id, message_id, root_message_id) "
        "VALUES (?, ?, ?)",
        (chat_id, root_message_id, root_message_id),
    )
    db.commit()


def save_message_root(
    db: sqlite3.Connection, chat_id: int, message_id: int, root_message_id: int
) -> None:
    db.execute(
        "INSERT OR REPLACE INTO message_roots(chat_id, message_id, root_message_id) "
        "VALUES (?, ?, ?)",
        (chat_id, message_id, root_message_id),
    )
    db.commit()


def find_root_id(db: sqlite3.Connection, message: Message) -> int | None:
    replied = message.reply_to_message
    if replied and replied.is_automatic_forward:
        return replied.message_id

    if replied:
        row = db.execute(
            "SELECT root_message_id FROM message_roots "
            "WHERE chat_id=? AND message_id=?",
            (message.chat.id, replied.message_id),
        ).fetchone()
        if row:
            return int(row[0])

    if message.message_thread_id:
        row = db.execute(
            "SELECT root_message_id FROM thread_posts "
            "WHERE chat_id=? AND root_message_id=?",
            (message.chat.id, message.message_thread_id),
        ).fetchone()
        if row:
            return int(row[0])
    return None


def get_post_text(
    db: sqlite3.Connection, chat_id: int, root_message_id: int
) -> str | None:
    row = db.execute(
        "SELECT post_text FROM thread_posts WHERE chat_id=? AND root_message_id=?",
        (chat_id, root_message_id),
    ).fetchone()
    return str(row[0]) if row else None


async def resolve_root_id(
    db: sqlite3.Connection,
    message: Message,
    sender: TelegramClient,
    group_entity: Any,
) -> int | None:
    cached = find_root_id(db, message)
    if cached is not None:
        return cached

    telegram_message = await sender.get_messages(
        group_entity, ids=message.message_id
    )
    reply = getattr(telegram_message, "reply_to", None)
    if reply is None:
        return None

    root_id = getattr(reply, "reply_to_top_id", None)
    if root_id is None:
        root_id = getattr(reply, "reply_to_msg_id", None)
    return int(root_id) if root_id is not None else None


async def resolve_post_text(
    db: sqlite3.Connection,
    chat_id: int,
    root_id: int,
    sender: TelegramClient,
    group_entity: Any,
) -> str | None:
    cached = get_post_text(db, chat_id, root_id)
    if cached:
        return cached

    post = await sender.get_messages(group_entity, ids=root_id)
    if post is None:
        return None

    text = (getattr(post, "raw_text", "") or "").strip()
    if not text:
        if getattr(post, "photo", None):
            text = "Пост содержит фотографию без подписи"
        elif getattr(post, "video", None):
            text = "Пост содержит видео без подписи"
        else:
            text = "Пост содержит медиа без текста"
    save_post(db, chat_id, root_id, text)
    return text


def create_runtime() -> dict[str, Any]:
    validate_secrets()
    logging.basicConfig(level=logging.INFO)

    bot = Bot(TELEGRAM_BOT_TOKEN)
    dispatcher = Dispatcher()
    gemini = genai.Client(api_key=GEMINI_API_KEY)
    db = init_db()
    session: str | StringSession
    if TELEGRAM_USER_SESSION_STRING:
        session = StringSession(TELEGRAM_USER_SESSION_STRING)
    else:
        session = TELEGRAM_USER_SESSION
    sender = TelegramClient(
        session,
        int(TELEGRAM_API_ID),
        TELEGRAM_API_HASH,
        receive_updates=False,
    )

    runtime: dict[str, Any] = {
        "bot": bot,
        "dispatcher": dispatcher,
        "gemini": gemini,
        "db": db,
        "sender": sender,
        "bot_user_id": None,
        "group_entity": None,
    }

    @dispatcher.message()
    async def answer_comment(message: Message) -> None:
        if message.chat.type == ChatType.PRIVATE:
            if message.text and message.text.startswith("/start"):
                await message.reply(
                    "Бот запущен и готов к работе)\n\n"
                    "Основные ответы он публикует под постами канала "
                    "АЛЕКСЕЕВ.ПРО после подключения к группе обсуждений."
                )
            return

        if message.chat.type not in {ChatType.GROUP, ChatType.SUPERGROUP}:
            return
        if message.chat.id != TELEGRAM_GROUP_ID:
            return

        if message.is_automatic_forward:
            save_post(db, message.chat.id, message.message_id, content_of(message))
            return

        if message.from_user is None:
            return
        if message.from_user.id == runtime["bot_user_id"]:
            return
        if message.from_user.is_bot or already_processed(db, message) or not message.text:
            return

        sender_client: TelegramClient = runtime["sender"]
        group_entity = runtime["group_entity"]

        try:
            root_id = await resolve_root_id(
                db, message, sender_client, group_entity
            )
            if root_id is None:
                return

            replied = message.reply_to_message
            if replied and replied.is_automatic_forward:
                save_post(db, message.chat.id, root_id, content_of(replied))

            post_context = await resolve_post_text(
                db,
                message.chat.id,
                root_id,
                sender_client,
                group_entity,
            )
            if not post_context:
                return
            save_message_root(db, message.chat.id, message.message_id, root_id)

            prompt = f"""{SYSTEM_PROMPT}

Если комментарий не требует ответа, является спамом или бессмысленным,
верни ровно {SKIP}.

ИСХОДНЫЙ ПОСТ:
{post_context}

КОММЕНТАРИЙ:
{message.text}
"""

            result = await asyncio.to_thread(
                gemini.models.generate_content,
                model=GEMINI_MODEL,
                contents=prompt,
            )
            answer = (result.text or "").strip()
            if not answer or answer == SKIP:
                mark_processed(db, message)
                return

            sent = await sender_client.send_message(
                group_entity,
                answer,
                reply_to=message.message_id,
                send_as=group_entity,
                parse_mode=None,
                link_preview=False,
            )
            save_message_root(db, message.chat.id, sent.id, root_id)
            mark_processed(db, message)
        except Exception:
            logging.exception("Не удалось обработать комментарий")

    return runtime


async def start_runtime(runtime: dict[str, Any]) -> None:
    bot: Bot = runtime["bot"]
    sender: TelegramClient = runtime["sender"]

    runtime["bot_user_id"] = (await bot.get_me()).id
    await asyncio.wait_for(sender.connect(), timeout=45)
    if not await sender.is_user_authorized():
        raise RuntimeError(
            "Telegram-аккаунт не авторизован. Создайте новую пользовательскую сессию."
        )

    group_entity = None
    try:
        group_entity = await asyncio.wait_for(
            sender.get_entity(TELEGRAM_GROUP_ID), timeout=15
        )
    except (ValueError, asyncio.TimeoutError):
        dialogs = await asyncio.wait_for(
            sender.get_dialogs(limit=100), timeout=30
        )
        for dialog in dialogs:
            if dialog.id == TELEGRAM_GROUP_ID:
                group_entity = dialog.entity
                break
    if group_entity is None:
        raise RuntimeError("Группа АЛЕКСЕЕВ.ПРО не найдена в Telegram-аккаунте")
    runtime["group_entity"] = group_entity


async def stop_runtime(runtime: dict[str, Any], close_bot: bool = True) -> None:
    runtime["db"].close()
    await runtime["sender"].disconnect()
    if close_bot:
        await runtime["bot"].session.close()


async def run_polling() -> None:
    runtime = create_runtime()
    try:
        await start_runtime(runtime)
        await runtime["bot"].delete_webhook(drop_pending_updates=False)
        await runtime["dispatcher"].start_polling(
            runtime["bot"], allowed_updates=["message"]
        )
    finally:
        await stop_runtime(runtime)


def create_webhook_app() -> web.Application:
    runtime = create_runtime()
    bot: Bot = runtime["bot"]
    dispatcher: Dispatcher = runtime["dispatcher"]
    app = web.Application()

    async def health(_: web.Request) -> web.Response:
        return web.json_response({"status": "ok", "service": "alekseev-pro-bot"})

    async def startup(_: web.Application) -> None:
        await start_runtime(runtime)
        webhook_url = f"{RENDER_EXTERNAL_URL.rstrip('/')}{WEBHOOK_PATH}"
        await bot.set_webhook(
            webhook_url,
            secret_token=WEBHOOK_SECRET,
            allowed_updates=["message"],
            drop_pending_updates=False,
        )
        logging.info("Webhook configured")

    async def shutdown(_: web.Application) -> None:
        await stop_runtime(runtime, close_bot=False)

    app.router.add_get("/", health)
    SimpleRequestHandler(
        dispatcher=dispatcher,
        bot=bot,
        handle_in_background=True,
        secret_token=WEBHOOK_SECRET,
    ).register(app, path=WEBHOOK_PATH)
    app.on_startup.append(startup)
    app.on_shutdown.append(shutdown)
    return app


if __name__ == "__main__":
    if RUNTIME_MODE == "webhook":
        web.run_app(
            create_webhook_app(),
            host="0.0.0.0",
            port=PORT,
            access_log=None,
        )
    else:
        asyncio.run(run_polling())
