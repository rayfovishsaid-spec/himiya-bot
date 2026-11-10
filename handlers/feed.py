"""Лента анкет: карточка, лайк/скип, «подглядеть фото» за Stars, жалобы."""
from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
)

import db
from utils import esc
from config import DAILY_LIKES, PHOTO_PEEK_STARS
from keyboards import card_kb
from services import matchmaking
from states import Report
from texts import (
    FEED_EMPTY,
    LIKE_SENT,
    NEED_PROFILE,
    SKIP_SENT,
)

router = Router(name="feed")


async def send_next_card(bot: Bot, chat_id: int, uid: int) -> None:
    """Показывает следующую анкету (голос + карточка с кнопками)."""
    viewer = await db.get_user(uid)
    if not viewer:
        await bot.send_message(chat_id, "Напиши /start")
        return
    if not db.profile_complete(viewer):
        await bot.send_message(chat_id, NEED_PROFILE)
        return

    left = DAILY_LIKES - await db.likes_today(uid)
    if left <= 0:
        await bot.send_message(
            chat_id,
            "На сегодня лайки закончились 🙃\n\n"
            "Это защита от спама — завтра лимит обновится. "
            "А пока можно поболтать в «💬 Мои мэтчи».",
        )
        return

    seek = viewer["seek"]
    genders = [seek] if seek in ("m", "f") else ["m", "f", "x"]
    candidate = None
    for gender in genders:
        candidate = await db.next_candidate(uid, gender, viewer.get("city"))
        if candidate:
            break

    if not candidate:
        await bot.send_message(chat_id, FEED_EMPTY)
        return

    if candidate.get("voice_id"):
        try:
            await bot.send_voice(chat_id, candidate["voice_id"])
        except Exception:
            pass  # файл мог протухнуть — карточка всё равно уйдёт

    caption = matchmaking.card_caption(candidate, viewer)
    await bot.send_message(
        chat_id,
        caption,
        reply_markup=card_kb(candidate["id"], bool(candidate.get("voice_id"))),
        disable_web_page_preview=True,
    )


@router.callback_query(F.data.startswith("like:"))
async def cb_like(call: CallbackQuery) -> None:
    me = await db.get_user(call.from_user.id)
    if not me or not db.profile_complete(me):
        await call.answer("Сначала анкета", show_alert=True)
        return
    if DAILY_LIKES - await db.likes_today(call.from_user.id) <= 0:
        await call.answer("Лимит лайков на сегодня исчерпан", show_alert=True)
        return

    target_id = int(call.data.split(":")[1])
    if target_id == call.from_user.id:
        await call.answer("Себя лайкать нельзя, но ты молодец 🙂", show_alert=True)
        return

    target = await db.get_user(target_id)
    if not target or target.get("is_banned"):
        await call.answer("Эта анкета больше недоступна", show_alert=True)
        return

    mutual = await db.save_like(call.from_user.id, target_id)
    await db.save_seen(call.from_user.id, target_id)

    if mutual:
        # Уже есть мэтч? Не создаём дубль.
        existing = await db.find_match_between(call.from_user.id, target_id)
        match_id = existing["id"] if existing else await db.create_match(call.from_user.id, target_id)
        await call.message.edit_reply_markup(reply_markup=None)
        await call.message.answer(
            f"🔥 Взаимно! Это мэтч с <b>{esc(target['name'])}</b>. Открываю Ледокол…"
        )
        from handlers.match import start_quest

        await start_quest(call.bot, call.from_user.id, match_id)
        try:
            await start_quest(call.bot, target_id, match_id)
        except Exception:
            pass  # демо-анкета без реального чата
    else:
        await call.message.edit_reply_markup(reply_markup=None)
        await call.message.answer(LIKE_SENT)
        await send_next_card(call.bot, call.message.chat.id, call.from_user.id)
    await call.answer("❤️")


@router.callback_query(F.data.startswith("skip:"))
async def cb_skip(call: CallbackQuery) -> None:
    target_id = int(call.data.split(":")[1])
    await db.save_seen(call.from_user.id, target_id)
    await call.message.edit_reply_markup(reply_markup=None)
    await call.message.answer(SKIP_SENT)
    await send_next_card(call.bot, call.message.chat.id, call.from_user.id)
    await call.answer()


@router.callback_query(F.data.startswith("voice:"))
async def cb_voice(call: CallbackQuery) -> None:
    target = await db.get_user(int(call.data.split(":")[1]))
    if not target or not target.get("voice_id"):
        await call.answer("У этого человека нет голосового", show_alert=True)
        return
    await call.bot.send_voice(call.from_user.id, target["voice_id"])
    await call.answer()


# ─────────────────── «Подглядеть фото» за Telegram Stars ───────────────────
@router.callback_query(F.data.startswith("peek:"))
async def cb_peek(call: CallbackQuery) -> None:
    target_id = int(call.data.split(":")[1])
    target = await db.get_user(target_id)
    if not target or not target.get("photo_id"):
        await call.answer("Фото нет", show_alert=True)
        return

    await call.bot.send_invoice(
        chat_id=call.from_user.id,
        title="Подглядеть фото",
        description=f"Открыть фото анкеты «{target['name']}» до мэтча",
        payload=f"peek:{target_id}",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label="Подглядеть фото", amount=PHOTO_PEEK_STARS)],
    )
    await call.answer()


@router.pre_checkout_query()
async def pre_checkout(q: PreCheckoutQuery) -> None:
    await q.answer(ok=True)


@router.message(F.successful_payment)
async def paid(message: Message) -> None:
    payload = message.successful_payment.invoice_payload or ""
    if payload.startswith("peek:"):
        target = await db.get_user(int(payload.split(":")[1]))
        if target and target.get("photo_id"):
            await message.answer_photo(
                target["photo_id"], caption=f"📸 {target['name']}, {target['age']} — как просил 🙂"
            )
            return
    await message.answer("Оплата прошла ✅")


# ───────────────────────────── жалобы ─────────────────────────────
@router.callback_query(F.data.startswith("rep:"))
async def cb_report(call: CallbackQuery, state) -> None:
    target_id = int(call.data.split(":")[1])
    await state.set_state(Report.reason)
    await state.update_data(report_target=target_id)
    await call.message.answer(
        "🚩 На что жалуешься? Напиши одним сообщением: спам, обнажёнка, "
        "оскорбления, несовершеннолетний, фейк."
    )
    await call.answer()


@router.message(Report.reason, F.text)
async def report_reason(message: Message, state) -> None:
    data = await state.get_data()
    target = int(data.get("report_target") or 0)
    if target:
        await db.add_report(message.from_user.id, target, message.text[:300])
    else:
        await db.add_report(message.from_user.id, 0, f"[материал {data.get('report_article')}] {message.text[:280]}")
    await state.clear()
    await message.answer(
        "Жалоба принята 🙏 Модератор посмотрит. Спасибо, что держишь «Химию» живой."
    )


@router.message(Command("report"))
async def cmd_report(message: Message) -> None:
    await message.answer(
        "Чтобы пожаловаться: нажми 🚩 в карточке анкеты или в чате — так я пойму, на кого."
    )
