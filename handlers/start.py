"""Старт, меню, справка."""
from aiogram import F, Router
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

import db
from utils import esc
from keyboards import BTN_FEED, BTN_LIKED_ME, BTN_MATCHES, BTN_PROFILE, main_menu
from services import matchmaking
from states import Registration
from texts import HELP, NEED_PROFILE, START

router = Router(name="start")


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    user = await db.ensure_user(message.from_user.id, message.from_user.username)

    from handlers.admin import claim_first_admin

    if await claim_first_admin(message.from_user.id):
        await message.answer(
            "👑 Ты — администратор этого бота.\n"
            f"Твой ID: <code>{message.from_user.id}</code>\n\n"
            "Команды: /admin — статистика, /ban /unban /verify /reports /broadcast"
        )

    if not db.profile_complete(user):
        await state.set_state(Registration.name)
        await message.answer(START)
        await message.answer("Как тебя зовут? (имя или ник — как хочешь, чтобы видели другие)")
        return

    await message.answer(
        f"С возвращением, <b>{esc(user['name'])}</b> 🧪\n\n"
        "Что делаем? Смотри ленту или проверь мэтчи.",
        reply_markup=main_menu(),
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP, reply_markup=main_menu())


@router.message(Command("menu"))
async def cmd_menu(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Меню 🧪", reply_markup=main_menu())


@router.message(StateFilter(None), F.text == BTN_FEED)
async def menu_feed(message: Message) -> None:
    from handlers.feed import send_next_card

    user = await db.get_user(message.from_user.id)
    if not db.profile_complete(user):
        await message.answer(NEED_PROFILE)
        return
    await send_next_card(message.bot, message.chat.id, message.from_user.id)


@router.message(StateFilter(None), F.text == BTN_MATCHES)
async def menu_matches(message: Message) -> None:
    from handlers.match import show_matches

    await show_matches(message, message.from_user.id)


@router.message(StateFilter(None), F.text == BTN_PROFILE)
async def menu_profile(message: Message) -> None:
    from handlers.profile import show_profile

    await show_profile(message, message.from_user.id)


@router.message(StateFilter(None), F.text == BTN_LIKED_ME)
async def menu_liked_me(message: Message) -> None:
    user = await db.get_user(message.from_user.id)
    if not db.profile_complete(user):
        await message.answer(NEED_PROFILE)
        return

    from keyboards import liked_me_kb

    fans = await db.who_liked_me(message.from_user.id)
    if not fans:
        await message.answer(
            "Пока тихо 💤\n\nЗаполни голосовое и фото — и лайки подтянутся. "
            "Ещё работает: чаще появляйся в ленте («🔍 Искать»)."
        )
        return
    await message.answer(
        f"💘 Тебя лайкнули: <b>{len(fans)}</b> человек.\n"
        "Показываю их по одному — лайкни в ответ, и будет мэтч.",
        reply_markup=liked_me_kb(),
    )
