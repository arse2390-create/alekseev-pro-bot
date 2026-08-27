# АЛЕКСЕЕВ.ПРО — Telegram × Gemini

## 1. Добавьте настройки

Откройте `.env` и заполните токен Telegram-бота, ключ Gemini, `api_id` и
`api_hash` Telegram. Не добавляйте пробелы вокруг `=` и не отправляйте файл
другим людям.

## 2. Установите зависимости

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## 3. Один раз подключите Telegram-аккаунт

```bash
python authorize_telegram.py
```

Сохранённая `.session` нужна, чтобы отправлять ответы от имени группы. Она
содержит доступ к Telegram-аккаунту, поэтому не передавайте её другим людям.

## 4. Запустите

```bash
python bot.py
```

Бот и подключённый Telegram-аккаунт должны быть администраторами привязанной
группы обсуждений. Для аккаунта должна быть включена анонимность администратора.
В BotFather должны быть включены **Allow Groups** и отключён **Group Privacy**.

Бот получает новые текстовые комментарии через Bot API, анализирует исходный
пост и комментарий с помощью Gemini, а затем отвечает через MTProto от имени
группы «АЛЕКСЕЕВ.ПРО».

## Бесплатный запуск на Render

В репозитории находится `render.yaml` для бесплатного Web Service. На Render
бот работает через Telegram webhook, а не через постоянный polling. После сна
первый новый комментарий пробуждает сервис.

Render запросит следующие секретные переменные:

- `TELEGRAM_BOT_TOKEN`;
- `GEMINI_API_KEY`;
- `TELEGRAM_API_ID`;
- `TELEGRAM_API_HASH`;
- `TELEGRAM_USER_SESSION_STRING`;
- `WEBHOOK_SECRET`.

Не добавляйте их в GitHub. `TELEGRAM_USER_SESSION_STRING` даёт доступ к
Telegram-аккаунту и должна храниться только в защищённых настройках Render.
Переменная `RENDER_EXTERNAL_URL` добавляется самим Render и используется для
автоматической настройки webhook.
