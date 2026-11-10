"""Клавиатуры."""
from __future__ import annotations

from typing import Iterable

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import PHOTO_PEEK_STARS
from texts import INTERESTS

BTN_FEED = "🔍 Искать"
BTN_MATCHES = "💬 Мои мэтчи"
BTN_PROFILE = "👤 Анкета"
BTN_LIKED_ME = "💘 Кто меня лайкнул"
BTN_NEWS = "📰 Лента"
BTN_SAVED = "🔖 Закладки"
BTN_DIGEST = "☕ Дайджест"

GENDERS = [("Парень", "m"), ("Девушка", "f"), ("Другое", "x")]
SEEKS = [("Девушек", "f"), ("Парней", "m"), ("Всех", "any")]


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_FEED), KeyboardButton(text=BTN_MATCHES)],
            [KeyboardButton(text=BTN_NEWS), KeyboardButton(text=BTN_DIGEST)],
            [KeyboardButton(text=BTN_SAVED), KeyboardButton(text=BTN_PROFILE)],
            [KeyboardButton(text=BTN_LIKED_ME)],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выбери действие 🧪",
    )


def gender_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for label, value in GENDERS:
        b.button(text=label, callback_data=f"gender:{value}")
    b.adjust(3)
    return b.as_markup()


def seek_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for label, value in SEEKS:
        b.button(text=label, callback_data=f"seek:{value}")
    b.adjust(3)
    return b.as_markup()


def options_kb(q_index: int, options: Iterable[str], prefix: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for i, option in enumerate(options):
        b.button(text=option, callback_data=f"{prefix}:{q_index}:{i}")
    b.adjust(1)
    return b.as_markup()


def interests_kb(selected: list[str]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for tag in INTERESTS:
        mark = "✅ " if tag in selected else ""
        b.button(text=f"{mark}{tag}", callback_data=f"int:{tag}")
    b.button(text=f"Готово ({len(selected)}) →", callback_data="int:done")
    b.adjust(2)
    return b.as_markup()


def card_kb(target_id: int, has_voice: bool = False) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="❤️ Хочу познакомиться", callback_data=f"like:{target_id}"),
        InlineKeyboardButton(text="➖ Дальше", callback_data=f"skip:{target_id}"),
    )
    b.row(
        InlineKeyboardButton(
            text=f"👀 Подглядеть фото — {PHOTO_PEEK_STARS} ⭐", callback_data=f"peek:{target_id}"
        )
    )
    b.row(
        InlineKeyboardButton(text="🎙 Голос", callback_data=f"voice:{target_id}"),
        InlineKeyboardButton(text="🚩 Жалоба", callback_data=f"rep:{target_id}"),
    )
    return b.as_markup()


def matches_kb(matches: list[dict]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for m in matches:
        if m["unlocked"]:
            b.button(text=f"💬 {m['partner_name']}", callback_data=f"open:{m['id']}")
        else:
            b.button(text=f"🧊 Ледокол: {m['partner_name']}", callback_data=f"quest:{m['id']}")
    b.adjust(1)
    return b.as_markup()


def quest_kb(match_id: int, q_index: int, options: list[str]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for i, option in enumerate(options):
        b.button(text=option, callback_data=f"q:{match_id}:{q_index}:{i}")
    b.adjust(1)
    return b.as_markup()


def chat_kb(match_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="🚪 Выйти из чата", callback_data=f"leave:{match_id}"),
        InlineKeyboardButton(text="🚩 Жалоба", callback_data=f"rep:{match_id}"),
    )
    return b.as_markup()


def after_unlock_kb(match_id: int, partner_username: str | None) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if partner_username:
        b.row(InlineKeyboardButton(text="🔗 Открыть профиль в Telegram", url=f"https://t.me/{partner_username}"))
    b.row(InlineKeyboardButton(text="💬 Писать здесь, анонимно", callback_data=f"open:{match_id}"))
    return b.as_markup()


def liked_me_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🔍 Показать по одному", callback_data="likedme:next"))
    return b.as_markup()


# ══════════════════════════════ ЛЕНТА ══════════════════════════════
from services.news import TOPICS  # noqa: E402  (после основных клавиатур, чтобы не плодить циклы)


def topics_kb(selected: list[str]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for key, meta in TOPICS.items():
        mark = "✅ " if key in selected else ""
        b.button(text=f"{mark}{meta['emoji']} {meta['title']}", callback_data=f"topic:{key}")
    b.button(text=f"Готово ({len(selected)}) →", callback_data="topic:done")
    b.adjust(2)
    return b.as_markup()


def article_kb(article_id: int, url: str, can_share: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="📖 Открыть статью", url=url))
    share_row = [InlineKeyboardButton(text="💌 Поделиться с мэтчем", callback_data=f"art:share:{article_id}")]
    if not can_share:
        share_row = [InlineKeyboardButton(text="💌 Поделиться (нужен мэтч)", callback_data="art:noshare")]
    b.row(*share_row)
    b.row(
        InlineKeyboardButton(text="🔖 В закладки", callback_data=f"art:save:{article_id}"),
        InlineKeyboardButton(text="➖ Дальше", callback_data=f"art:skip:{article_id}"),
    )
    b.row(
        InlineKeyboardButton(text="⚙️ Мои темы", callback_data="art:topics"),
        InlineKeyboardButton(text="🚩 Жалоба", callback_data=f"art:report:{article_id}"),
    )
    return b.as_markup()


def share_target_kb(article_id: int, matches: list[dict]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for m in matches:
        b.button(
            text=f"💬 {m['partner_name']}", callback_data=f"shareto:{article_id}:{m['id']}"
        )
    b.button(text="← Назад", callback_data=f"art:back:{article_id}")
    b.adjust(1)
    return b.as_markup()


def share_reaction_kb(match_id: int, article_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="🔥 Класс", callback_data=f"nreact:{match_id}:{article_id}:fire"),
        InlineKeyboardButton(text="🤔 Спорно", callback_data=f"nreact:{match_id}:{article_id}:hmm"),
    )
    b.row(
        InlineKeyboardButton(text="💬 Обсудить", callback_data=f"nreact:{match_id}:{article_id}:talk"),
        InlineKeyboardButton(text="↩️ Ответить", callback_data=f"rt:{match_id}"),
    )
    return b.as_markup()


def saved_kb(articles: list[dict]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for art in articles:
        b.button(text=f"📰 {art['title'][:32]}…", callback_data=f"art:card:{art['id']}")
    b.adjust(1)
    return b.as_markup()


def digest_intro_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="⚙️ Настроить темы", callback_data="art:topics"))
    return b.as_markup()
