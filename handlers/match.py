"""Мэтчи и «Ледокол»: 5 вопросов, раскрытие ответов, разблокировка контактов."""
from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, Message

import db
from config import MATCH_TTL_HOURS
from utils import esc
from keyboards import after_unlock_kb, matches_kb, quest_kb
from texts import (
    MATCH_FOUND,
    MATCH_UNLOCKED,
    QUEST_ANSWERED_WAIT,
    QUEST_QUESTIONS,
    QUEST_REVEAL,
    QUEST_REVEAL_HEADER,
    VERDICT_DIFF,
    VERDICT_SAME,
)

router = Router(name="match")

TOTAL = len(QUEST_QUESTIONS)


def partner_of(match: dict, uid: int) -> int:
    return match["b_id"] if match["a_id"] == uid else match["a_id"]


def fmt_seconds_left(match: dict) -> str:
    return str(MATCH_TTL_HOURS)


# ─────────────────────────── список мэтчей ───────────────────────────
async def show_matches(message: Message, uid: int) -> None:
    matches = await db.user_matches(uid)
    if not matches:
        await message.answer(
            "Мэтчей пока нет 💤\n\nЖми «🔍 Искать» — и лайкай тех, кто зацепил. "
            "Помни: химия считается по ответам, так что анкета важнее фильтров."
        )
        return

    ready = [m for m in matches if m["unlocked"]]
    quests = [m for m in matches if not m["unlocked"]]
    text = f"🧪 <b>Твои мэтчи</b> — {len(matches)}\n"
    if ready:
        text += f"\n💬 Чаты открыты: {len(ready)}"
    if quests:
        text += f"\n🧊 Ждут Ледокол: {len(quests)}"
    text += "\n\nВыбирай:"
    await message.answer(text, reply_markup=matches_kb(matches))


# ─────────────────────────── запуск квеста ───────────────────────────
async def start_quest(bot: Bot, uid: int, match_id: int) -> None:
    match = await db.get_match(match_id)
    if not match or match["closed"]:
        return
    try:
        await bot.send_message(uid, MATCH_FOUND)
    except Exception:
        pass
    progress = await db.quest_progress(match_id, uid)
    if progress < TOTAL:
        await ask_question(bot, uid, match_id, progress)


async def ask_question(bot: Bot, uid: int, match_id: int, idx: int) -> None:
    q = QUEST_QUESTIONS[idx]
    try:
        await bot.send_message(
            uid,
            f"🧊 <b>Вопрос {idx + 1} из {TOTAL}</b>\n\n{q['q']}",
            reply_markup=quest_kb(match_id, idx, q["options"]),
        )
    except Exception:
        pass  # демо-анкета: реального чата нет


@router.callback_query(F.data.startswith("quest:"))
async def cb_quest(call: CallbackQuery) -> None:
    match_id = int(call.data.split(":")[1])
    match = await db.get_match(match_id)
    if not match or call.from_user.id not in (match["a_id"], match["b_id"]):
        await call.answer("Это не твой мэтч", show_alert=True)
        return
    if match["closed"]:
        await call.answer("Мэтч сгорел 💨", show_alert=True)
        return
    if match["unlocked"]:
        await call.answer("Ледокол уже пройден — открывай чат 💬", show_alert=False)
        return

    progress = await db.quest_progress(match_id, call.from_user.id)
    if progress >= TOTAL:
        await call.answer("Ты ответил на всё. Ждём вторую сторону 🧊", show_alert=True)
        return
    await ask_question(call.bot, call.from_user.id, match_id, progress)
    await call.answer()


