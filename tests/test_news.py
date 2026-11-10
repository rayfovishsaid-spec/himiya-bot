"""Автотест ленты: парсинг RSS/Atom, дедуп, ранжирование, шаринг, «вы оба читали».

Запуск:  python tests/test_news.py
Живой тест сети (необязательно):  NET=1 python tests/test_news.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db  # noqa: E402
from services import news  # noqa: E402
from texts import PROFILE_QUESTIONS  # noqa: E402

RSS_FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Test</title>
  <item>
    <title>GTA 6 gets PS5 Pro enhancements</title>
    <link>https://example.com/a1</link>
    <description>&lt;p&gt;Rockstar подробнее рассказала о &lt;b&gt;графике&lt;/b&gt; и производительности.&lt;/p&gt;</description>
    <pubDate>Mon, 10 Nov 2026 08:00:00 +0000</pubDate>
    <enclosure url="https://example.com/pic1.jpg" type="image/jpeg"/>
  </item>
  <item>
    <title>Another story about football transfers</title>
    <link>https://example.com/a2</link>
    <description>Short text</description>
    <pubDate>Mon, 10 Nov 2026 07:00:00 +0000</pubDate>
  </item>
  <item>
    <title>Broken item without link</title>
    <description>should be skipped</description>
  </item>
</channel></rss>""".encode()

ATOM_FIXTURE = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>Atom test</title>
  <entry>
    <title>Atom entry about music</title>
    <link href="https://example.com/atom1"/>
    <summary>New album announced</summary>
    <updated>2026-11-10T09:30:00Z</updated>
  </entry>
