"""
Telethon userbot -> claude-bridge.

Минимальный безопасный скелет:
  - логинится по SESSION_STRING (env), тома не нужны;
  - в личке отвечает на сообщения (RESPOND_PRIVATE=1);
  - в группах отвечает только на упоминание/реплай (RESPOND_GROUP_ON_MENTION=1);
  - в broadcast-каналах молчит;
  - при старте пишет в лог, кем залогинился и достаёт ли claude-bridge
    (это и есть сетевая разведка — смотри логи контейнера в Dokploy).

Поведение сознательно узкое: это аккаунт-человек, авто-ответ всем подряд —
это и бан-риск, и «кому это он только что написал». Расширять, когда будет ТЗ.
"""

import os
import asyncio
import logging
import aiohttp
from telethon import TelegramClient, events
from telethon.sessions import StringSession

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("claude-bot")

API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
SESSION_STRING = os.environ["SESSION_STRING"]

BRIDGE_URL = os.environ.get("BRIDGE_URL", "http://172.17.0.1:8080/v1/generate")
BRIDGE_TOKEN = os.environ.get("BRIDGE_TOKEN", "")
BRIDGE_MODEL = os.environ.get("BRIDGE_MODEL", "opus")

RESPOND_PRIVATE = os.environ.get("RESPOND_PRIVATE", "1") == "1"
RESPOND_GROUP_ON_MENTION = os.environ.get("RESPOND_GROUP_ON_MENTION", "1") == "1"
TRIGGER_PREFIX = os.environ.get("TRIGGER_PREFIX", "")   # напр. "!ai " — требовать префикс
MAX_PROMPT = int(os.environ.get("MAX_PROMPT", "8000"))

client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)


async def ask_claude(prompt: str) -> str:
    headers = {"Content-Type": "application/json"}
    if BRIDGE_TOKEN:
        headers["X-Bridge-Token"] = BRIDGE_TOKEN
    payload = {"prompt": prompt, "model": BRIDGE_MODEL}
    timeout = aiohttp.ClientTimeout(total=120)
    async with aiohttp.ClientSession(timeout=timeout) as s:
        async with s.post(BRIDGE_URL, json=payload, headers=headers) as r:
            r.raise_for_status()
            data = await r.json()
            return (data.get("text") or "").strip()


@client.on(events.NewMessage(incoming=True))
async def handler(event):
    try:
        if event.out:
            return
        msg = (event.raw_text or "").strip()
        if not msg:
            return

        if event.is_private:
            if not RESPOND_PRIVATE:
                return
        elif event.is_group:
            if RESPOND_GROUP_ON_MENTION and not event.mentioned:
                return
        else:
            return   # broadcast-канал и прочее — молчим

        if TRIGGER_PREFIX:
            if not msg.startswith(TRIGGER_PREFIX):
                return
            msg = msg[len(TRIGGER_PREFIX):].strip()
            if not msg:
                return

        if len(msg) > MAX_PROMPT:
            msg = msg[:MAX_PROMPT]

        async with client.action(event.chat_id, "typing"):
            answer = await ask_claude(msg)

        await event.reply(answer or "(пустой ответ от Claude)")

    except Exception as e:
        log.exception("handler error: %s", e)


async def main():
    await client.connect()
    if not await client.is_user_authorized():
        log.error("SESSION_STRING невалиден/протух — перегенери через gen_session.py")
        return

    me = await client.get_me()
    log.info("Залогинен как %s (@%s) id=%s", me.first_name, me.username, me.id)

    try:
        probe = await ask_claude("ping — ответь одним словом: pong")
        log.info("claude-bridge OK, пример ответа: %r", probe[:80])
    except Exception as e:
        log.error("claude-bridge недоступен: %s", e)

    log.info("Бот запущен. PRIVATE=%s GROUP_ON_MENTION=%s PREFIX=%r",
             RESPOND_PRIVATE, RESPOND_GROUP_ON_MENTION, TRIGGER_PREFIX)
    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
