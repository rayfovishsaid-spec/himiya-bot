"""Анонимный чат внутри бота: сообщения пересылаются через бота.

Работает двумя путями:
1) пользователь нажал «Писать здесь» → включилось состояние Chat.talking;
2) пользователь отвечает (Reply) на сообщение бота — находим отправителя по таблице messages.
"""
from __future__ import annotations

import asyncio

from aiogram import Bot, F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

import db
from keyboards import chat_kb
from utils import esc
from states import Chat
from texts import CHAT_ENTER, CHAT_LEFT, CHAT_NO_MATCH

router = Router(name="chat")


def _reply_kb(match_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="↩️ Ответить", callback_data=f"rt:{match_id}")]
        ]
    )


async def _relay(bot: Bot, match: dict, sender: dict, message: Message) -> None:
    """Пересылает сообщение партнёру без раскрытия контактов."""
    match_id = match["id"]
    partner_id = match["b_id"] if match["a_id"] == sender["id"] else match["a_id"]

    head = f"💬 <b>{esc(sender['name'])}</b>"
    sent = None
    if message.text:
        sent = await bot.send_message(
            partner_id, f"{head}\n{esc(message.text)}", reply_markup=_reply_kb(match_id)
        )
    elif message.photo:
        await bot.send_message(partner_id, head)
        sent = await bot.copy_message(partner_id, message.chat.id, message.message_id)
        await bot.send_message(partner_id, "↩️ Ответить — просто ответь на сообщение выше.")
    elif message.voice or message.video_note or message.video or message.sticker:
        await bot.send_message(partner_id, head)
        sent = await bot.copy_message(partner_id, message.chat.id, message.message_id)
        await bot.send_message(partner_id, "↩️ Ответить — ответом на сообщение выше.")
    else:
        await bot.send_message(sender["id"], "Пока умею пересылать текст, фото, видео и голосовые.")
        return

    if sent is not None:
        await db.save_message(match_id, sender["id"], partner_id, sent.message_id)
    await db.touch_match(match_id)

    # демо-собеседник отвечает сам
    from handlers.demo import auto_reply

    if partner_id < 0:
        asyncio.create_task(auto_reply(bot, match, partner_id, sender["id"]))


@router.callback_query(F.data.startswith("open:"))
async def cb_open(call: CallbackQuery, state: FSMContext) -> None:
    match_id = int(call.data.split(":")[1])
    match = await db.get_match(match_id)
    if not match or call.from_user.id not in (match["a_id"], match["b_id"]):
        await call.answer("Это не твой мэтч", show_alert=True)
        return
    if not match["unlocked"]:
        await call.answer("Сначала Ледокол 🧊", show_alert=True)
        return
    if match["closed"]:
        await call.answer("Мэтч сгорел 💨", show_alert=True)
        return

    partner = await db.get_user(match["b_id"] if match["a_id"] == call.from_user.id else match["a_id"])
    await state.set_state(Chat.talking)
    await state.update_data(match_id=match_id)
    await call.message.answer(
        CHAT_ENTER.format(name=esc(partner["name"]) if partner else "собеседником"),
        reply_markup=chat_kb(match_id),
    )
    await call.answer()


@router.callback_query(F.data.startswith("rt:"))
async def cb_reply_button(call: CallbackQuery, state: FSMContext) -> None:
    match_id = int(call.data.split(":")[1])
    await state.set_state(Chat.talking)
    await state.update_data(match_id=match_id)
    await call.answer("Пиши сообщение 👇")


@router.callback_query(F.data.startswith("leave:"))
async def cb_leave(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await call.message.answer(CHAT_LEFT)
    await call.answer()


@router.message(Command("stop"))
async def cmd_stop(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(CHAT_LEFT)


@router.message(Chat.talking)
async def chat_message(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    match_id = data.get("match_id")
    if not match_id:
        await state.clear()
        await message.answer(CHAT_NO_MATCH)
        return
    match = await db.get_match(int(match_id))
    if not match or match["closed"]:
        await state.clear()
        await message.answer("Этот чат закрыт. Открой «💬 Мои мэтчи».")
        return
    sender = await db.get_user(message.from_user.id)
    await _relay(message.bot, match, sender, message)


# ── Fallback: Reply на сообщение бота, когда состояния нет ──
# Вынесен в отдельный роутер: подключается самым последним, чтобы не съедать меню.
fallback_router = Router(name="chat_fallback")


@fallback_router.message(StateFilter(None))
async def chat_fallback(message: Message) -> None:
    if not message.from_user:
        return

    if message.reply_to_message:
        relay = await db.find_relay(message.from_user.id, message.reply_to_message.message_id)
        if relay:
            match = await db.get_match(relay["match_id"])
            partner = await db.get_user(relay["from_id"])
            if match and partner and not match["closed"]:
                sender = await db.get_user(message.from_user.id)
                await _relay(message.bot, match, sender, message)
                return

    # Если у человека ровно один открытый чат — просто роутим туда
    match = await db.first_open_match(message.from_user.id)
    if match:
        sender = await db.get_user(message.from_user.id)
        await _relay(message.bot, match, sender, message)
        return

    await message.answer("Не понял 🙂 Жми «🔍 Искать» или «💬 Мои мэтчи».")