</feed>""".encode()


class FakeBot:
    def __init__(self) -> None:
        self.outbox: list[tuple[int, str, dict]] = []

    async def send_message(self, chat_id, text, **kwargs):
        self.outbox.append((chat_id, text, kwargs))

        class Msg:
            message_id = len(self.outbox)

        return Msg()

    async def send_photo(self, chat_id, photo, caption=None, **kwargs):
        self.outbox.append((chat_id, caption or "", kwargs))
        return None

    def texts_for(self, uid: int) -> list[str]:
        return [t for chat, t, _ in self.outbox if chat == uid]


async def make_user(uid: int, name: str, interests: list[str]) -> None:
    await db.ensure_user(uid, f"user{uid}")
    await db.set_field(uid, "name", name)
    await db.set_field(uid, "age", 27)
    await db.set_field(uid, "city", "Лондон")
    await db.set_field(uid, "gender", "m" if uid % 2 else "f")
    await db.set_field(uid, "seek", "f" if uid % 2 else "m")
    await db.set_field(uid, "photo_id", f"photo{uid}")
    await db.set_answers(uid, {q["key"]: q["options"][0] for q in PROFILE_QUESTIONS})
    await db.set_interests(uid, interests)


async def main() -> None:
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    await db.init(tmp.name)

    print("1) Парсинг RSS: теги вычищены, картинка найдена, битое пропущено")
    items = news.parse_feed(RSS_FIXTURE, "cinema", "Test")
    assert len(items) == 2, f"ждали 2 валидные новости, получили {len(items)}"
    assert "<b>" not in items[0]["summary"], "HTML должен быть вычищен"
    assert items[0]["image_url"] == "https://example.com/pic1.jpg"
    assert items[0]["published_at"].startswith("2026-11-10")
    print(f"   {items[0]['title']} | {items[0]['summary'][:40]}… ✅")

    print("2) Парсинг Atom")
    atom = news.parse_feed(ATOM_FIXTURE, "music", "AtomTest")
    assert len(atom) == 1 and atom[0]["url"] == "https://example.com/atom1"
    print(f"   {atom[0]['title']} ✅")

    print("3) Дедуп по URL")
    added_first = await db.add_article(**items[0])
    added_second = await db.add_article(**items[0])
    assert added_first is True and added_second is False
    print("   повторная вставка отклонена ✅")

    print("4) Темы из интересов анкеты (не спрашиваем дважды)")
    topics = news.topics_from_interests(["кино", "спорт", "путешествия"])
    assert set(topics) == {"cinema", "sport", "travel"}, topics
    empty = news.topics_from_interests(["йога"])
    assert empty == ["kind"], empty  # йога → «милые истории» через fallback
    print(f"   кино+спорт+путешествия → {topics} ✅")

    print("5) Ранжирование: свежее выше, похожие заголовки схлопываются")
    old = dict(items[1], published_at="2020-01-01T00:00:00+00:00", url_hash="h-old")
    fresh = dict(items[0], published_at=news.datetime.now(news.timezone.utc).isoformat(), url_hash="h-fresh")
    dup = dict(items[0], title="GTA 6 gets PS5 Pro enhancements explained", url_hash="h-dup")
    picked = news.rank([old, fresh, dup], limit=3)
    assert picked[0]["url_hash"] == "h-fresh", "свежая должна быть первой"
    assert all(p["url_hash"] != "h-dup" for p in picked), "дубль по смыслу должен отвалиться"
    print(f"   порядок: {[p['url_hash'] for p in picked]} ✅")

    print("6) Источники сеются в базу, всего их", len(news.SEED_SOURCES))
    seeded = await db.seed_sources(news.SEED_SOURCES)
    seeded_again = await db.seed_sources(news.SEED_SOURCES)
    assert seeded == len(news.SEED_SOURCES) and seeded_again == 0
    print(f"   засеяно {seeded}, повторно — {seeded_again} ✅")

    print("7) Пользователь выбирает темы, лента отдаёт только их")
    await make_user(1, "Аня", ["кино", "игры"])
    await db.set_user_topics(1, ["cinema"])
    await make_user(2, "Борис", ["игры"])
    await db.set_user_topics(2, ["cinema"])
    pool = await db.articles_for_user(1, ["cinema"], hours=24 * 365 * 10)
    assert pool and all(a["topic"] in ("cinema",) for a in pool)
    print(f"   в пуле {len(pool)} статей по теме cinema ✅")

    print("8) Дайджест уходит карточками")
    from handlers import news as news_handlers

    bot = FakeBot()
    sent = await news_handlers.send_digest(bot, 1)
    assert sent >= 1, "дайджест должен отправить хотя бы одну карточку"
    assert "Доброе утро" in bot.texts_for(1)[0]
    card = bot.texts_for(1)[1]
    assert "Открыть статью" not in card  # кнопка, а не текст
    assert "example.com" in card, "ссылка должна быть в карточке"
    print(f"   отправлено карточек: {sent} ✅")

    print("9) Шаринг в чат + реакция + «вы оба читали»")
    mid = await db.create_match(1, 2)
    await db.unlock_match(mid)
    article = (await db.get_article(1)) or (await db.articles_for_user(2, ["cinema"], 1e9))[0]

    await db.log_share(mid, 1, 2, article["id"])
    shares = await db.fetchall("SELECT * FROM shares WHERE match_id = ?", (mid,))
    assert len(shares) == 1
    text = news.shared_text("Аня", article)
    assert "поделился" in text and article["url"] in text
    print("   карточка шарится внутрь чата ✅")

    await db.mark_article(2, article["id"], "saved")
    common = await db.common_reading(1)
    assert common, "если оба сохранили одну статью — должна найтись общая тема"
    assert common[0]["partner_name"] == "Борис"
    print(f"   «вы оба читали»: {common[0]['title'][:40]} → мэтч с {common[0]['partner_name']} ✅")

    print("10) Лимиты тем и мусорные ссылки")
    assert await db.get_user_topics(1) == ["cinema"]
    assert db.profile_complete(await db.get_user(1))
    print("   ок ✅")

    print("11) ФИЛЬТР НЕГАТИВА: войны, смерти и скандалы не проходят")
    bad = [
        "Война и мир в новой экранизации",
        "Умер актёр Юрий Каюров",
        "Драка на матче прервала игру",
        "Пожар в музее уничтожил картины",
        "Судебное дело о нарушении прав",
        "Рассел Брэнд проведет в тюрьме десять лет",
        "Скандал на премьере: актёры поссорились",
    ]
    for title in bad:
        assert not news.is_positive(title), f"должно отсекаться: {title}"
    print(f"   отсечено {len(bad)} плохих заголовков ✅")

    print("12) Ловушки словаря: доброе не режем")
    good = [
        "Искусство батика: как создаются картины",
        "Судьба художника: путь к признанию",
        "Балет «Щелкунчик» возвращается на сцену",
        "10 рецептов нежной пасты",
        "Сборная России победила в товарищеском матче",
        "Приют для кошек нашёл дом для 40 котят",
    ]
    for title in good:
        assert news.is_positive(title), f"не должно отсекаться: {title}"
    print(f"   пропущено {len(good)} хороших заголовков ✅ (искусство ≠ иск, судьба ≠ суд)")

    print("13) Негатив не попадает в базу даже если источник его прислал")
    bad_feed = RSS_FIXTURE.replace(
        "GTA 6 gets PS5 Pro enhancements".encode(),
        "Война обостряется: погибли люди".encode(),
    )
    parsed_bad = news.parse_feed(bad_feed, "cinema", "Test")
    titles = [a["title"] for a in parsed_bad]
    assert not any("Война" in t for t in titles), titles
    print(f"   в базу прошло только {len(parsed_bad)} из 2 статей ✅")

    print("14) «Добрые» слова поднимают материал в ранге")
    now = news.datetime.now(news.timezone.utc).isoformat()
    boring = {"title": "Отчёт о мероприятии", "summary": "", "published_at": now,
              "url_hash": "b1", "shares": 0, "likes": 0}
    warm = {"title": "Фестиваль уличного искусства собрал 10 тысяч гостей",
            "summary": "Праздник, музыка, танцы и красота", "published_at": now,
            "url_hash": "b2", "shares": 0, "likes": 0}
    ranked = news.rank([boring, warm], limit=2)
    assert ranked[0]["url_hash"] == "b2", ranked
    print("   добрый материал выше нейтрального ✅")

    if os.getenv("NET") == "1":
        print("11) Живой фид (сеть)")
        live = news.fetch_feed("https://www.gastronom.ru/rss", "food", "Гастрономъ")
        assert live, "живой фид должен вернуть элементы"
        picked_live = news.rank(
            [dict(a, url_hash=f"live{i}") for i, a in enumerate(live)], limit=3
        )
        print(f"   живой фид: {len(live)} хороших новостей, топ: {picked_live[0]['title'][:55]} ✅")

    await db.close()
    os.unlink(tmp.name)
    print("\n🎉 Все тесты ленты прошли")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    finally:
        sys.stdout.flush()
        os._exit(0)  # фоновый поток aiosqlite не должен держать процесс
