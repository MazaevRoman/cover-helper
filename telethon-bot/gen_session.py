"""
Одноразовый генератор StringSession для Telethon.
Запускать интерактивно — спросит телефон, код и (если включён) 2FA-пароль.

    pip install "telethon>=1.36,<2" "python-socks[asyncio]>=2.5"
    python gen_session.py

ПРОКСИ (важно на инфре без прямого egress):
  Если запускаешь с машины, где Telegram доступен ТОЛЬКО через прокси,
  выставь перед запуском переменные окружения:
    export PROXY_HOST=proxy.cloud4w.com PROXY_PORT=8787 PROXY_TYPE=http
    export PROXY_USER=... PROXY_PASS=...
  Если запускаешь с обычного интернета (ноутбук) — прокси не нужен, ничего
  не выставляй, коннект пойдёт напрямую.

api_id / api_hash берутся на https://my.telegram.org (код входа придёт
сообщением внутри Telegram).

Результат — строка SESSION_STRING. Это ПОЛНЫЙ доступ к аккаунту: не коммить,
не пересылай в чат, клади только в env Dokploy как секрет.
"""

import os
import asyncio
import python_socks
from telethon import TelegramClient
from telethon.sessions import StringSession


def build_proxy():
    host = os.environ.get("PROXY_HOST", "").strip()
    if not host:
        return None
    type_map = {
        "http": python_socks.ProxyType.HTTP,
        "socks5": python_socks.ProxyType.SOCKS5,
        "socks4": python_socks.ProxyType.SOCKS4,
    }
    ptype = type_map.get(os.environ.get("PROXY_TYPE", "http").lower(),
                         python_socks.ProxyType.HTTP)
    return (
        ptype,
        host,
        int(os.environ.get("PROXY_PORT", "8787")),
        True,
        os.environ.get("PROXY_USER") or None,
        os.environ.get("PROXY_PASS") or None,
    )


api_id = int(input("api_id: ").strip())
api_hash = input("api_hash: ").strip()
proxy = build_proxy()
print("proxy:", "ON (" + os.environ.get("PROXY_HOST", "") + ")" if proxy else "OFF (прямой коннект)")


async def main():
    async with TelegramClient(StringSession(), api_id, api_hash, proxy=proxy) as client:
        me = await client.get_me()
        print("\nЗашли как:", me.first_name, "| @" + (me.username or "—"), "| id", me.id)
        print("\n=== SESSION_STRING (в Dokploy env, секрет) ===\n")
        print(client.session.save())
        print("\n=== держать в секрете ===")


asyncio.run(main())