# ─────────────────────────── ответы на квест ───────────────────────────
async def submit_answer(bot: Bot, match_id: int, uid: int, idx: int, opt: int) -> str:
    """Ядро «Ледокола»: принять ответ, раскрыть при паре, разблокировать чат.

    Возвращает код результата: "saved" | "wait" | "revealed" | "unlocked"
    Вынесено отдельно от хендлера, чтобы это можно было тестировать без Telegram.
    """
    match = await db.get_match(match_id)
    if not match or uid not in (match["a_id"], match["b_id"]):
        return "not_member"
    if match["closed"]:
        return "closed"
    if match["unlocked"]:
        return "unlocked"
    if await db.quest_answer(match_id, uid, idx):
        return "already"
    if not (0 <= idx < TOTAL) or not (0 <= opt < len(QUEST_QUESTIONS[idx]["options"])):
        return "bad_option"

    q = QUEST_QUESTIONS[idx]
    answer = q["options"][opt]
    await db.save_quest_answer(match_id, uid, idx, answer)

    partner_id = partner_of(match, uid)
    # демо-собеседник отвечает сам
    from handlers.demo import auto_answer

    await auto_answer(bot, match_id, partner_id, idx)
    partner_answer = await db.quest_answer(match_id, partner_id, idx)

    if partner_answer is None:
        partner_progress = await db.quest_progress(match_id, partner_id)
        if partner_progress == idx:
            await ask_question(bot, partner_id, match_id, idx)
        return "wait"

    a_id, b_id = match["a_id"], match["b_id"]
    a_user, b_user = await db.get_user(a_id), await db.get_user(b_id)
    a_answer = await db.quest_answer(match_id, a_id, idx)
    b_answer = await db.quest_answer(match_id, b_id, idx)

    verdict = VERDICT_SAME if a_answer == b_answer else VERDICT_DIFF
    reveal = QUEST_REVEAL_HEADER.format(n=idx + 1, q=q["q"]) + QUEST_REVEAL.format(
        a_name=esc(a_user["name"]) if a_user else "Он(а)",
        a=esc(a_answer),
        b_name=esc(b_user["name"]) if b_user else "Он(а)",
        b=esc(b_answer),
        verdict=verdict,
    )
    for recipient in (a_id, b_id):
        try:
            await bot.send_message(recipient, reveal)
        except Exception:
            pass

    pa = await db.quest_progress(match_id, a_id)
    pb = await db.quest_progress(match_id, b_id)
    if pa >= TOTAL and pb >= TOTAL:
        await unlock(bot, match_id)
        return "unlocked"
    for recipient, prog in ((a_id, pa), (b_id, pb)):
        if prog < TOTAL:
            await ask_question(bot, recipient, match_id, prog)
    return "revealed"


@router.callback_query(F.data.startswith("q:"))
async def cb_answer(call: CallbackQuery) -> None:
    _, mid_s, idx_s, opt_s = call.data.split(":")
    match_id, idx, opt = int(mid_s), int(idx_s), int(opt_s)

    result = await submit_answer(call.bot, match_id, call.from_user.id, idx, opt)
    if result == "not_member":
        await call.answer("Это не твой мэтч", show_alert=True)
        return
    if result == "closed":
        await call.answer("Мэтч сгорел 💨", show_alert=True)
        return
    if result == "unlocked":
        await call.answer("Уже открыто 💬", show_alert=False)
        return
    if result == "already":
        await call.answer("Ты уже ответил на этот вопрос 🙂", show_alert=False)
        return
    if result == "bad_option":
        await call.answer("Что-то пошло не так, попробуй ещё раз", show_alert=True)
        return

    await call.message.edit_reply_markup(reply_markup=None)
    if result == "wait":
        await call.message.answer(QUEST_ANSWERED_WAIT)
    await call.answer("🧊")


# ─────────────────────────── разблокировка чата ───────────────────────────
async def unlock(bot: Bot, match_id: int) -> None:
    match = await db.get_match(match_id)
    if not match or match["unlocked"]:
        return
    await db.unlock_match(match_id)
    a_user = await db.get_user(match["a_id"])
    b_user = await db.get_user(match["b_id"])
    for me, other in ((a_user, b_user), (b_user, a_user)):
        if not me or not other:
            continue
        try:
            await bot.send_message(
                me["id"],
                MATCH_UNLOCKED.format(hours=MATCH_TTL_HOURS),
                reply_markup=after_unlock_kb(
                    match_id, other.get("username") if other["id"] > 0 else None
                ),
            )
            if other.get("photo_id"):
                await bot.send_photo(
                    me["id"],
                    other["photo_id"],
                    caption=f"📸 Вот и фото: <b>{esc(other['name'])}</b>, {esc(other['age'])}",
                )
        except Exception:
            pass


# ─────────────────────────── сообщения о сгоревших мэтчах ───────────────────────────
async def notify_expired(bot: Bot, expired: list[dict]) -> None:
    for match in expired:
        for me_id, other_id in ((match["a_id"], match["b_id"]), (match["b_id"], match["a_id"])):
            other = await db.get_user(other_id)
            name = other["name"] if other else "собеседником"
            try:
                await bot.send_message(
                    me_id,
                    f"💨 Мэтч с <b>{esc(name)}</b> сгорел: за {MATCH_TTL_HOURS} часов ни одного сообщения.\n"
                    "Ничего личного — так у нас не бывает мёртвых мэтчей. Лента ждёт.",
                )
            except Exception:
                pass
