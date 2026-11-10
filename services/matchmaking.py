"""Игровая математика: химия между анкетами, тексты карточек, подбор."""
from __future__ import annotations

import json
import zlib
from typing import Any

from texts import INTERESTS, PROFILE_QUESTIONS
from utils import esc

_Q_KEYS = [q["key"] for q in PROFILE_QUESTIONS]
_Q_MAP = {q["key"]: q for q in PROFILE_QUESTIONS}


def chemistry(a: dict[str, Any], b: dict[str, Any]) -> int:
    """
    Химия 55–99%: совпадение ответов (вес 70%) + общие интересы (вес 30%).
    Плюс маленький «рандом» от хеша пары — чтобы проценты не были плоскими.
    """
    try:
        ans_a = json.loads(a.get("answers") or "{}")
        ans_b = json.loads(b.get("answers") or "{}")
    except json.JSONDecodeError:
        ans_a, ans_b = {}, {}

    common = [k for k in _Q_KEYS if k in ans_a and k in ans_b]
    same = sum(1 for k in common if ans_a[k] == ans_b[k])
    answers_part = (same / len(common)) if common else 0.5

    int_a = set(json.loads(a.get("interests") or "[]"))
    int_b = set(json.loads(b.get("interests") or "[]"))
    union = int_a | int_b
    jaccard = len(int_a & int_b) / len(union) if union else 0.0

    base = 0.7 * answers_part + 0.3 * jaccard          # 0..1
    jitter = zlib.crc32(f"{min(a['id'], b['id'])}:{max(a['id'], b['id'])}".encode()) % 7
    score = 55 + round(base * 40) + jitter              # 55..102
    return max(55, min(99, score))


def chem_comment(score: int) -> str:
    if score >= 90:
        return "Это не совпадение, это диагноз. Пишите друг другу немедленно."
    if score >= 80:
        return "Сильная заявка. Скорее всего, вам будет о чём трепаться всю ночь."
    if score >= 70:
        return "Хорошая база: есть совпадения, есть о чём спорить."
    return "Почти всё разное — но иногда именно так и начинается лучшее."


def chem_bar(score: int, width: int = 10) -> str:
    """Полоска химии — визуальный акцент вместо скучных цифр."""
    filled = max(1, min(width, round(score / 100 * width)))
    return "▰" * filled + "▱" * (width - filled)


def card_caption(user: dict[str, Any], viewer: dict[str, Any] | None = None) -> str:
    """Текст карточки: без фото, зато с содержанием. Максимально близко к макету."""
    answers = json.loads(user.get("answers") or "{}")
    interests = json.loads(user.get("interests") or "[]")
    lines: list[str] = []

    verified = " 🛡" if user.get("verified") else ""
    lines.append(f"🧪 <b>{esc(user['name'])}, {esc(user['age'])}</b> — {esc(user['city'])}{verified}")

    if viewer:
        score = chemistry(user, viewer)
        lines.append(f"💫 Химия с тобой: <b>{score}%</b>  {chem_bar(score)}")
        if viewer.get("city") and viewer.get("city") == user.get("city"):
            lines.append("📍 Тот же город")

    pairs = [
        f"{_Q_MAP[key]['q']} → <b>{answers[key]}</b>"
        for key in _Q_KEYS
        if key in answers
    ]
    if pairs:
        lines.append("")
        lines.append("<blockquote>" + "\n".join(pairs) + "</blockquote>")

    if interests:
        lines.append("")
        lines.append("🏷 " + " · ".join(interests[:6]))

    if not user.get("voice_id"):
        lines.append("\n🎙 <i>Без голосового — редкость. Спроси почему 😏</i>")

    lines.append("📸 <i>Фото откроется, если совпадёте.</i>")
    return "\n".join(lines)


def photo_tease_caption(user: dict[str, Any]) -> str:
    return (
        f"📸 Фото <b>{user['name']}</b> скрыто.\n\n"
        "Оно откроется, если вы совпадёте. Или можно подглядеть за "
        "⭐ Telegram Stars — но тогда интрига умрёт 🤷"
    )


def short_profile(user: dict[str, Any]) -> str:
    answers = json.loads(user.get("answers") or "{}")
    interests = json.loads(user.get("interests") or "[]")
    verified = " 🛡 верифицирован" if user.get("verified") else ""
    lines = [
        f"🧪 <b>{esc(user.get('name') or '—')}</b>, {esc(user.get('age') or '—')} — "
        f"{esc(user.get('city') or '—')}{verified}",
        f"<i>Ищу: {user.get('seek') or '—'} · Мэтчей: {user.get('matches_cnt') or 0}</i>",
        "",
    ]
    pairs = [f"{q['q']} → <b>{answers[key]}</b>" for key, q in _Q_MAP.items() if key in answers]
    if pairs:
        lines.append("<blockquote>" + "\n".join(pairs) + "</blockquote>")
    if interests:
        lines.append("🏷 " + " · ".join(interests))
    if not user.get("voice_id"):
        lines.append("\n🎙 Голосового нет — добавь, это +50% к мэтчам.")
    return "\n".join(lines)


def missing_steps(user: dict[str, Any]) -> list[str]:
    steps: list[str] = []
    if not user.get("name"):
        steps.append("имя")
    if not user.get("age"):
        steps.append("возраст")
    if not user.get("gender"):
        steps.append("пол")
    if not user.get("seek"):
        steps.append("кого ищешь")
    if not user.get("city"):
        steps.append("город")
    if not user.get("answers") or user.get("answers") == "{}":
        steps.append("ответы на вопросы")
    if not user.get("photo_id"):
        steps.append("фото")
    if not user.get("interests") or user.get("interests") == "[]":
        steps.append("интересы")
    if not user.get("voice_id"):
        steps.append("голосовое (необязательно)")
    return steps


INTEREST_EMOJI = {tag: "•" for tag in INTERESTS}
