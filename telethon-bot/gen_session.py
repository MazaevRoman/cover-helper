"""
Одноразовый генератор StringSession для Telethon.
Запускать ЛОКАЛЬНО и интерактивно (не в контейнере) — спросит телефон, код и,
если на аккаунте включён облачный пароль, 2FA-пароль.

    pip install "telethon>=1.36,<2"
    python gen_session.py

api_id / api_hash берутся на https://my.telegram.org (залогинься под тем же
номером — код придёт в Telegram, ты его сейчас принимаешь сам).

Результат — строка SESSION_STRING. Это ПОЛНЫЙ доступ к аккаунту: не коммить,
не пересылай в чат, клади только в env Dokploy как секрет.
"""

import asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession

api_id = int(input("api_id: ").strip())
api_hash = input("api_hash: ").strip()


async def main():
    async with TelegramClient(StringSession(), api_id, api_hash) as client:
        me = await client.get_me()
        print("\nЗашли как:", me.first_name, "| @" + (me.username or "—"), "| id", me.id)
        print("\n=== SESSION_STRING (в Dokploy env, секрет) ===\n")
        print(client.session.save())
        print("\n=== держать в секрете ===")


asyncio.run(main())
