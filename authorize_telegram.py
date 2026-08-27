import asyncio
import os

import qrcode
from dotenv import load_dotenv
from telethon import TelegramClient


load_dotenv()

API_ID = int(os.environ["TELEGRAM_API_ID"].strip())
API_HASH = os.environ["TELEGRAM_API_HASH"].strip()
QR_PATH = "telegram-login-qr.png"
SESSION_NAME = "alekseev_user_mtproto"


async def main() -> None:
    client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
    await client.connect()

    try:
        if await client.is_user_authorized():
            print("ALREADY_AUTHORIZED", flush=True)
            return

        for attempt in range(1, 21):
            qr_login = await client.qr_login()
            image = qrcode.make(qr_login.url)
            image.save(QR_PATH)
            print(f"QR_READY attempt={attempt}", flush=True)

            try:
                user = await qr_login.wait()
            except asyncio.TimeoutError:
                print("QR_EXPIRED", flush=True)
                continue

            display_name = " ".join(
                part for part in (user.first_name, user.last_name) if part
            )
            print(f"AUTHORIZED name={display_name!r}", flush=True)
            return

        print("AUTHORIZATION_TIMEOUT", flush=True)
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
