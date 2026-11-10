"""«Лента»: темы из интересов → карточки контента → шаринг в чат с мэтчем.

Ключевая мысль: контент здесь существует ради разговора.
Поэтому на каждой карточке главная кнопка — не «Открыть», а «Поделиться с мэтчем».
"""
from __future__ import annotations

import html

from aiogram import Bot, F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import db
from utils import safe_edit
from keyboards import (
    BTN_DIGEST,
    BTN_NEWS,
    BTN_SAVED,
    article_kb,
    digest_intro_kb,
    main_menu,
    saved_kb,
    share_reaction_kb,
    share_target_kb,
    topics_kb,
)
from services import news
from states import Report
from texts import NEED_PROFILE

router = Router(name="news")

REACTIONS = {
    "fire": "🔥 Класс",
    "hmm": "🤔 Спорно",
    "talk": "💬 Обсудить",
}


# ───────────────────────────── темы ─────────────────────────────
async def open_topics(message_or_call, uid: int, editing: bool = False) -> None:
    current = await db.get_user_topics(uid)
    if not current:
        user = await db.get_user(uid)
        import json

        interests = json.loads(user.get("interests") or "[]") if user else []
        current = news.topics_from_interests(interests)
        await db.set_user_topics(uid, current)

    text = (
        "⚙️ <b>Мои темы</b>\n\n"
        "Выбери, что тебе реально интересно — я буду приносить 3–5 материалов в день "
        "и только по делу.\n\n"
        f"<i>Сейчас выбрано: {len(current)}</i>"
    )
    markup = topics_kb(current)
    if editing:
        await message_or_call.edit_text(text, reply_markup=markup)
    else:
        await message_or_call.answer(text, reply_markup=markup)


@router.callback_query(F.data.startswith("topic:"))
async def cb_topic(call: CallbackQuery) -> None:
    value = call.data.split(":", 1)[1]
    selected = await db.get_user_topics(call.from_user.id)

    if value == "done":
        if not selected:
            await call.answer("Выбери хотя бы одну тему", show_alert=True)
            return
        await safe_edit(call.message, 
            f"✅ Готово, темы: <b>{len(selected)}</b>\n\nПринесу первое прямо сейчас."
        )
        await call.answer()
        await send_next_article(call.bot, call.from_user.id)
        return

    if value in selected:
        selected.remove(value)
    else:
        if len(selected) >= 8:
            await call.answer("Максимум 8 тем — иначе лента станет шумом", show_alert=True)
            return
        selected.append(value)

    await db.set_user_topics(call.from_user.id, selected)
    await safe_edit(call.message, 
        f"⚙️ <b>Мои темы</b>\n\nВыбрано: {len(selected)}\n\n"
        "Отмечай, что интересно — дайджест соберётся сам.",
        reply_markup=topics_kb(selected),
    )
    await call.answer()


@router.message(Command("topics"))
async def cmd_topics(message: Message) -> None:
    await open_topics(message, message.from_user.id)


@router.callback_query(F.data == "art:topics")
async def cb_art_topics(call: CallbackQuery) -> None:
    await open_topics(call.message, call.from_user.id, editing=False)
    await call.answer()


# ───────────────────────────── карточки ─────────────────────────────
async def _share_ready_matches(uid: int) -> list[dict]:
    matches = await db.user_matches(uid)
    return [m for m in matches if m["unlocked"]]


async def card_payload(article: dict, uid: int) -> tuple[str, object]:
    can_share = bool(await _share_ready_matches(uid))
    text = news.card_text(article) + f"\n\n{article['url']}"
    return text, article_kb(article["id"], article["url"], can_share)


async def send_article(bot: Bot, chat_id: int, uid: int, article: dict) -> None:
    text, markup = await card_payload(article, uid)
    await db.mark_article(uid, article["id"], "seen")
    await bot.send_message(chat_id, text, reply_markup=markup)


