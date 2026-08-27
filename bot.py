import asyncio
import logging
import os
import sqlite3
import ssl
from typing import Any

import certifi
from aiohttp import ClientSession, ClientTimeout, TCPConnector, web
from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.sessions import StringSession


load_dotenv()

TELEGRAM_API_ID = os.getenv("TELEGRAM_API_ID", "")
TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH", "")
TELEGRAM_GROUP_ID = int(os.getenv("TELEGRAM_GROUP_ID", "-1003948369276"))
TELEGRAM_USER_SESSION_STRING = os.getenv("TELEGRAM_USER_SESSION_STRING", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
BOT_DB_PATH = os.getenv("BOT_DB_PATH", "bot.db")
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


def validate_config() -> None:
    if not TELEGRAM_API_ID.isdigit():
        raise RuntimeError("TELEGRAM_API_ID is missing")
    if not TELEGRAM_API_HASH:
        raise RuntimeError("TELEGRAM_API_HASH is missing")
    if not TELEGRAM_USER_SESSION_STRING:
        raise RuntimeError("TELEGRAM_USER_SESSION_STRING is missing")
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is missing")


def open_db() -> sqlite3.Connection:
    parent = os.path.dirname(BOT_DB_PATH)
    if parent:
        os.makedirs(parent, exist_ok=True)
    db = sqlite3.connect(BOT_DB_PATH)
    db.execute(
        "CREATE TABLE IF NOT EXISTS processed "
        "(chat_id INTEGER, message_id INTEGER, PRIMARY KEY(chat_id, message_id))"
    )
    db.commit()
    return db


def was_processed(db: sqlite3.Connection, message_id: int) -> bool:
    return (
        db.execute(
            "SELECT 1 FROM processed WHERE chat_id=? AND message_id=?",
            (TELEGRAM_GROUP_ID, message_id),
        ).fetchone()
        is not None
    )


def mark_processed(db: sqlite3.Connection, message_id: int) -> None:
    db.execute(
        "INSERT OR IGNORE INTO processed(chat_id, message_id) VALUES (?, ?)",
        (TELEGRAM_GROUP_ID, message_id),
    )
    db.commit()


def post_text(message: Any) -> str:
    text = (getattr(message, "raw_text", "") or "").strip()
    if text:
        return text
    media = getattr(message, "media", None)
    if media is None:
        return "Пост без текста"
    name = type(media).__name__.lower()
    if "photo" in name:
        return "Пост содержит фотографию без подписи"
    return "Пост содержит видео или другое медиа без подписи"


async def ask_gemini(http: ClientSession, source_post: str, comment: str) -> str:
    prompt = f"""{SYSTEM_PROMPT}

Если комментарий не требует ответа, является спамом или бессмысленным,
верни ровно {SKIP}.

ИСХОДНЫЙ ПОСТ:
{source_post}

КОММЕНТАРИЙ:
{comment}
"""
    model = GEMINI_MODEL.removeprefix("models/")
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent"
    )
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.65, "maxOutputTokens": 350},
    }
    async with http.post(
        url, params={"key": GEMINI_API_KEY}, json=payload
    ) as response:
        data = await response.json(content_type=None)
        if response.status >= 400:
            raise RuntimeError(f"Gemini HTTP {response.status}: {data}")
    candidates = data.get("candidates") or []
    if not candidates:
        return ""
    parts = candidates[0].get("content", {}).get("parts", [])
    return "".join(str(part.get("text", "")) for part in parts).strip()


async def start_health_server() -> web.AppRunner:
    app = web.Application()
    app.router.add_get(
        "/",
        lambda _: web.json_response(
            {"status": "ok", "service": "alekseev-pro-bot"}
        ),
    )
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    return runner


async def main() -> None:
    validate_config()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    db = open_db()
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    http = ClientSession(
        timeout=ClientTimeout(total=45),
        connector=TCPConnector(ssl=ssl_context),
    )
    client = TelegramClient(
        StringSession(TELEGRAM_USER_SESSION_STRING),
        int(TELEGRAM_API_ID),
        TELEGRAM_API_HASH,
    )
    health_runner: web.AppRunner | None = None
    response_lock = asyncio.Semaphore(2)

    try:
        await client.connect()
        if not await client.is_user_authorized():
            raise RuntimeError("Telegram session is not authorized")
        group = await client.get_entity(TELEGRAM_GROUP_ID)

        async def answer_comment(event: events.NewMessage.Event) -> None:
            message = event.message
            sender_id = getattr(message, "sender_id", None)
            text = (getattr(message, "raw_text", "") or "").strip()

            # Real users have positive IDs. This prevents anonymous group
            # replies from triggering a reply loop.
            if not text or sender_id is None or sender_id <= 0:
                return
            if getattr(message, "out", False) or was_processed(db, message.id):
                return

            reply = getattr(message, "reply_to", None)
            if reply is None:
                return
            root_id = getattr(reply, "reply_to_top_id", None)
            if root_id is None:
                root_id = getattr(reply, "reply_to_msg_id", None)
            if root_id is None:
                return

            try:
                async with response_lock:
                    root = await client.get_messages(group, ids=int(root_id))
                    if root is None:
                        return
                    answer = await ask_gemini(http, post_text(root), text)
                    if not answer or answer == SKIP:
                        mark_processed(db, message.id)
                        return
                    await client.send_message(
                        group,
                        answer,
                        reply_to=message.id,
                        send_as=group,
                        parse_mode=None,
                        link_preview=False,
                    )
                    mark_processed(db, message.id)
            except Exception:
                logging.exception("Failed to answer comment %s", message.id)

        client.add_event_handler(answer_comment, events.NewMessage(chats=group))
        health_runner = await start_health_server()
        logging.info("Bot is running")
        await client.run_until_disconnected()
    finally:
        if health_runner is not None:
            await health_runner.cleanup()
        await http.close()
        await client.disconnect()
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
