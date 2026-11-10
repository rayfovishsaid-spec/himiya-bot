"""Генерирует preview_design.html — как реальные сообщения бота выглядят в Telegram.

Запуск:  python tools/preview.py
Тексты берутся из боевого кода (texts.py, matchmaking.py), а не пишутся руками.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import texts  # noqa: E402
from services import matchmaking as mm  # noqa: E402
from texts import QUEST_QUESTIONS  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "preview_design.html")

MARK = {
    "id": 2, "name": "Марк", "age": 28, "city": "Лондон", "verified": 1, "voice_id": "v",
    "answers": json.dumps({
        "friday": "Бар с друзьями", "value": "Чувство юмора",
        "mess": "5 из 10 — творческий хаос", "owl": "Сова — живу ночью",
        "first": "Всегда на мне", "love": "Команда",
    }),
    "interests": json.dumps(["музыка", "кино", "путешествия", "фотография", "спорт"]),
}
ME = {
    "id": 1, "name": "Аня", "age": 26, "city": "Лондон", "verified": 0, "voice_id": "v",
    "answers": json.dumps({
        "friday": "Бар с друзьями", "value": "Ум и любопытство",
        "mess": "5 из 10 — творческий хаос", "owl": "Сова — живу ночью",
        "first": "Всегда на мне", "love": "Приключение",
    }),
    "interests": json.dumps(["музыка", "кино", "искусство", "путешествия"]),
}

QUEST_Q = (
    f"🧊 <b>Вопрос 1 из 5</b>\n\n{QUEST_QUESTIONS[0]['q']}"
)
QUEST_REVEAL = texts.QUEST_REVEAL_HEADER.format(n=1, q=QUEST_QUESTIONS[0]["q"]) + texts.QUEST_REVEAL.format(
    a_name="Аня", a=QUEST_QUESTIONS[0]["options"][1],
    b_name="Марк", b=QUEST_QUESTIONS[0]["options"][1],
    verdict=texts.VERDICT_SAME,
)

NEWS = (
    "🎬 <b>Полуночные показы возвращаются в кинотеатры Лондона</b>\n"
    "<i>Evening Standard · 3 ч назад</i>\n"
    "<blockquote>Независимые кинотеатры Soho и Peckham возрождают сеансы в полночь: "
    "билеты раскупают за сутки, а половина зала — люди 25–35 лет.</blockquote>\n\n"
    "https://www.standard.co.uk/culture/film"
)
SHARED = (
    "💌 <b>Аня</b> поделилась:\n\n"
    "🎬 <b>Полуночные показы возвращаются в кинотеатры Лондона</b>\n"
    "<i>Evening Standard · 3 ч назад</i>\n"
    "<blockquote>Независимые кинотеатры Soho и Peckham возрождают сеансы в полночь.</blockquote>"
)

SECTIONS = [
    ("1. Первый экран", "Что видит человек по /start — до анкеты.", [
        ("bot", texts.START, []),
        ("bot", "Как тебя зовут? (имя или ник — как хочешь, чтобы видели другие)", []),
    ]),
    ("2. Анкета: 5 вопросов", "Кнопки вместо ввода — заполняется за минуту.", [
        ("bot", "<b>Анкета: вопрос 1 из 5</b>\n\nИдеальная пятница — это…",
         ["Бар с друзьями", "Сериал и доставка", "Концерт или выставка", "Спонтанная поездка"]),
        ("bot", texts.ASK_PHOTO, []),
        ("bot", texts.ASK_VOICE, []),
    ]),
    ("3. Карточка в ленте", "Фото скрыто. Химия считается по ответам и интересам.", [
        ("bot", mm.card_caption(MARK, ME),
         ["❤️ Хочу познакомиться  ·  ➖ Дальше", "👀 Подглядеть фото — 1 ⭐", "🎙 Голос  ·  🚩 Жалоба"]),
    ]),
    ("4. Мэтч и Ледокол", "Взаимный лайк ≠ чат. Сначала 5 вопросов.", [
        ("bot", texts.MATCH_FOUND, []),
        ("bot", QUEST_Q, ["Море и лежак", "Горы и рюкзак", "Город и музеи", "Дом и никто не звонит"]),
        ("me", "Горы и рюкзак", []),
        ("bot", texts.QUEST_ANSWERED_WAIT, []),
        ("bot", QUEST_REVEAL, []),
    ]),
    ("5. Разблокировка", "Контакты и чат — после квеста.", [
        ("bot", texts.MATCH_UNLOCKED.format(hours=48), ["🔗 Открыть профиль в Telegram", "💬 Писать здесь, анонимно"]),
        ("photo", "📸 Вот и фото: <b>Марк</b>, 28", []),
    ]),
    ("6. Анонимный чат", "Сообщения идут через бота, контакты не раскрываются.", [
        ("bot", texts.CHAT_ENTER.format(name="Марк"), ["🚪 Выйти из чата  ·  🚩 Жалоба"]),
        ("me", "привет! видел, ты тоже выбрала «горы и рюкзак»", []),
        ("bot", "💬 <b>Марк</b>\nАга 🙂 А ты где-нибудь была в походе, или это мечта?", ["↩️ Ответить"]),
    ]),
    ("7. Лента", "Контент по темам из анкеты. Главная кнопка — «поделиться», а не «открыть».", [
        ("bot", NEWS, ["📖 Открыть статью", "💌 Поделиться с мэтчем", "🔖 В закладки  ·  ➖ Дальше",
                      "⚙️ Мои темы  ·  🚩 Жалоба"]),
        ("bot", texts.QUEST_ANSWERED_WAIT.replace("Ответ принят.", "Отправлено Марку.").replace(
            "Ждём вторую сторону — как ответит, покажу оба ответа.", "Как отреагирует — увидишь здесь."), []),
        ("bot", SHARED, ["🔥 Класс  ·  🤔 Спорно", "💬 Обсудить  ·  ↩️ Ответить"]),
        ("bot", "💬 <b>Марк</b>: 🔥 Класс\n<i>на «Полуночные показы возвращаются в кинотеатры Лондона»</i>", []),
    ]),
    ("8. Главное меню", "Reply-клавиатура — всегда под рукой.", [
        ("bot", "С возвращением, <b>Аня</b> 🧪\n\nЧто делаем? Смотри ленту или проверь мэтчи.",
         None),
    ]),
]

MENU_BUTTONS = [
    ["🔍 Искать", "💬 Мои мэтчи"],
    ["📰 Лента", "☕ Дайджест"],
    ["🔖 Закладки", "👤 Анкета"],
    ["💘 Кто меня лайкнул"],
]


def bubble(kind: str, text: str, buttons) -> str:
    if kind == "me":
        return f'<div class="b me">{text}</div>'
    if kind == "photo":
        return f'<div class="b bot">{text}<div class="ph">фото</div></div>'
    kb = ""
    if buttons:
        rows = "".join(
            f'<div class="kbrow">' + "".join(f'<span class="kbtn">{b}</span>' for b in row.split("  ·  ")) + "</div>"
            for row in buttons
        )
        kb = f'<div class="kb">{rows}</div>'
    return f'<div class="b bot">{text}</div>{kb}'


def render() -> str:
    out = []
    for title, note, items in SECTIONS:
        out.append(f'<section><h3>{title}</h3><p class="note">{note}</p><div class="phone">')
        for kind, text, buttons in items:
            out.append(bubble(kind, text, buttons))
        if title.startswith("8."):
            rows = "".join(
                '<div class="kbrow">' + "".join(f'<span class="rbtn">{b}</span>' for b in row) + "</div>"
                for row in MENU_BUTTONS
            )
            out.append(f'<div class="replykb">{rows}</div>')
        out.append("</div></section>")
    return "\n".join(out)


HTML = f"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Химия — как выглядит бот в Telegram</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; padding: 32px 20px 64px; background: radial-gradient(1000px 500px at 30% -10%, #2b1b4d, #0c0a14 60%, #07060d);
         color: #f2eefb; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }}
  .head {{ max-width: 1180px; margin: 0 auto 28px; }}
  h1 {{ font-size: 27px; margin: 0 0 8px; letter-spacing: -.4px; }}
  h1 span {{ background: linear-gradient(135deg, #c084fc, #f472b6); -webkit-background-clip: text; background-clip: text; color: transparent; }}
  .lead {{ color: #a99fc9; font-size: 14px; line-height: 1.6; max-width: 760px; margin: 0; }}
  .grid {{ max-width: 1180px; margin: 0 auto; display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 22px; align-items: start; }}
  section {{ }}
  h3 {{ font-size: 13px; text-transform: uppercase; letter-spacing: 1.2px; color: #a855f7; margin: 0 0 4px; }}
  .note {{ font-size: 12px; color: #8b7bb5; margin: 0 0 10px; line-height: 1.45; min-height: 30px; }}
  .phone {{ background: #12101f; border: 1px solid rgba(168,85,247,.28); border-radius: 22px; padding: 14px 11px;
            display: flex; flex-direction: column; gap: 7px; box-shadow: 0 22px 60px rgba(0,0,0,.5); }}
  .b {{ max-width: 92%; padding: 9px 12px; border-radius: 14px; font-size: 13px; line-height: 1.5; white-space: pre-wrap; word-wrap: break-word; }}
  .b.bot {{ align-self: flex-start; background: #1d1932; border: 1px solid rgba(168,85,247,.14); border-bottom-left-radius: 5px; }}
  .b.me  {{ align-self: flex-end; background: linear-gradient(135deg, #7c3aed, #db2777); border-bottom-right-radius: 5px; }}
  .b blockquote {{ border-left: 3px solid rgba(168,85,247,.55); margin: 7px 0 0; padding: 2px 0 2px 9px; color: #c9bce8; }}
  .b b {{ color: #fff; }}
  .b i {{ color: #a394cf; }}
  .ph {{ margin-top: 8px; height: 110px; border-radius: 10px; display: grid; place-items: center;
         background: linear-gradient(135deg, #6d28d9, #be185d); color: #fff; font-size: 12px; }}
  .kb {{ align-self: stretch; display: flex; flex-direction: column; gap: 5px; margin-top: 1px; }}
  .kbrow {{ display: flex; gap: 5px; flex-wrap: wrap; }}
  .kbtn {{ flex: 1; min-width: 45%; text-align: center; background: rgba(168,85,247,.13);
           border: 1px solid rgba(168,85,247,.38); color: #e9dcff; border-radius: 9px; padding: 8px 9px; font-size: 12px; }}
  .replykb {{ margin-top: 10px; display: flex; flex-direction: column; gap: 5px; }}
  .rbtn {{ background: #221c38; border: 1px solid rgba(168,85,247,.25); color: #ded4f5; border-radius: 8px;
           padding: 9px 10px; font-size: 12.5px; text-align: center; flex: 1; }}
  .replykb .kbrow {{ display: flex; }}
  footer {{ max-width: 1180px; margin: 34px auto 0; color: #7c6ea3; font-size: 12px; line-height: 1.6; }}
</style></head><body>
<div class="head">
  <h1>🧪 <span>Химия</span> — как это выглядит в Telegram</h1>
  <p class="lead">Это не макет: тексты, карточки и кнопки сгенерированы напрямую из боевого кода
  (<code>texts.py</code>, <code>services/matchmaking.py</code>). Именно так бот отвечает в
  <b>@chemistry7LOVE_bot</b>. Единственное, что нельзя задать через Bot API — фон и градиенты в пузырях:
  их рисует сам клиент Telegram.</p>
</div>
<div class="grid">
{render()}
</div>
<footer>Сгенерировано <code>tools/preview.py</code> · Telegram-разметка: HTML (b, i, blockquote, code) + inline-кнопки.
Bot API не управляет шрифтами, цветом пузырей и аватаром — аватар загружается через @BotFather.</footer>
</body></html>
"""


def main() -> None:
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(HTML)
    print("Готово:", OUT)


if __name__ == "__main__":
    main()
