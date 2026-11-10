"""Точка входа бота «Химия».

Запуск:  python bot.py
Нужен BOT_TOKEN в .env (см. .env.example).
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import threading
import time

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from storage import SQLiteStorage
from aiogram import BaseMiddleware

import db
from config import (
    BOT_NAME,
    BOT_TOKEN,
    DIGEST_HOUR,
    DIGEST_TZ_OFFSET,
    INGEST_MINUTES,
)
from handlers import admin, chat, demo, feed, match, news, profile, registration, start
from handlers.match import notify_expired
from services import ingest

LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
_log_handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
try:
    os.makedirs(LOG_DIR, exist_ok=True)
    _log_handlers.append(logging.FileHandler(os.path.join(LOG_DIR, "bot.log"), encoding="utf-8"))
except OSError:
    # на некоторых хостингах папка проекта только для чтения — живём на stdout
    LOG_DIR = "/tmp/himiya_logs"
    os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=_log_handlers,
)
logging.getLogger("aiogram.event").setLevel(logging.INFO)
log = logging.getLogger("himiya")

EXPIRY_CHECK_SECONDS = 15 * 60

# ── watchdog: если event loop встал, никто не заметит кроме отдельного потока ──
_last_tick = time.time()
WATCHDOG_LIMIT = 120  # секунд без признаков жизни → принудительный рестарт


def tick() -> None:
    global _last_tick
    _last_tick = time.time()


def watchdog_thread() -> None:
    while True:
        time.sleep(20)
        idle = time.time() - _last_tick
        if idle > WATCHDOG_LIMIT:
            log.error("🛑 watchdog: цикл молчит %.0f с — принудительный перезапуск", idle)
            os._exit(3)


class LogUpdates(BaseMiddleware):
    """Пишем в лог каждый апдейт — иначе непонятно, доходит ли он до бота."""

    async def __call__(self, handler, event, data):
        tick()
        try:
            from aiogram.types import Update

            user = data.get("event_from_user")
            kind, payload = "other", ""
            if isinstance(event, Update):
                if event.message:
                    kind = "message"
                    payload = event.message.text or ("[медиа] " + event.message.content_type)
                elif event.callback_query:
                    kind = "callback"
                    payload = event.callback_query.data or ""
                elif event.pre_checkout_query:
                    kind = "payment"
            log.info(
                "⬇️ %-8s %s (@%s): %s",
                kind, user.id if user else "?", getattr(user, "username", None),
                str(payload)[:70],
            )
        except Exception:
            pass
        return await handler(event, data)


class ErrorsMiddleware(BaseMiddleware):
    """Гасим некритичные ошибки Telegram и ВСЕГДА снимаем «крутилку» с кнопки.

    Без этого любое 400-е («message is not modified», «query is too old»)
    оставляло кнопку в вечной загрузке — со стороны выглядело как «бот завис».
    """

    async def __call__(self, handler, event, data):
        from aiogram.exceptions import TelegramBadRequest
        from aiogram.types import Update

        try:
            return await handler(event, data)
        except TelegramBadRequest as exc:
            text = str(exc)
            soft = ("message is not modified" in text or "query is too old" in text
                    or "message to edit not found" in text)
            if soft:
                log.info("некритичная ошибка Telegram: %s", text[:90])
            else:
                log.exception("TelegramBadRequest: %s", text[:200])
            await self._release(event)
            if not soft:
                await self._apologize(event)
            return None
        except Exception:
            log.exception("Ошибка в обработчике")
            await self._release(event)
            await self._apologize(event)
            return None

    async def _release(self, event) -> None:
        from aiogram.types import Update

        if isinstance(event, Update) and event.callback_query:
            try:
                await event.callback_query.answer()
            except Exception:
                pass

    async def _apologize(self, event) -> None:
        from aiogram.types import Update

        if not isinstance(event, Update):
            return
        chat_id = None
        if event.message:
            chat_id = event.message.chat.id
        elif event.callback_query and event.callback_query.message:
            chat_id = event.callback_query.message.chat.id
        if not chat_id:
            return
        try:
            await event.bot.send_message(
                chat_id, "😔 Что-то пошло не так. Попробуй ещё раз или напиши /start"
            )
        except Exception:
            pass


class UserLockMiddleware(BaseMiddleware):
    """Один пользователь — один обработчик за раз.

    Telegram иногда доставляет апдейт повторно; два параллельных обработчика
    читали одно состояние и оба писали в него — оттуда и ошибки, и дубли.
    """

    def __init__(self) -> None:
        self._locks: dict[int, asyncio.Lock] = {}

    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        if not user:
            return await handler(event, data)
        lock = self._locks.setdefault(user.id, asyncio.Lock())
        async with lock:
            return await handler(event, data)


def build_dispatcher() -> Dispatcher:
    dp = Dispatcher(storage=SQLiteStorage())
    dp.update.outer_middleware(ErrorsMiddleware())
    dp.update.outer_middleware(LogUpdates())
    dp.update.middleware(UserLockMiddleware())
    # Порядок важен: fallback-роутер чата идёт последним
    dp.include_router(admin.router)
    dp.include_router(demo.router)
    dp.include_router(registration.router)
    dp.include_router(feed.router)
    dp.include_router(match.router)
    dp.include_router(chat.router)
    dp.include_router(news.router)
    dp.include_router(profile.router)
    dp.include_router(start.router)
    dp.include_router(chat.fallback_router)
    return dp


async def expiry_worker(bot: Bot) -> None:
    """Раз в 15 минут гасит мэтчи, где не было сообщений."""
    while True:
        try:
            expired = await db.expire_matches()
            if expired:
                log.info("Сгорело мэтчей: %s", len(expired))
                await notify_expired(bot, expired)
        except Exception as exc:  # воркер не должен падать
            log.warning("expiry_worker: %s", exc)
        await asyncio.sleep(EXPIRY_CHECK_SECONDS)


async def ingest_worker() -> None:
    """Тянет RSS каждые INGEST_MINUTES минут — контент должен быть свежим."""
    while True:
        try:
            added = await ingest.refresh_sources()
            if added:
                log.info("Лента: +%s новых статей", added)
        except Exception as exc:
            log.warning("ingest_worker: %s", exc)
        await asyncio.sleep(INGEST_MINUTES * 60)


async def digest_worker(bot: Bot) -> None:
    """Раз в ~10 минут проверяет, не пора ли слать утренний дайджест."""
    from datetime import datetime, timedelta, timezone

    while True:
        try:
            local = datetime.now(timezone.utc) + timedelta(hours=DIGEST_TZ_OFFSET)
            if local.hour == DIGEST_HOUR:
                day = local.date().isoformat()
                for uid in await db.users_for_digest():
                    if await db.digest_already_sent(uid, day):
                        continue
                    try:
                        sent = await news.send_digest(bot, uid)
                        if sent:
                            await db.mark_digest_sent(uid, day)
                    except Exception as exc:
                        log.debug("digest %s: %s", uid, exc)
                    await asyncio.sleep(0.05)
        except Exception as exc:
            log.warning("digest_worker: %s", exc)
        await asyncio.sleep(600)


async def heartbeat_worker() -> None:
    """Отметка «я жив» раз в 30 секунд — по ней видно, не заморожен ли процесс."""
    while True:
        tick()
        try:
            await db.heartbeat()
        except Exception as exc:
            log.warning("heartbeat: %s", exc)
        await asyncio.sleep(30)


def acquire_single_instance_lock():
    """Второй экземпляр бота — главная причина «команды не работают»:
    два поллера рвут друг другу getUpdates. Держим файловую блокировку."""
    import fcntl

    handle = open(os.path.join(LOG_DIR, "bot.lock"), "w")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print(
            "❌ Уже запущен другой экземпляр бота (bot.lock занят).\n"
            "   Останови его: pkill -f 'python3 -u [b]ot.py'",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return handle


async def main() -> None:
    _lock = acquire_single_instance_lock()
    threading.Thread(target=watchdog_thread, daemon=True).start()

    if not BOT_TOKEN:
        print(
            "❌ Нет BOT_TOKEN.\n"
            "Скопируй .env.example → .env и вставь токен из @BotFather:\n"
            "  cp .env.example .env && nano .env\n"
            "Или: BOT_TOKEN=123:ABC python bot.py",
            file=sys.stderr,
        )
        raise SystemExit(1)

    await db.init()
    from aiogram.client.session.aiohttp import AiohttpSession

    session = AiohttpSession(timeout=20)
    bot = Bot(
        token=BOT_TOKEN,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = build_dispatcher()

    workers = [
        asyncio.create_task(expiry_worker(bot)),
        asyncio.create_task(ingest_worker()),
        asyncio.create_task(digest_worker(bot)),
        asyncio.create_task(heartbeat_worker()),
    ]
    log.info("🧪 %s запущена", BOT_NAME)
    try:
        await bot.delete_webhook(drop_pending_updates=False)
        # Короткий polling_timeout + бесконечный ретрай: прокси песочницы рвёт
        # долгие соединения, и без ретрая бот «жив», но апдейты не забирает.
        while True:
            try:
                await dp.start_polling(
                    bot,
                    polling_timeout=10,
                    allowed_updates=dp.resolve_used_update_types(),
                )
                log.warning("Polling завершился штатно — перезапускаю через 3 с")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.error("Polling упал: %s — перезапуск через 3 с", exc)
            await asyncio.sleep(3)
    finally:
        for task in workers:
            task.cancel()
        await db.close()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    # SystemExit пробрасываем: по коду 2 супервизор понимает,
    # что запущен другой экземпляр, и не пытается перезапускать.
