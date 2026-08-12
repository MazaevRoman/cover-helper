#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
md-helper — локальный HTTP-сервис конвертации markdown -> семантический HTML для блога.
Аналог claude-bridge / cover-helper: Flask на 172.17.0.1, токен из env, дёргается из n8n.

Портирует фирменную логику styleCloud4yHtml из md-editor (Toast UI):
  - срез мета-блока по маркеру «ТЕКСТ СТАТЬИ»
  - удаление первого H1 (заголовок идёт в HEADER_ru/NAME вебхука отдельно)
  - разворачивание <li><p>..</p></li> -> <li>..</li>
  - фирменный инлайн-стиль таблиц (тёмный #334155 заголовок)
  - нормализация language-класса на <code>
  - чистка пустых <p>

Вход: markdown из поля «Текст статьи» NocoDB. Выход: HTML для TEXT_ru вебхука.
"""
import os
import re
from flask import Flask, request, jsonify
import markdown
from bs4 import BeautifulSoup, NavigableString, Tag

app = Flask(__name__)

# --- Конфигурация (из env, как у bridge/cover) ---
MD_TOKEN = os.environ.get("MD_TOKEN", "")
PORT = int(os.environ.get("MD_PORT", "8082"))
HOST = os.environ.get("MD_HOST", "172.17.0.1")

# --- Фирменные стили таблиц — дословно из styleCloud4yHtml ---
TABLE_STYLE = ("width:100%; border-collapse:collapse; border:1px solid #000000; "
               "font-family:system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif; "
               "font-size:0.95rem; background:white; margin:1.5rem 0;")
TH_STYLE = ("border:1px solid #000000; background:#334155; color:white; "
            "font-weight:600; padding:12px 8px; text-align:left;")
TD_STYLE = "border:1px solid #000000; padding:12px 8px; vertical-align:top;"

MARKER_RE = re.compile(r'ТЕКСТ\s*СТАТЬИ', re.I)

# extensions под наш набор конструкций (H1-H3, списки, GFM-таблицы,
# fenced-код, инлайн-код, жирный, ссылки).
# ПРИМЕЧАНИЕ: sane_lists НЕ используем — он ломает распознавание вложенных
# списков в комбинации с нашими отступами. Вложенность обеспечивает
# normalize_list_indent (2-проб. уровни -> 4-проб.) + базовый парсер.
MD_EXTENSIONS = ['fenced_code', 'tables', 'nl2br']


def normalize_list_indent(md_text):
    """python-markdown требует 4 пробела на уровень вложенности списка.
    Claude мог сгенерить с 2 пробелами — приводим кратные-2 отступы к кратным-4."""
    out = []
    for line in md_text.split('\n'):
        m = re.match(r'^( +)([-*+]|\d+\.)\s', line)
        if m:
            spaces = len(m.group(1))
            level = spaces // 2
            out.append(' ' * (level * 4) + line[spaces:])
        else:
            out.append(line)
    return '\n'.join(out)


def strip_meta(md_text):
    """Отрезать мета-блок ДО маркера «ТЕКСТ СТАТЬИ» включительно (как в WF2)."""
    if not MARKER_RE.search(md_text):
        return md_text
    parts = MARKER_RE.split(md_text, maxsplit=1)
    body = parts[1] if len(parts) > 1 else md_text
    # убрать хвост строки маркера (═══ и перевод строки)
    body = re.sub(r'^[^\n]*\n', '', body, count=1)
    return body.lstrip('\n')


def style_html(html):
    """Портирование styleCloud4yHtml через BeautifulSoup(lxml)."""
    soup = BeautifulSoup(html, 'lxml')
    body = soup.body if soup.body else soup

    # 0. чистка пустых <p> и <p><br></p>
    for p in body.find_all('p'):
        inner = (p.decode_contents() or '').replace('&nbsp;', '').strip()
        if inner == '' or re.fullmatch(r'(<br\s*/?>)+', inner, re.I):
            p.decompose()

    # 0b. убрать первый h1 (заголовок ставится в Битриксе отдельно)
    first_h1 = body.find('h1')
    if first_h1:
        first_h1.decompose()

    # 0c. развернуть <li><p>..</p></li> -> <li>..</li>
    for li in body.find_all('li'):
        child_tags = [c for c in li.children if isinstance(c, Tag)]
        if len(child_tags) == 1 and child_tags[0].name == 'p':
            child_tags[0].unwrap()
        else:
            ps = li.find_all('p', recursive=False)
            for idx, p in enumerate(ps):
                if idx > 0:
                    p.insert_before(NavigableString(' '))
                p.unwrap()

    # 1. таблицы: фирменный инлайн-стиль
    for table in body.find_all('table'):
        table['style'] = TABLE_STYLE
        if table.has_attr('class'):
            del table['class']
        for th in table.find_all('th'):
            th['style'] = TH_STYLE
            if th.has_attr('class'):
                del th['class']
        for td in table.find_all('td'):
            td['style'] = TD_STYLE
            if td.has_attr('class'):
                del td['class']

    # 2. блоки кода: language-класс на <code>
    for code in body.find_all('code'):
        pre = code.parent
        if pre and getattr(pre, 'name', None) == 'pre' and pre.has_attr('class'):
            cls = ' '.join(pre['class'])
            m = re.search(r'language-[\w-]+', cls)
            if m:
                existing = ' '.join(code.get('class', []))
                if 'language-' not in existing:
                    code['class'] = code.get('class', []) + [m.group(0)]
                del pre['class']
        if code.has_attr('data-language'):
            del code['data-language']
        if pre and getattr(pre, 'name', None) == 'pre' and pre.has_attr('data-language'):
            del pre['data-language']

    # 3. чистка мусора Toast UI (у python-markdown его нет, но для полноты)
    for el in body.find_all(attrs={'contenteditable': True}):
        del el['contenteditable']
    for el in body.find_all(attrs={'data-nodeid': True}):
        del el['data-nodeid']

    return ''.join(str(c) for c in body.children).strip()


def convert(md_text):
    body_md = strip_meta(md_text)
    body_md = normalize_list_indent(body_md)
    raw_html = markdown.markdown(body_md, extensions=MD_EXTENSIONS)
    return style_html(raw_html)


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "markdown": markdown.__version__})


@app.route("/md2html", methods=["POST"])
def md2html():
    token = request.headers.get("X-Md-Token", "")
    if MD_TOKEN and token != MD_TOKEN:
        return jsonify({"success": False, "error": "unauthorized"}), 401

    data = request.get_json(force=True, silent=True) or {}
    md_text = data.get("markdown", "")
    if not md_text:
        return jsonify({"success": False, "error": "markdown is required"}), 400

    try:
        html = convert(md_text)
        return jsonify({"success": True, "html": html})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


if __name__ == "__main__":
    app.run(host=HOST, port=PORT)
