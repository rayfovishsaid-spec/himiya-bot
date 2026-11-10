"""Регистрация: анкета из 5 вопросов + фото + голос + интересы."""
from __future__ import annotations

import json

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import db
from utils import safe_edit
from config import MAX_AGE, MIN_AGE
from keyboards import (
    BTN_FEED,
    gender_kb,
    interests_kb,
    main_menu,
    options_kb,
    seek_kb,
)
from services import matchmaking
from states import QuestionFlow, Registration
from texts import (
    ASK_AGE,
    ASK_CITY,
    ASK_GENDER,
    ASK_INTERESTS,
    ASK_NAME,
    ASK_PHOTO,
    ASK_SEEK,
    ASK_VOICE,
    PROFILE_DONE,
    PROFILE_QUESTIONS,
)

router = Router(name="registration")


@router.message(Registration.name, F.text)
async def step_name(message: Message, state: FSMContext) -> None:
    name = message.text.strip()[:32]
    if len(name) < 2:
        await message.answer("Слишком коротко. Как тебя зовут?")
        return
    await db.set_field(message.from_user.id, "name", name)
    await state.set_state(Registration.age)
    await message.answer(ASK_AGE)


@router.message(Registration.age, F.text)
async def step_age(message: Message, state: FSMContext) -> None:
    text = message.text.strip()
    if not text.isdigit() or not (MIN_AGE <= int(text) <= MAX_AGE):
        await message.answer(f"Нужно число от {MIN_AGE} до {MAX_AGE}. Попробуй ещё раз.")
        return
    await db.set_field(message.from_user.id, "age", int(text))
    await state.set_state(Registration.city)
    await message.answer(ASK_CITY)


@router.message(Registration.city, F.text)
async def step_city(message: Message, state: FSMContext) -> None:
    city = message.text.strip()[:48]
    await db.set_field(message.from_user.id, "city", city)
    await state.set_state(Registration.gender)
    await message.answer(ASK_GENDER, reply_markup=gender_kb())


@router.callback_query(Registration.gender, F.data.startswith("gender:"))
async def step_gender(call: CallbackQuery, state: FSMContext) -> None:
    gender = call.data.split(":")[1]
    await db.set_field(call.from_user.id, "gender", gender)
    await state.set_state(Registration.seek)
    await safe_edit(call.message, ASK_SEEK, reply_markup=seek_kb())
    await call.answer()


@router.callback_query(Registration.seek, F.data.startswith("seek:"))
async def step_seek(call: CallbackQuery, state: FSMContext) -> None:
    seek = call.data.split(":")[1]
    await db.set_field(call.from_user.id, "seek", seek)
    await state.set_state(QuestionFlow.answering)
    await state.update_data(q_index=0, answers={})
    q = PROFILE_QUESTIONS[0]
    await safe_edit(call.message, 
        f"<b>Анкета: вопрос 1 из {len(PROFILE_QUESTIONS)}</b>\n\n{q['q']}",
        reply_markup=options_kb(0, q["options"], "ans"),
    )
    await call.answer()


# ───────────────────────── 5 вопросов анкеты ─────────────────────────
@router.callback_query(QuestionFlow.answering, F.data.startswith("ans:"))
async def step_answers(call: CallbackQuery, state: FSMContext) -> None:
    _, idx_s, opt_s = call.data.split(":")
    idx, opt = int(idx_s), int(opt_s)
    data = await state.get_data()
    answers: dict[str, str] = data.get("answers", {})
    if data.get("q_index") != idx:
        await call.answer("Этот вопрос уже позади 🙂", show_alert=False)
        return

    q = PROFILE_QUESTIONS[idx]
    answers[q["key"]] = q["options"][opt]
    await state.update_data(answers=answers, q_index=idx + 1)

    if idx + 1 < len(PROFILE_QUESTIONS):
        nxt = PROFILE_QUESTIONS[idx + 1]
        await safe_edit(call.message, 
            f"<b>Анкета: вопрос {idx + 2} из {len(PROFILE_QUESTIONS)}</b>\n\n{nxt['q']}",
            reply_markup=options_kb(idx + 1, nxt["options"], "ans"),
        )
    else:
        await db.set_answers(call.from_user.id, answers)
        await state.set_state(Registration.photo)
        await safe_edit(call.message, "Готово ✅")
        await call.message.answer(ASK_PHOTO)
    await call.answer()


@router.message(QuestionFlow.answering)
async def requestion(message: Message, state: FSMContext) -> None:
    """Спасение, если кнопки потерялись: любое сообщение заново показывает текущий вопрос."""
    data = await state.get_data()
    idx = int(data.get("q_index", 0))
    if idx >= len(PROFILE_QUESTIONS):
        await state.set_state(Registration.photo)
        await message.answer(ASK_PHOTO)
        return
    q = PROFILE_QUESTIONS[idx]
    await message.answer(
        f"<b>Анкета: вопрос {idx + 1} из {len(PROFILE_QUESTIONS)}</b>\n\n{q['q']}",
        reply_markup=options_kb(idx, q["options"], "ans"),
    )


