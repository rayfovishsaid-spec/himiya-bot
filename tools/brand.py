"""Брендинг бота через Bot API: имя, описания, команды, кнопка меню.

Запуск:  BOT_TOKEN=... python tools/brand.py
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request

TOKEN = os.getenv("BOT_TOKEN", "")

SHORT = "Знакомства, где сначала смысл, а потом фото 🧪"

DESCRIPTION = (
    "Химия — знакомства без «привет, как дела» в пустоту.\n\n"
    "• Анкета — 5 честных вопросов и голосовое\n"
    "• Фото скрыто, пока не случился мэтч\n"
    "• После мэтча — «Ледокол»: 5 вопросов, и только потом контакты\n"
    "• Мэтч сгорает за 48 часов тишины\n"
    "• Лента по твоим темам — чтобы всегда было о чём говорить\n\n"
    "18+. Жми «Запустить» и заполни анкету — это минута."
)

COMMANDS = [
    {"command": "start", "description": "Анкета / меню"},
    {"command": "news", "description": "📰 Лента по моим темам"},
    {"command": "topics", "description": "⚙️ Настроить темы"},
    {"command": "saved", "description": "🔖 Закладки"},
    {"command": "profile", "description": "🧪 Моя анкета"},
    {"command": "fill", "description": "Дозаполнить анкету"},
    {"command": "stop", "description": "Выйти из чата"},
    {"command": "report", "description": "🚩 Пожаловаться"},
    {"command": "help", "description": "Как всё устроено"},
]


def api(method: str, **params):
    url = f"https://api.telegram.org/bot{TOKEN}/{method}"
    data = json.dumps(params).encode() if params else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return json.loads(exc.read())


def main() -> None:
    if not TOKEN:
        print("Нет BOT_TOKEN", file=sys.stderr)
        raise SystemExit(1)

    steps = [
        ("setMyName", {"name": "Химия · знакомства"}),
        ("setMyShortDescription", {"short_description": SHORT}),
        ("setMyDescription", {"description": DESCRIPTION}),
        ("setMyCommands", {"commands": COMMANDS}),
        ("setChatMenuButton", {"menu_button": {"type": "commands"}}),
    ]
    for method, params in steps:
        result = api(method, **params)
        mark = "✅" if result.get("ok") else "❌"
        print(f"{mark} {method}: {result.get('ok') or result.get('description')}")

    me = api("getMe").get("result", {})
    print(f"\n@{me.get('username')} — {me.get('first_name')}")
    print("Аватар Bot API менять не умеет: загрузи assets/logo.png через @BotFather → /setuserpic")


if __name__ == "__main__":
    main()
