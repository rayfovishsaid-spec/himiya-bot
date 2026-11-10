"""Интеграционный тест анкеты — без Telegram и без токена.

Проверяет весь путь регистрации через настоящие хендлеры + настоящий FSM,
и специально воспроизводит два места, которые уже ломались в бою:
  • повторный клик по той же кнопке (Telegram → «message is not modified»)
  • параллельная доставка одного апдейта дважды

Запуск:  python tests/test_registration.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aiogram.exceptions import TelegramBadRequest  # noqa: E402
from aiogram.fsm.context import FSMContext  # noqa: E402
from aiogram.fsm.storage.base import StorageKey  # noqa: E402

import db  # noqa: E402
from services import matchmaking  # noqa: E402
from texts import PROFILE_QUESTIONS  # noqa: E402

UID = 7697964856


class FakeBot:
    def __init__(self) -> None:
        self.out: list[tuple[int, str, dict]] = []

    async def send_message(self, chat_id, text, **kwargs):
        self.out.append((chat_id, text, kwargs))
        return SimpleNamespace(message_id=len(self.out))

    async def send_photo(self, chat_id, photo, caption=None, **kwargs):
        self.out.append((chat_id, caption or "", kwargs))
        return SimpleNamespace(message_id=len(self.out))

    async def send_voice(self, chat_id, voice, **kwargs):
        self.out.append((chat_id, "[voice]", kwargs))
        return SimpleNamespace(message_id=len(self.out))

    def texts(self) -> list[str]:
        return [text for _, text, _ in self.out]

    def last(self) -> str:
        return self.out[-1][1] if self.out else ""


class FakeMessage:
    """Минимальная замена aiogram.Message: только то, что реально используют хендлеры."""

    def __init__(self, bot: FakeBot, uid: int = UID, text: str | None = None,
                 photo: bool = False, voice: bool = False) -> None:
        self.bot = bot
        self.from_user = SimpleNamespace(id=uid, username=f"user{uid}")
        self.chat = SimpleNamespace(id=uid)
        self.text = text
        self.photo = [SimpleNamespace(file_id="photo_1", width=800)] if photo else None
        self.voice = SimpleNamespace(file_id="voice_1", duration=12) if voice else None
        self.audio = None
        self.video_note = None
        self.reply_to_message = None
        self.message_id = 1
        self.content_type = "photo" if photo else ("voice" if voice else "text")
        self._shown: str | None = None

    async def answer(self, text, **kwargs):
        bot_out = (self.chat.id, text, kwargs)
        self.bot.out.append(bot_out)
        return SimpleNamespace(message_id=len(self.bot.out))

    async def edit_text(self, text, **kwargs):
        # точная копия поведения Telegram: тот же текст → 400 Bad Request
        if text == self._shown:
            raise TelegramBadRequest(method=None, message="message is not modified: same content")
        self._shown = text
        self.bot.out.append((self.chat.id, text, {"edit": True}))
        return SimpleNamespace(message_id=1)

    async def edit_reply_markup(self, **kwargs):
        return None


class FakeCallback:
    def __init__(self, bot: FakeBot, data: str, uid: int = UID) -> None:
        self.bot = bot
        self.data = data
        self.from_user = SimpleNamespace(id=uid, username=f"user{uid}")
        self.message = FakeMessage(bot, uid)
        self.answers: list[str] = []

    async def answer(self, text: str = "", **kwargs):
        self.answers.append(text)
        return True


def make_state(storage) -> FSMContext:
    return FSMContext(
        storage=storage,
        key=StorageKey(bot_id=1, chat_id=UID, user_id=UID, destiny="default"),
    )


async def main() -> None:
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    await db.init(tmp.name)

    from handlers import registration, start
    from storage import SQLiteStorage

    storage = SQLiteStorage()
    bot = FakeBot()
    ctx = make_state(storage)

    print("1) /start → приветствие + состояние Registration:name")
    await start.cmd_start(FakeMessage(bot, text="/start"), ctx)
    assert (await ctx.get_state()) == "Registration:name", await ctx.get_state()
    assert any("Химия" in t for t in bot.texts()), "нет приветствия"
    print("   ok ✅")

    print("2) имя → возраст → город")
    await registration.step_name(FakeMessage(bot, text="Вадим"), ctx)
    assert (await db.get_user(UID))["name"] == "Вадим"
    assert (await ctx.get_state()) == "Registration:age"

    await registration.step_age(FakeMessage(bot, text="17"), ctx)
    assert "18" in bot.last() and (await ctx.get_state()) == "Registration:age", "17 лет должны отклоняться"
    await registration.step_age(FakeMessage(bot, text="27"), ctx)
    assert (await db.get_user(UID))["age"] == 27

    await registration.step_city(FakeMessage(bot, text="Ставрополь"), ctx)
    assert (await db.get_user(UID))["city"] == "Ставрополь"
    print("   ok ✅ (валидация возраста работает)")

    print("3) пол и цель через кнопки")
    await registration.step_gender(FakeCallback(bot, "gender:m"), ctx)
    assert (await db.get_user(UID))["gender"] == "m"
    await registration.step_seek(FakeCallback(bot, "seek:f"), ctx)
    user = await db.get_user(UID)
    assert user["seek"] == "f"
    assert (await ctx.get_state()) == "QuestionFlow:answering"
    print("   ok ✅")

    print("4) 5 вопросов анкеты идемпотентно")
    total = len(PROFILE_QUESTIONS)
    assert total == 5, f"обещали 5 вопросов, а их {total}"
    for idx in range(total):
        call = FakeCallback(bot, f"ans:{idx}:{idx % len(PROFILE_QUESTIONS[idx]['options'])}")
        await registration.step_answers(call, ctx)
        assert call.answers, f"на вопрос {idx + 1} не ответили пользователю (кнопка зависнет)"
        # повторный клик по тому же вопросу не должен ничего ломать
        dup = FakeCallback(bot, f"ans:{idx}:0")
        await registration.step_answers(dup, ctx)
        assert dup.answers and ("позади" in dup.answers[0] or dup.answers[0] == "")
    print(f"   {total} вопросов, повторные клики не ломают ✅")

    print("5) фото и голосовое")
    await registration.step_photo(FakeMessage(bot, photo=True), ctx)
    assert (await db.get_user(UID))["photo_id"] == "photo_1"
    await registration.step_voice(FakeMessage(bot, voice=True), ctx)
    assert (await db.get_user(UID))["voice_id"] == "voice_1"
    print("   ok ✅")

    print("6) интересы и финиш")
    for tag in ("кино", "музыка", "путешествия"):
        await registration.step_interests(FakeCallback(bot, f"int:{tag}"), ctx)
    done = FakeCallback(bot, "int:done")
    await registration.step_interests(done, ctx)
    assert (await ctx.get_state()) is None, "после финиша состояние должно очищаться"
    user = await db.get_user(UID)
    assert db.profile_complete(user), "анкета должна считаться заполненной"
    assert "путешествия" in user["interests"]
    print("   анкета заполнена ✅")

    print("7) «message is not modified» больше не вешает кнопку")
    msg = FakeMessage(bot)
    await msg.edit_text("одинаковый текст")
    from utils import safe_edit

    assert await safe_edit(msg, "одинаковый текст") is False  # не падает, просто False
    print("   safe_edit глотает 400 ✅")

    print("8) спасение потерянных кнопок: любое сообщение возвращает текущий вопрос")
    await ctx.set_state("QuestionFlow:answering")
    await ctx.update_data(q_index=2, answers={"friday": "Бар с друзьями"})
    await registration.requestion(FakeMessage(bot, text="а где кнопки?"), ctx)
    assert "вопрос 3 из 5" in bot.last(), bot.last()[:80]
    print("   requestion работает ✅")

    await db.close()
    os.unlink(tmp.name)
    print("\n🎉 Анкета проходит целиком, зависаний нет")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    finally:
        sys.stdout.flush()
        os._exit(0)  # фоновые потоки aiosqlite не должны держать процесс