@router.message(Registration.photo, F.photo)
async def step_photo(message: Message, state: FSMContext) -> None:
    photo_id = message.photo[-1].file_id
    await db.set_field(message.from_user.id, "photo_id", photo_id)
    await state.set_state(Registration.voice)
    await message.answer(ASK_VOICE)


@router.message(Registration.photo)
async def step_photo_wrong(message: Message) -> None:
    await message.answer("Нужно именно фото (не файл и не стикер) 📸. Отправь картинку ещё раз.")


@router.message(Registration.voice, F.voice | F.audio)
async def step_voice(message: Message, state: FSMContext) -> None:
    voice = message.voice or message.audio
    if voice.duration and voice.duration > 60:
        await message.answer("Давай до 60 секунд, это же не подкаст 🙂")
        return
    await db.set_field(message.from_user.id, "voice_id", voice.file_id)
    await state.set_state(Registration.interests)
    await state.update_data(interests=[])
    await message.answer(ASK_INTERESTS, reply_markup=interests_kb([]))


@router.message(Registration.voice, Command("skip"))
async def skip_voice(message: Message, state: FSMContext) -> None:
    await state.set_state(Registration.interests)
    await state.update_data(interests=[])
    await message.answer(
        "Ок, без голоса. Но заметь: анкеты с голосом собирают в разы больше мэтчей 🎙\n\n"
        + ASK_INTERESTS,
        reply_markup=interests_kb([]),
    )


@router.message(Registration.voice)
async def voice_wrong(message: Message) -> None:
    await message.answer("Жду голосовое (кружок с микрофоном) или /skip 🎙")


@router.callback_query(Registration.interests, F.data.startswith("int:"))
async def step_interests(call: CallbackQuery, state: FSMContext) -> None:
    value = call.data.split(":", 1)[1]
    data = await state.get_data()
    selected: list[str] = data.get("interests", [])

    if value == "done":
        if len(selected) < 3:
            await call.answer("Выбери хотя бы 3 интереса", show_alert=True)
            return
        await db.set_interests(call.from_user.id, selected)
        await state.clear()
        await safe_edit(call.message, "🧪 Анкета собрана!")
        await call.message.answer(PROFILE_DONE, reply_markup=main_menu())

        user = await db.get_user(call.from_user.id)
        if user:
            missing = [s for s in matchmaking.missing_steps(user) if "необязательно" not in s]
            if missing:
                await call.message.answer("Дозаполнить: " + ", ".join(missing) + "\n/profile")
        await call.answer()
        return

    if value in selected:
        selected.remove(value)
    else:
        if len(selected) >= 6:
            await call.answer("Максимум 6 интересов", show_alert=True)
            return
        selected.append(value)
    await state.update_data(interests=selected)
    await call.message.edit_reply_markup(reply_markup=interests_kb(selected))
    await call.answer()


# ───────────── /profile и кнопка «Анкета»: что дозаполнить ─────────────
@router.message(Command("fill"))
async def resume_fill(message: Message, state: FSMContext) -> None:
    user = await db.get_user(message.from_user.id)
    if not user:
        await message.answer("Напиши /start")
        return
    if not user.get("name"):
        await state.set_state(Registration.name)
        await message.answer(ASK_NAME)
    elif not user.get("age"):
        await state.set_state(Registration.age)
        await message.answer(ASK_AGE)
    elif not user.get("city"):
        await state.set_state(Registration.city)
        await message.answer(ASK_CITY)
    elif not user.get("gender"):
        await state.set_state(Registration.gender)
        await message.answer(ASK_GENDER, reply_markup=gender_kb())
    elif not user.get("answers") or user.get("answers") == "{}":
        await state.set_state(QuestionFlow.answering)
        await state.update_data(q_index=0, answers={})
        q = PROFILE_QUESTIONS[0]
        await message.answer(
            f"<b>Анкета: вопрос 1 из {len(PROFILE_QUESTIONS)}</b>\n\n{q['q']}",
            reply_markup=options_kb(0, q["options"], "ans"),
        )
    elif not user.get("photo_id"):
        await state.set_state(Registration.photo)
        await message.answer(ASK_PHOTO)
    elif not user.get("voice_id"):
        await state.set_state(Registration.voice)
        await message.answer(ASK_VOICE)
    else:
        await state.set_state(Registration.interests)
        await state.update_data(interests=json.loads(user.get("interests") or "[]"))
        await message.answer(ASK_INTERESTS, reply_markup=interests_kb(json.loads(user.get("interests") or "[]")))
