#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
blog-relay — локальный HTTP-релей для публикации в блог Bitrix.
Четвёртый сервис по образцу claude-bridge/cover-helper/md-helper: Flask на 172.17.0.1.

Зачем: n8n-контейнер ходит наружу через корпоративный HTTPS_PROXY, который отдаёт
502 CONNECT на хост блога. Адрес 172.17.0.1 — в NO_PROXY, поэтому n8n достучится
до релея напрямую, а релей форвардит POST на блог с хоста (тоже напрямую, мимо
прокси). Так обходим прокси без правки env n8n и без редеплоя.

Инкапсулирует специфику блога: TLS-игнор (серт просрочен), trailing slash,
Bearer-токен, обход прокси. n8n шлёт чистый payload — релей знает, как доставить.

Вход:  POST /publish  {"payload": {...тело для блог-вебхука...}}
Выход: ответ блога как есть (success/element_id/url или ошибка) + http-код блога.
"""
import os
import ssl
import json
import urllib.request
from flask import Flask, request, jsonify

app = Flask(__name__)

RELAY_TOKEN = os.environ.get("RELAY_TOKEN", "")
PORT = int(os.environ.get("RELAY_PORT", "8083"))
HOST = os.environ.get("RELAY_HOST", "172.17.0.1")

# Целевой блог (стенд). На бой — сменить BLOG_BASE/BLOG_TOKEN через env юнита.
BLOG_BASE = os.environ.get("BLOG_BASE", "https://skorokhodov.site.cloud4w.ru")
BLOG_TOKEN = os.environ.get("BLOG_TOKEN", "test_key")
BLOG_WEBHOOK = f"{BLOG_BASE}/api/blog/webhook/?token={BLOG_TOKEN}&config=settings"

# TLS блога просрочен → игнорируем проверку сертификата
_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE

# Обход корпоративного прокси — ходим напрямую (хост VM в whitelist фаервола блога)
_opener = urllib.request.build_opener(
    urllib.request.ProxyHandler({}),                 # пустой прокси = напрямую
    urllib.request.HTTPSHandler(context=_ssl_ctx),
)


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "target": BLOG_BASE})


@app.route("/publish", methods=["POST"])
def publish():
    token = request.headers.get("X-Relay-Token", "")
    if RELAY_TOKEN and token != RELAY_TOKEN:
        return jsonify({"success": False, "error": "unauthorized"}), 401

    data = request.get_json(force=True, silent=True) or {}
    payload = data.get("payload")
    if payload is None:
        return jsonify({"success": False, "error": "payload is required"}), 400

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        BLOG_WEBHOOK,
        method="POST",
        data=body,
        headers={
            "Authorization": f"Bearer {BLOG_TOKEN}",
            "Content-Type": "application/json",
        },
    )
    try:
        resp = _opener.open(req, timeout=120)
        raw = resp.read().decode("utf-8", errors="replace")
        code = resp.getcode()
    except urllib.error.HTTPError as e:
        # блог вернул ошибку (400/500) — пробрасываем тело и код как есть
        raw = e.read().decode("utf-8", errors="replace")
        code = e.code
    except Exception as e:
        return jsonify({"success": False, "error": f"relay failed: {e}"}), 502

    # пробрасываем ответ блога дословно (JSON если распарсится, иначе как текст)
    try:
        parsed = json.loads(raw)
        return jsonify(parsed), code
    except Exception:
        return jsonify({"success": False, "error": "non-json blog response",
                        "raw": raw[:500], "blog_http": code}), code


if __name__ == "__main__":
    app.run(host=HOST, port=PORT)
