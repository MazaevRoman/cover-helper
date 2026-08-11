#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cover-helper — локальный HTTP-сервис генерации обложек статей блога.
Аналог claude-bridge: Flask на 172.17.0.1, токен из env, дёргается из n8n HTTP-нодой.

Рисует обложку 1200x768 (Pillow): фон (цветной градиент ИЛИ сплошной серый,
чередование задаёт вызывающий через variant) + заголовок статьи белым DIN Pro Bold
с типографским переносом. Возвращает PNG в base64 — прямо в images[{type:"preview"}]
вебхука блога.

Параметры макета сняты из фирменных psd-шаблонов (Шаблон_Обложки_статьи_*).
"""
import os
import io
import base64
from flask import Flask, request, jsonify
from PIL import Image, ImageDraw, ImageFont

app = Flask(__name__)

# --- Конфигурация (из env, как у bridge) ---
COVER_TOKEN = os.environ.get("COVER_TOKEN", "")
FONT_PATH = os.environ.get(
    "COVER_FONT",
    "/home/cloud4u/work/marketing-automation/assets/dinpro_bold.otf",
)
PORT = int(os.environ.get("COVER_PORT", "8081"))
HOST = os.environ.get("COVER_HOST", "172.17.0.1")

# --- Точные параметры макета (из psd) ---
W, H = 1200, 768
TEXT_COLOR = (255, 255, 255)
# Цветной градиент, диагональ TL->BR (снято с композита цветного шаблона)
COLOR_STOPS = [
    (0.00, (0x89, 0x33, 0x7B)),   # магента
    (0.30, (0x80, 0x3A, 0x80)),
    (0.50, (0x67, 0x4E, 0x8D)),   # фиолетовый
    (0.72, (0x51, 0x60, 0x99)),
    (1.00, (0x3E, 0x6E, 0xA3)),   # синий
]
GRAY = (0x69, 0x6E, 0x7B)         # сплошной серый (серый шаблон)

# --- Типографика ---
MARGIN_X = 92                     # левый=правый отступ (из psd)
TEXT_W = W - 2 * MARGIN_X         # рабочая ширина текста, ~1016px
BASE_SIZE = 60                    # кегль из psd
MIN_SIZE = 40                     # ниже не опускаемся
LINE_SPACING = 1.2
ZONE_H = 340                      # высота зоны под текст (для автокегля)
MAX_LINES = 4

# Короткие слова, которые нельзя оставлять последними в строке (висячие)
HANG = {
    'в', 'во', 'на', 'и', 'с', 'со', 'для', 'по', 'из', 'к', 'ко', 'от', 'у',
    'о', 'об', 'а', 'но', 'за', 'до', 'при', 'под', 'над', 'без', 'что', 'как',
    'это', 'не', 'ни', 'же', 'бы', 'ли', 'я', 'же', 'или',
}


def _lerp(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _grad_at(t, stops):
    for i in range(len(stops) - 1):
        t0, c0 = stops[i]
        t1, c1 = stops[i + 1]
        if t0 <= t <= t1:
            return _lerp(c0, c1, (t - t0) / (t1 - t0) if t1 > t0 else 0)
    return stops[-1][1]


def _make_bg(variant):
    if variant == "gray":
        return Image.new("RGB", (W, H), GRAY)
    img = Image.new("RGB", (W, H))
    px = img.load()
    for y in range(H):
        for x in range(W):
            px[x, y] = _grad_at((x / W + y / H) / 2, COLOR_STOPS)
    return img


def _wrap(text, font, draw, max_w):
    """Перенос по фактической ширине + приклейка висячих предлогов к следующему слову."""
    words = text.split()
    tokens = []
    i = 0
    while i < len(words):
        w = words[i]
        if w.lower() in HANG and i + 1 < len(words):
            tokens.append(w + "\u00A0" + words[i + 1])
            i += 2
        else:
            tokens.append(w)
            i += 1
    lines, cur = [], ""
    for tok in tokens:
        trial = (cur + " " + tok).strip()
        if draw.textlength(trial.replace("\u00A0", " "), font=font) <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = tok
    if cur:
        lines.append(cur)
    return [l.replace("\u00A0", " ") for l in lines]


def _fit(text, draw):
    """Подбор кегля: уменьшаем, пока текст не влезет по ширине и высоте."""
    for size in range(BASE_SIZE, MIN_SIZE - 1, -2):
        font = ImageFont.truetype(FONT_PATH, size)
        lines = _wrap(text, font, draw, TEXT_W)
        fits_w = all(draw.textlength(l, font=font) <= TEXT_W for l in lines)
        total_h = size * LINE_SPACING * len(lines)
        if fits_w and total_h <= ZONE_H and len(lines) <= MAX_LINES:
            return font, lines, size
    font = ImageFont.truetype(FONT_PATH, MIN_SIZE)
    return font, _wrap(text, font, draw, TEXT_W), MIN_SIZE


def render_cover(title, variant):
    img = _make_bg(variant)
    d = ImageDraw.Draw(img)
    font, lines, size = _fit(title, d)
    line_h = size * LINE_SPACING
    total_h = line_h * len(lines)
    y = (H - total_h) / 2  # вертикальное центрирование блока
    for line in lines:
        d.text((MARGIN_X, y), line, font=font, fill=TEXT_COLOR)
        y += line_h
    return img


@app.route("/health", methods=["GET"])
def health():
    ok_font = os.path.exists(FONT_PATH)
    return jsonify({"status": "ok", "font_present": ok_font, "font_path": FONT_PATH})


@app.route("/cover", methods=["POST"])
def cover():
    # авторизация как у bridge — по заголовку
    token = request.headers.get("X-Cover-Token", "")
    if COVER_TOKEN and token != COVER_TOKEN:
        return jsonify({"success": False, "error": "unauthorized"}), 401

    data = request.get_json(force=True, silent=True) or {}
    title = (data.get("title") or "").strip()
    if not title:
        return jsonify({"success": False, "error": "title is required"}), 400

    # variant: 'colored' | 'gray'. Чередование считает ВЫЗЫВАЮЩИЙ (WF3, по чётности Id).
    variant = data.get("variant", "colored")
    if variant not in ("colored", "gray"):
        variant = "colored"

    if not os.path.exists(FONT_PATH):
        return jsonify({"success": False, "error": f"font not found: {FONT_PATH}"}), 500

    try:
        img = render_cover(title, variant)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return jsonify({
            "success": True,
            "png_base64": b64,
            "variant": variant,
            "width": W,
            "height": H,
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


if __name__ == "__main__":
    # host 172.17.0.1 — docker0, чтобы n8n из контейнера дотянулся (как bridge)
    app.run(host=HOST, port=PORT)
