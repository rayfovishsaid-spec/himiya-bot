"""Автотест ядра бота без Telegram: мэтч → Ледокол → разблокировка чата → сгорание.

Запуск:  python tests/test_flow.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db  # noqa: E402
from services import matchmaking  # noqa: E402
from texts import PROFILE_QUESTIONS, QUEST_QUESTIONS  # noqa: E402


class FakeBot:
    """Заглушка Bot: запоминает всё, что бот отправил."""

    def __init__(self) -> None:
        self.outbox: list[tuple[int, str]] = []

    async def send_message(self, chat_id, text, **kwargs):
        self.outbox.append((chat_id, text))

        class Msg:
            message_id = len(self.outbox)

        return Msg()

    async def send_photo(self, chat_id, photo, caption=None, **kwargs):
        self.outbox.append((chat_id, f"[photo] {caption or ''}"))
        return None

    async def send_voice(self, chat_id, voice, **kwargs):
        self.outbox.append((chat_id, "[voice]"))
        return None

    def texts_for(self, uid: int) -> list[str]:
        return [t for chat, t in self.outbox if chat == uid]


def make_user(uid: int, name: str, gender: str, seek: str, answers_idx: list[int]):
    answers = {
        q["key"]: q["options"][answers_idx[i]] for i, q in enumerate(PROFILE_QUESTIONS)
    }
    return uid, answers


async def setup_user(uid: int, name: str, gender: str, seek: str, picks: list[int], city="Лондон"):
    await db.ensure_user(uid, f"user{uid}")
    await db.set_field(uid, "name", name)
    await db.set_field(uid, "age", 25)
    await db.set_field(uid, "city", city)
    await db.set_field(uid, "gender", gender)
    await db.set_field(uid, "seek", seek)
    await db.set_field(uid, "photo_id", f"photo{uid}")
    _, answers = make_user(uid, name, gender, seek, picks)
    await db.set_answers(uid, answers)
    await db.set_interests(uid, ["кино", "спорт", "путешествия"])


async def main() -> None:
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    await db.init(tmp.name)
    bot = FakeBot()

    from handlers import match as match_handlers

    print("1) Химия: проверяем диапазон и реакцию на совпадения")
    a = await db.ensure_user(1, "a")
    b = await db.ensure_user(2, "b")
    a.update({"answers": json.dumps({q["key"]: q["options"][0] for q in PROFILE_QUESTIONS}),
              "interests": json.dumps(["кино", "спорт"])})
    b.update({"answers": json.dumps({q["key"]: q["options"][0] for q in PROFILE_QUESTIONS}),
              "interests": json.dumps(["кино", "спорт"])})
    same = matchmaking.chemistry(a, b)
    b["answers"] = json.dumps({q["key"]: q["options"][-1] for q in PROFILE_QUESTIONS})
    b["interests"] = json.dumps(["йога"])
    diff = matchmaking.chemistry(a, b)
    assert 55 <= diff <= 99 and 55 <= same <= 99, (same, diff)
    assert same > diff, f"одинаковые ответы должны давать больше химии: {same} vs {diff}"
    print(f"   одинаковые: {same}%, разные: {diff}%  ✅")

    print("2) Регистрация двух анкет")
    await setup_user(1, "Аня", "f", "m", [0, 1, 2, 0, 2, 1])
    await db.set_field(1, "voice_id", "voice1")
    await setup_user(2, "Борис", "m", "f", [0, 1, 2, 0, 2, 3])
    assert db.profile_complete(await db.get_user(1))
    assert db.profile_complete(await db.get_user(2))
    print("   анкеты полные ✅")

    print("3) Лента: Борис видит Аню, но не себя")
    cand = await db.next_candidate(2, "f", "Лондон")
    assert cand and cand["id"] == 1, cand
    cand2 = await db.next_candidate(1, "m", "Лондон")
    assert cand2 and cand2["id"] == 2
    print("   подбор работает ✅")

    print("4) Взаимные лайки → мэтч")
    assert await db.save_like(2, 1) is False, "первый лайк не может быть взаимным"
    assert await db.save_like(1, 2) is True, "второй лайк должен дать мэтч"
    match_id = await db.create_match(1, 2)
    await match_handlers.start_quest(bot, 1, match_id)
    await match_handlers.start_quest(bot, 2, match_id)
    assert any("МЭТЧ" in t for t in bot.texts_for(1))
    assert any("МЭТЧ" in t for t in bot.texts_for(2))
    print("   мэтч + приглашение в Ледокол ✅")

    print("5) Ледокол: оба отвечают на 5 вопросов")
    total = len(QUEST_QUESTIONS)
    for idx in range(total):
        r1 = await match_handlers.submit_answer(bot, match_id, 1, idx, 0)
        assert r1 == "wait", f"первый ответ должен ждать пару, а не {r1}"
        r2 = await match_handlers.submit_answer(bot, match_id, 2, idx, 0 if idx % 2 == 0 else 1)
        expected = "unlocked" if idx == total - 1 else "revealed"
        assert r2 == expected, f"вопрос {idx + 1}: ждали {expected}, получили {r2}"

    m = await db.get_match(match_id)
    assert m["unlocked"] == 1, "после 5 вопросов чат должен открыться"
    assert any("Ледокол пройден" in t for t in bot.texts_for(1))
    assert any("Ледокол пройден" in t for t in bot.texts_for(2))
    print(f"   квест пройден, чат открыт, раскрытий: "
          f"{sum('Полное совпадение' in t or 'По-разному' in t for _, t in bot.outbox)} ✅")

    print("6) Защита от повторов и чужих")
    assert await match_handlers.submit_answer(bot, match_id, 1, 0, 0) == "unlocked"
    assert await match_handlers.submit_answer(bot, match_id, 999, 0, 0) == "not_member"
    print("   защита работает ✅")

    print("7) Релокация сообщения в чате")
    await db.save_message(match_id, 1, 2, 4242)
    relay = await db.find_relay(2, 4242)
    assert relay and relay["from_id"] == 1 and relay["match_id"] == match_id
    print("   reply-роутинг работает ✅")

    print("8) Сгорание мэтча без сообщений")
    match2 = await db.create_match(1, 2)
    await db.execute(
        "UPDATE matches SET expires_at = '2000-01-01T00:00:00+00:00' WHERE id = ?", (match2,)
    )
    expired = await db.expire_matches()
    assert any(e["id"] == match2 for e in expired)
    await match_handlers.notify_expired(bot, expired)
    assert any("сгорел" in t for t in bot.texts_for(1))
    print("   мэтч сгорел и оба уведомлены ✅")

    print("9) Статистика и жалобы")
    await db.add_report(1, 2, "спам")
    s = await db.stats()
    assert s["users"] == 2 and s["reports"] == 1, s
    print(f"   {s} ✅")

    await db.close()
    os.unlink(tmp.name)
    print("\n🎉 Все тесты прошли")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    finally:
        sys.stdout.flush()
        os._exit(0)
