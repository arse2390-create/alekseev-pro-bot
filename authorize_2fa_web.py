import asyncio
import os

from aiohttp import web
from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.errors import PasswordHashInvalidError


load_dotenv()

API_ID = int(os.environ["TELEGRAM_API_ID"].strip())
API_HASH = os.environ["TELEGRAM_API_HASH"].strip()
SESSION_NAME = "alekseev_user_mtproto"

client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
state = {"status": "waiting", "message": "Введите облачный пароль Telegram"}

PAGE = """<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Завершение входа в Telegram</title>
  <style>
    * { box-sizing: border-box; }
    body { margin: 0; min-height: 100vh; display: grid; place-items: center; background: #f4f7fb; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: #17212b; }
    main { width: min(92vw, 460px); background: #fff; padding: 32px; border-radius: 20px; box-shadow: 0 12px 40px rgba(23,33,43,.12); }
    h1 { margin: 0 0 10px; font-size: 25px; }
    p { color: #536471; line-height: 1.45; }
    input { width: 100%; padding: 14px 15px; margin: 8px 0 12px; border: 1px solid #c8d2dc; border-radius: 12px; font-size: 17px; }
    button { width: 100%; padding: 14px; border: 0; border-radius: 12px; background: #2aabee; color: white; font-size: 17px; font-weight: 650; cursor: pointer; }
    button:disabled { opacity: .6; }
    #result { min-height: 24px; margin-top: 14px; font-weight: 600; }
    .ok { color: #15803d; }
    .error { color: #b91c1c; }
    small { display: block; margin-top: 14px; color: #718096; line-height: 1.4; }
  </style>
</head>
<body>
  <main>
    <h1>Облачный пароль Telegram</h1>
    <p>QR принят. Введите пароль двухэтапной защиты, чтобы завершить подключение.</p>
    <form id="form">
      <input id="password" type="password" autocomplete="current-password" placeholder="Облачный пароль" required autofocus>
      <button id="submit" type="submit">Подключить</button>
    </form>
    <div id="result"></div>
    <small>Страница работает только на вашем компьютере. Пароль не записывается в файл и не отображается в журнале.</small>
  </main>
  <script>
    const form = document.getElementById('form');
    const password = document.getElementById('password');
    const submit = document.getElementById('submit');
    const result = document.getElementById('result');
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      submit.disabled = true;
      result.className = '';
      result.textContent = 'Проверяю…';
      const response = await fetch('/password', {
        method: 'POST',
        headers: {'Content-Type': 'application/x-www-form-urlencoded'},
        body: new URLSearchParams({password: password.value})
      });
      password.value = '';
      const data = await response.json();
      result.textContent = data.message;
      result.className = data.status === 'authorized' ? 'ok' : 'error';
      submit.disabled = data.status === 'authorized';
      if (data.status === 'authorized') form.style.display = 'none';
    });
  </script>
</body>
</html>"""


async def index(_: web.Request) -> web.Response:
    return web.Response(text=PAGE, content_type="text/html")


async def submit_password(request: web.Request) -> web.Response:
    form = await request.post()
    password = str(form.get("password", ""))
    if not password:
        return web.json_response({"status": "error", "message": "Введите пароль"}, status=400)

    try:
        await client.sign_in(password=password)
    except PasswordHashInvalidError:
        state.update(status="error", message="Пароль неверный. Попробуйте ещё раз.")
    except Exception as exc:
        state.update(status="error", message=f"Не удалось завершить вход: {type(exc).__name__}")
    else:
        state.update(status="authorized", message="Готово — Telegram подключён")
        print("AUTHORIZED", flush=True)
    finally:
        password = ""

    return web.json_response(state)


async def main() -> None:
    await client.connect()
    if await client.is_user_authorized():
        state.update(status="authorized", message="Telegram уже подключён")

    app = web.Application(client_max_size=4096)
    app.router.add_get("/", index)
    app.router.add_post("/password", submit_password)

    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 8765)
    await site.start()
    print("LOCAL_2FA_PAGE_READY", flush=True)

    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