async def send_next_article(bot: Bot, uid: int) -> None:
    user = await db.get_user(uid)
    if not user or not db.profile_complete(user):
        await bot.send_message(uid, NEED_PROFILE)
        return

    topics = await db.get_user_topics(uid)
    if not topics:
        await bot.send_message(uid, "Сначала выбери темы 👇")
        await open_topics(_Sender(bot, uid), uid)
        return

    pool = await db.articles_for_user(uid, topics, hours=96, limit=40)
    picked = news.rank(pool, limit=1)

    if not picked:
        await bot.send_message(
            uid,
            "📭 По твоим темам пока пусто.\n\n"
            "Источники обновляются каждые 30 минут — загляни позже. "
            "Или добавь ещё пару тем: /topics",
        )
        return

    await send_article(bot, uid, uid, picked[0])

    # Бонус: «вы оба это читали» — лучший повод написать первым
    common = await db.common_reading(uid, limit=1)
    if common:
        item = common[0]
        await bot.send_message(
            uid,
            f"👀 Кстати: <b>{html.escape(item['partner_name'])}</b> тоже сохранил(а) "
            f"«{html.escape(item['title'][:60])}». Это уже почти готовый разговор.",
            reply_markup=share_target_kb(item["id"], [{
                "partner_name": item["partner_name"], "id": item["match_id"],
            }]),
        )
        await db.mark_article(uid, item["id"], "seen")


class _Sender:
    """Обёртка, чтобы open_topics могла работать и по message, и по боту."""

    def __init__(self, bot: Bot, uid: int) -> None:
        self.bot = bot
        self.uid = uid

    async def answer(self, text: str, **kwargs) -> None:
        await self.bot.send_message(self.uid, text, **kwargs)


@router.message(Command("news"))
async def cmd_news(message: Message) -> None:
    await send_next_article(message.bot, message.from_user.id)


@router.message(StateFilter(None), F.text == BTN_NEWS)
async def btn_news(message: Message) -> None:
    await send_next_article(message.bot, message.from_user.id)


@router.message(Command("saved"))
@router.message(StateFilter(None), F.text == BTN_SAVED)
async def cmd_saved(message: Message) -> None:
    items = await db.saved_articles(message.from_user.id)
    if not items:
        await message.answer(
            "🔖 Закладок нет.\n\nЖми «🔖 В закладки» на карточке — и материал будет ждать здесь."
        )
        return
    await message.answer(
        f"🔖 <b>Закладки</b> — {len(items)}\n\nВыбери, что перечитать или кому переслать:",
        reply_markup=saved_kb(items),
    )


@router.callback_query(F.data.startswith("art:card:"))
async def cb_saved_card(call: CallbackQuery) -> None:
    article = await db.get_article(int(call.data.split(":")[2]))
    if not article:
        await call.answer("Материал недоступен", show_alert=True)
        return
    await send_article(call.bot, call.from_user.id, call.from_user.id, article)
    await call.answer()


@router.callback_query(F.data.startswith("art:skip:"))
async def cb_art_skip(call: CallbackQuery) -> None:
    await db.mark_article(call.from_user.id, int(call.data.split(":")[2]), "seen")
    await call.message.edit_reply_markup(reply_markup=None)
    await call.answer()
    await send_next_article(call.bot, call.from_user.id)


@router.callback_query(F.data.startswith("art:save:"))
async def cb_art_save(call: CallbackQuery) -> None:
    await db.mark_article(call.from_user.id, int(call.data.split(":")[2]), "saved")
    await call.answer("🔖 В закладках")


@router.callback_query(F.data == "art:noshare")
async def cb_art_noshare(call: CallbackQuery) -> None:
    await call.answer("Пока некому 🙂 Сначала мэтч и Ледокол", show_alert=True)


@router.callback_query(F.data.startswith("art:report:"))
async def cb_art_report(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Report.reason)
    await state.update_data(report_target=0, report_article=int(call.data.split(":")[2]))
    await call.message.answer("🚩 Что не так с материалом? Напиши одним сообщением.")
    await call.answer()


