"""Демо-режим для админа: три анкеты, которые умеют отвечать сами.

Нужен, чтобы тестировать полный цикл (лента → мэтч → Ледокол → чат) в одиночку,
пока в боте нет живых людей. В продакшене просто не вызывай /demo.
"""
from __future__ import annotations

import asyncio
import random

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.types import Message

import db
from handlers.admin import is_admin
from texts import QUEST_QUESTIONS

router = Router(name="demo")

DEMO_IDS = [-101, -102, -103]

DEMO_PROFILES = [
    {
        "id": -101,
        "name": "Аня",
        "age": 26,
        "gender": "f",
        "answers": {
            "friday": "Концерт или выставка",
            "value": "Ум и любопытство",
            "mess": "5 из 10 — творческий хаос",
            "owl": "Сова — живу ночью",
            "first": "Всегда на мне",
            "love": "Приключение",
        },
        "interests": ["музыка", "кино", "искусство", "путешествия", "фотография"],
        "photo": "https://picsum.photos/seed/himiya-anya/700/900",
        "voice": None,
    },
    {
        "id": -102,
        "name": "Марк",
        "age": 28,
        "gender": "m",
        "answers": {
            "friday": "Бар с друзьями",
            "value": "Чувство юмора",
            "mess": "5 из 10 — творческий хаос",
            "owl": "Сова — живу ночью",
            "first": "Всегда на мне",
            "love": "Команда",
        },
        "interests": ["музыка", "кино", "путешествия", "фотография", "спорт"],
        "photo": "https://picsum.photos/seed/himiya-mark/700/900",
        "voice": None,
    },
    {
        "id": -103,
        "name": "Лиза",
        "age": 31,
        "gender": "f",
        "answers": {
            "friday": "Сериал и доставка",
            "value": "Надёжность",
            "mess": "1 из 10 — всё по местам",
            "owl": "Жаворонок — утро моё",
            "first": "50/50, но без «привет»",
            "love": "Спокойствие",
        },
        "interests": ["книги", "кулинария", "йога", "психология", "кино"],
        "photo": "https://picsum.photos/seed/himiya-liza/700/900",
        "voice": None,
    },
]

DEMO_REPLIES = [
    "О, это уже интересно 🙂 А ты сам как обычно проводишь пятницу?",
    "Слушай, а мне понравилось, как ты ответил в анкете — не по шаблону.",
    "Предлагаю проверить химию вживую: кофе на выходных?",
    "Кстати, я тоже это читал(а). Совпадение или знак? 😏",
    "Ты первый человек из этого бота, кто отвечает нормально. Продолжай.",
]


async def create_demo(bot: Bot, admin_id: int) -> list[str]:
    """Создаёт демо-анкеты под то, кого ищет админ, и «лайкает» его от их имени."""
    import json

    admin = await db.get_user(admin_id)
    if not admin:
        return []
    city = admin.get("city") or "Лондон"
    seek = admin.get("seek") or "any"
    genders = ["f", "m"] if seek == "any" else [seek]

    created: list[str] = []
    for i, profile in enumerate(DEMO_PROFILES):
        gender = genders[i % len(genders)]
        await db.execute(
            """INSERT OR REPLACE INTO users
               (id, username, name, age, city, gender, seek, photo_id, answers, interests,
                verified, created_at, last_active)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                profile["id"], f"demo{i}", profile["name"], profile["age"], city, gender,
                "f" if gender == "m" else "m",
                profile["photo"],
                json.dumps(profile["answers"], ensure_ascii=False),
                json.dumps(profile["interests"], ensure_ascii=False),
                1, db.iso(db.utcnow()), db.iso(db.utcnow()),
            ),
        )
        await db.execute(
            "INSERT OR IGNORE INTO likes (from_id, to_id, created_at) VALUES (?, ?, ?)",
            (profile["id"], admin_id, db.iso(db.utcnow())),
        )
        created.append(f"{profile['name']}, {profile['age']}")
    return created


async def remove_demo() -> None:
    for demo_id in DEMO_IDS:
        await db.execute("DELETE FROM users WHERE id = ?", (demo_id,))
        await db.execute("DELETE FROM likes WHERE from_id = ? OR to_id = ?", (demo_id, demo_id))


async def auto_answer(bot: Bot, match_id: int, partner_id: int, idx: int) -> None:
    """Демо-собеседник отвечает на вопрос Ледокола вместо живого человека."""
    if partner_id not in DEMO_IDS or idx >= len(QUEST_QUESTIONS):
        return
    if await db.quest_answer(match_id, partner_id, idx):
        return
    options = QUEST_QUESTIONS[idx]["options"]
    await db.save_quest_answer(match_id, partner_id, idx, random.choice(options))


async def auto_reply(bot: Bot, match: dict, demo_id: int, human_id: int) -> None:
    """Демо-собеседник отвечает в чате, чтобы можно было проверить диалог."""
    if demo_id not in DEMO_IDS:
        return
    await asyncio.sleep(random.uniform(1.5, 3.5))
    demo = await db.get_user(demo_id)
    try:
        from handlers.chat import _reply_kb

        sent = await bot.send_message(
            human_id,
            f"💬 <b>{demo['name']}</b>\n{random.choice(DEMO_REPLIES)}",
            reply_markup=_reply_kb(match["id"]),
        )
        await db.save_message(match["id"], demo_id, human_id, sent.message_id)
        await db.touch_match(match["id"])
    except Exception:
        pass


# ───────────────────────────── команды ─────────────────────────────
@router.message(Command("demo"))
async def cmd_demo(message: Message) -> None:
    if not await is_admin(message.from_user.id):
        return
    created = await create_demo(message.bot, message.from_user.id)
    if not created:
        await message.answer("Сначала заполни свою анкету — демо подстраивается под твой город.")
        return
    await message.answer(
        "🧪 <b>Демо-анкеты готовы</b>\n\n"
        + "\n".join("• " + name for name in created)
        + "\n\nОни уже «лайкнули» тебя: жми «🔍 Искать» → ❤️ → сразу получишь мэтч, "
        "пройдёшь Ледокол и сможешь переписываться. Отвечают сами 🙂\n\n"
        "Убрать: /demo_off"
    )


@router.message(Command("demo_off"))
async def cmd_demo_off(message: Message) -> None:
    if not await is_admin(message.from_user.id):
        return
    await remove_demo()
    await message.answer("🧹 Демо-анкеты удалены.")
