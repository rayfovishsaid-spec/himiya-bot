"""Анкета пользователя, статистика, настройки видимости."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

import db
from keyboards import main_menu
from services import matchmaking
from texts import NEED_PROFILE

router = Router(name="profile")


async def show_profile(message: Message, uid: int) -> None:
    user = await db.get_user(uid)
    if not user:
        await message.answer("Напиши /start")
        return
    if not db.profile_complete(user):
        await message.answer(NEED_PROFILE)
        return

    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    fans = await db.who_liked_me(uid)
    matches = await db.user_matches(uid)
    text = matchmaking.short_profile(user)
    text += (
        f"\n\n📊 <b>Статистика</b>\n"
        f"Лайкнули тебя: <b>{len(fans)}</b>\n"
        f"Активных мэтчей: <b>{len(matches)}</b>\n"
        f"Видимость в ленте: {'скрыта 🙈' if user['is_hidden'] else 'включена 👀'}"
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎙 Дозаполнить/изменить", callback_data="profile:fill")],
            [
                InlineKeyboardButton(
                    text="👀 Показаться в ленте" if user["is_hidden"] else "🙈 Скрыть из ленты",
                    callback_data="profile:toggle_hidden",
                )
            ],
            [InlineKeyboardButton(text="🛡 Верификация", callback_data="profile:verify")],
        ]
    )
    if user.get("photo_id"):
        await message.answer_photo(
            user["photo_id"], caption=text, reply_markup=kb
        )
    else:
        await message.answer(text, reply_markup=kb)


@router.message(Command("profile"))
async def cmd_profile(message: Message) -> None:
    await show_profile(message, message.from_user.id)


@router.callback_query(F.data == "profile:toggle_hidden")
async def cb_toggle_hidden(call: CallbackQuery) -> None:
    user = await db.get_user(call.from_user.id)
    new_value = 0 if user["is_hidden"] else 1
    await db.set_field(call.from_user.id, "is_hidden", new_value)
    await call.answer("Скрыто 🙈" if new_value else "Ты снова в ленте 👀")
    await show_profile(call.message, call.from_user.id)


@router.callback_query(F.data == "profile:fill")
async def cb_fill(call: CallbackQuery, state) -> None:
    from handlers.registration import resume_fill

    await resume_fill(call.message, state)
    await call.answer()


@router.callback_query(F.data == "profile:verify")
async def cb_verify(call: CallbackQuery) -> None:
    await call.message.answer(
        "🛡 <b>Верификация</b>\n\n"
        "Пришли кружок (видео-сообщение) на 3–5 секунд: скажи своё имя и сегодняшнюю дату. "
        "Модератор проверит вручную — бейдж 🛡 поднимает мэтчи и отсекает фейки.\n\n"
        "Пока просто отправь кружок сюда — он уйдёт в очередь модерации."
    )
    await call.answer()


@router.message(F.video_note)
async def got_video_note(message: Message) -> None:
    await message.answer(
        "Кружок получен 🛡 Отправил в очередь модерации. "
        "Как проверим — появится бейдж в анкете."
    )
