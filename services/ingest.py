"""Загрузка контента: тянем RSS в фоне и складываем в базу."""
from __future__ import annotations

import asyncio
import logging

import db
from services import news

log = logging.getLogger("himiya.ingest")


async def seed() -> int:
    """Засев источников + авто-чистка при смене контент-набора.

    Когда меняем список изданий (например, перешли с иностранных на русские),
    старые статьи и источники вычищаются целиком — иначе в ленте всплывёт
    то, чего там быть не должно.
    """
    stored = await db.get_meta("news_version")
    if stored != str(news.NEWS_VERSION):
        await db.wipe_news()
        await db.set_meta("news_version", str(news.NEWS_VERSION))
        log.info("Лента: контент-набор v%s — старые источники и статьи очищены", news.NEWS_VERSION)

    await db.deactivate_sources_except([url for _, _, url in news.SEED_SOURCES])
    return await db.seed_sources(news.SEED_SOURCES)


async def refresh_sources(limit: int = 8) -> int:
    """Обходит источники, которым пора обновиться. Возвращает число новых статей."""
    await seed()
    sources = await db.sources_to_fetch()
    if not sources:
        return 0

    added = 0
    for source in sources[:limit]:
        try:
            items = await asyncio.to_thread(
                news.fetch_feed, source["url"], source["topic"], source["name"]
            )
        except Exception as exc:  # битый фид — не повод падать
            log.warning("feed fail %s: %s", source["url"], exc)
            await db.mark_source(source["id"], ok=False)
            continue

        fresh = 0
        for item in items:
            if await db.add_article(**item):
                fresh += 1
        added += fresh
        await db.mark_source(source["id"], ok=True)
        log.info("%s: +%s статей", source["name"], fresh)
    return added
