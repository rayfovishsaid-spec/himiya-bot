"""Админка: статистика, баны, рассылка."""
from __future__ import annotations

import asyncio

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import Message

import db
from config import ADMIN_IDS

router = Router(name="admin")


async def is_admin(uid: int) -> bool:
    if uid in ADMIN_IDS:
        return True
    user = await db.get_user(uid)
    return bool(user and user.get("is_admin"))


async def claim_first_admin(uid: int) -> bool:
    """Если ADMIN_IDS не задан и админа ещё нет — первый, кто нажал /start, становится им."""
    if ADMIN_IDS:
        return False
    existing = await db.fetchone("SELECT id FROM users WHERE is_admin = 1 LIMIT 1")
    if existing:
        return False
    await db.set_field(uid, "is_admin", 1) if "is_admin" in db.SETTABLE else await db.execute(
        "UPDATE users SET is_admin = 1 WHERE id = ?", (uid,)
    )
    return True


@router.message(Command("admin"))
async def cmd_admin(message: Message) -> None:
    if not await is_admin(message.from_user.id):
        return
    s = await db.stats()
    text = (
        "🧪 <b>Админка «Химия»</b>\n\n"
        f"👥 Всего: <b>{s['users']}</b>\n"
        f"✅ С анкетой: <b>{s['profiles']}</b>\n"
        f"❤️ Лайков: <b>{s['likes']}</b>\n"
        f"🔥 Мэтчей: <b>{s['matches']}</b>\n"
        f"💬 Открытых чатов: <b>{s['chats']}</b>\n"
        f"🚩 Жалоб: <b>{s['reports']}</b>\n"
        f"⛔ Забанено: <b>{s['banned']}</b>"
    )
    if s["profiles"]:
        conv = s["matches"] / s["profiles"] * 100
        text += f"\n\n📈 Мэтч-конверсия: <b>{conv:.1f}%</b>"
    await message.answer(text)


@router.message(Command("ping"))
async def cmd_ping(message: Message) -> None:
    """Диагностика: жив ли процесс, давно ли был heartbeat, что с базой."""
    if not await is_admin(message.from_user.id):
        return
    from datetime import datetime, timezone

    beat = await db.last_heartbeat()
    if beat:
        delta = (datetime.now(timezone.utc) - datetime.fromisoformat(beat)).seconds
        beat_line = f"💓 heartbeat: <b>{delta} с</b> назад"
    else:
        beat_line = "💓 heartbeat: нет данных"

    s = await db.stats()
    articles = await db.fetchone("SELECT COUNT(*) c FROM articles")
    await message.answer(
        "🏓 <b>Бот жив</b>\n\n"
        f"{beat_line}\n"
        f"👥 пользователей: {s['users']} · 📰 статей: {articles['c']}\n"
        f"🔥 мэтчей: {s['matches']} · 💬 чатов: {s['chats']}\n\n"
        f"<i>uptime процесса: с последнего рестарта. Если heartbeat старый — процесс заморожен.</i>"
    )


@router.message(Command("ban"))
async def cmd_ban(message: Message) -> None:
    if not await is_admin(message.from_user.id):
        return
    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[1].lstrip("-").isdigit():
        await message.answer("Использование: /ban <user_id> [причина]")
        return
    uid = int(parts[1])
    await db.set_field(uid, "is_banned", 1)
    for m in await db.user_matches(uid):
        await db.close_match(m["id"], "banned")
    await message.answer(f"⛔ {uid} забанен, мэтчи закрыты.")
    try:
        await message.bot.send_message(uid, "Твой аккаунт заблокирован за нарушение правил.")
    except Exception:
        pass


@router.message(Command("unban"))
async def cmd_unban(message: Message) -> None:
    if not await is_admin(message.from_user.id):
        return
    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[1].lstrip("-").isdigit():
        await message.answer("Использование: /unban <user_id>")
        return
    await db.set_field(int(parts[1]), "is_banned", 0)
    await message.answer("✅ Разбанен.")


@router.message(Command("verify"))
async def cmd_verify(message: Message) -> None:
    if not await is_admin(message.from_user.id):
        return
    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[1].lstrip("-").isdigit():
        await message.answer("Использование: /verify <user_id>")
        return
    uid = int(parts[1])
    await db.set_field(uid, "verified", 1)
    await message.answer(f"🛡 {uid} теперь верифицирован.")
    try:
        await message.bot.send_message(uid, "🛡 Верификация пройдена! Бейдж появился в анкете.")
    except Exception:
        pass


@router.message(Command("reports"))
async def cmd_reports(message: Message) -> None:
    if not await is_admin(message.from_user.id):
        return
    rows = await db.fetchall("SELECT * FROM reports ORDER BY created_at DESC LIMIT 20")
    if not rows:
        await message.answer("Жалоб нет 🎉")
        return
    lines = ["🚩 <b>Последние жалобы</b>"]
    for r in rows:
        lines.append(f"#{r['id']} {r['from_id']} → {r['to_id']}: {r['reason']}")
    await message.answer("\n".join(lines))


@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message, bot: Bot) -> None:
    if not await is_admin(message.from_user.id):
        return
    text = (message.text or "").partition(" ")[2].strip()
    if not text:
        await message.answer("Использование: /broadcast <текст>")
        return
    rows = await db.fetchall("SELECT id FROM users WHERE is_banned = 0")
    sent = failed = 0
    for row in rows:
        try:
            await bot.send_message(row["id"], text)
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)  # лимиты Telegram
    await message.answer(f"📣 Отправлено: {sent}, ошибок: {failed}")