# ───────────────────────────── шаринг в чат ─────────────────────────────
@router.callback_query(F.data.startswith("art:share:"))
async def cb_art_share(call: CallbackQuery) -> None:
    article_id = int(call.data.split(":")[2])
    article = await db.get_article(article_id)
    if not article:
        await call.answer("Материал недоступен", show_alert=True)
        return

    matches = await _share_ready_matches(call.from_user.id)
    if not matches:
        await call.answer(
            "Открытых чатов пока нет. Пройди Ледокол с кем-нибудь — и сможешь "
            "кидать друг другу такие карточки.",
            show_alert=True,
        )
        return

    await call.message.answer(
        "💌 Кому отправим? Карточка появится прямо в вашем чате — уходить из бота не надо.",
        reply_markup=share_target_kb(article_id, matches),
    )
    await call.answer()


@router.callback_query(F.data.startswith("shareto:"))
async def cb_share_to(call: CallbackQuery) -> None:
    _, art_s, mid_s = call.data.split(":")
    article = await db.get_article(int(art_s))
    match = await db.get_match(int(mid_s))
    if not article or not match or call.from_user.id not in (match["a_id"], match["b_id"]):
        await call.answer("Не получилось 🙂", show_alert=True)
        return
    if not match["unlocked"] or match["closed"]:
        await call.answer("Этот чат ещё не открыт", show_alert=True)
        return

    sender = await db.get_user(call.from_user.id)
    partner_id = match["b_id"] if match["a_id"] == call.from_user.id else match["a_id"]

    sent = await call.bot.send_message(
        partner_id,
        news.shared_text(sender["name"], article),
        reply_markup=share_reaction_kb(match["id"], article["id"]),
        disable_web_page_preview=True,
    )
    await db.save_message(match["id"], call.from_user.id, partner_id, sent.message_id)
    await db.touch_match(match["id"])
    await db.log_share(match["id"], call.from_user.id, partner_id, article["id"])

    await call.message.edit_reply_markup(reply_markup=None)
    await call.message.answer(
        f"✅ Отправлено <b>{html.escape(match['partner_name'])}</b>. "
        "Как отреагирует — увидишь здесь."
    )
    await call.answer("💌")


@router.callback_query(F.data.startswith("art:back:"))
async def cb_art_back(call: CallbackQuery) -> None:
    article = await db.get_article(int(call.data.split(":")[2]))
    if article:
        text, markup = await card_payload(article, call.from_user.id)
        await safe_edit(call.message, text, reply_markup=markup, disable_web_page_preview=True)
    await call.answer()


@router.callback_query(F.data.startswith("nreact:"))
async def cb_reaction(call: CallbackQuery) -> None:
    _, mid_s, art_s, code = call.data.split(":")
    match = await db.get_match(int(mid_s))
    article = await db.get_article(int(art_s))
    if not match or not article or call.from_user.id not in (match["a_id"], match["b_id"]):
        await call.answer("Не твой мэтч", show_alert=True)
        return

    reactor = await db.get_user(call.from_user.id)
    other_id = match["b_id"] if match["a_id"] == call.from_user.id else match["a_id"]
    label = REACTIONS.get(code, "💬")

    sent = await call.bot.send_message(
        other_id,
        f"💬 <b>{html.escape(reactor['name'])}</b>: {label}\n"
        f"<i>на «{html.escape(article['title'][:70])}»</i>",
    )
    await db.save_message(match["id"], call.from_user.id, other_id, sent.message_id)
    await db.touch_match(match["id"])
    await call.message.edit_reply_markup(reply_markup=None)
    await call.answer(f"Отправлено: {label}")


# ───────────────────────────── дайджест ─────────────────────────────
async def send_digest(bot: Bot, uid: int) -> int:
    user = await db.get_user(uid)
    if not user:
        return 0
    topics = await db.get_user_topics(uid)
    if not topics:
        return 0

    pool = await db.articles_for_user(uid, topics, hours=24, limit=40)
    picked = news.rank(pool, limit=3)
    if not picked:
        return 0

    await bot.send_message(
        uid,
        news.digest_intro(user.get("name") or "друг", len(picked)),
        reply_markup=digest_intro_kb(),
    )
    for article in picked:
        await send_article(bot, uid, uid, article)
    return len(picked)


@router.message(StateFilter(None), F.text == BTN_DIGEST)
async def btn_digest(message: Message) -> None:
    sent = await send_digest(message.bot, message.from_user.id)
    if not sent:
        await message.answer("Свежего пока нет — загляни через полчаса 📭", reply_markup=main_menu())
