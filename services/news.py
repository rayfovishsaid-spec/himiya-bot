"""Лента: только русский язык, только добрый контент.

Принцип: это не новостник. Войны, криминала, политики, скандалов и трагедий
здесь нет вообще — фильтр стоит на входе, в момент сбора, а не в выдаче.
Остаётся то, что поднимает настроение: искусство, театр и танцы, музыка, кино,
наука, спорт, путешествия, еда, животные и просто милые истории.
"""
from __future__ import annotations

import hashlib
import html
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Optional

# ─────────────────────────── Версия контент-набора ───────────────────────────
# Меняем число → старая лента и источники вычищаются и засеиваются заново.
NEWS_VERSION = 3

# ───────────────────────────── Темы ─────────────────────────────
# tag — интерес из анкеты, чтобы не спрашивать человека дважды.
TOPICS: dict[str, dict[str, str]] = {
    "art":     {"title": "Искусство",      "emoji": "🎨", "tag": "искусство"},
    "theatre": {"title": "Театр и танцы",  "emoji": "🩰", "tag": "танцы"},
    "music":   {"title": "Музыка",         "emoji": "🎧", "tag": "музыка"},
    "cinema":  {"title": "Кино",           "emoji": "🎬", "tag": "кино"},
    "science": {"title": "Наука",          "emoji": "🔬", "tag": ""},
    "sport":   {"title": "Спорт",          "emoji": "⚽", "tag": "спорт"},
    "travel":  {"title": "Путешествия",    "emoji": "✈️", "tag": "путешествия"},
    "food":    {"title": "Еда",            "emoji": "🍳", "tag": "кулинария"},
    "kind":    {"title": "Милые истории",  "emoji": "😊", "tag": "психология"},
    "culture": {"title": "Культура и город", "emoji": "🎉", "tag": "книги"},
}

# ─────────────────── Источники: только русский язык ───────────────────
# Все проверены вживую. Никаких новостных лент «обо всём» — только
# тематические издания, где по определению нет фронтовых сводок.
SEED_SOURCES: list[tuple[str, str, str]] = [
    # искусство
    ("art",     "The Art Newspaper Russia", "https://www.theartnewspaper.ru/rss/"),
    # театр, балет, танец
    ("theatre", "О театре",                 "https://oteatre.info/feed/"),
    # музыка
    ("music",   "InterMedia",               "https://www.intermedia.ru/rss/news"),
    # кино
    ("cinema",  "Мир фантастики",           "https://www.mirf.ru/feed/"),
    ("cinema",  "Кинорепортёр",             "https://www.kinoreporter.ru/feed/"),
    # наука
    ("science",  "N + 1",                   "https://nplus1.ru/rss"),
    ("science",  "Наука и жизнь",           "https://www.nkj.ru/rss/"),
    # спорт
    ("sport",   "Sport24",                  "https://sport24.ru/rss/news"),
    # путешествия
    ("travel",  "34travel",                 "https://34travel.me/rss"),
    # еда
    ("food",    "Гастрономъ",               "https://www.gastronom.ru/rss"),
    # милые истории и лайфстайл
    ("kind",    "AdMe",                     "https://www.adme.ru/rss/"),
    # культура и город
    ("culture", "Афиша Daily",              "https://daily.afisha.ru/rss/"),
]

ATOM = "{http://www.w3.org/2005/Atom}"
UA = "Mozilla/5.0 (compatible; HimiyaBot/1.0; +https://t.me/)"
TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")

# ─────────────────────────────────────────────────────────────────────────────
#  ФИЛЬТР НЕГАТИВА
#  Стоит на входе: неподходящая статья не попадает в базу вообще.
#  Границы слов (\b) обязательны, иначе «иск» съест «искусство»,
#  а «суд» — «судьбу». Это проверено тестом.
# ─────────────────────────────────────────────────────────────────────────────
NEGATIVE_PATTERNS = [
    # война, армия, политика
    r"\bвойн", r"\bвоенн", r"\bарми", r"\bфронт", r"\bобстрел", r"\bракет",
    r"\bдрон", r"\bбпла\b", r"\bтеракт", r"\bвзрыв", r"\bмобилизац", r"\bсво\b",
    r"\bспецоперац", r"\bпутин", r"\bкремл", r"\bминоборон", r"\bгенерал",
    r"\bдепутат", r"\bгосдум", r"\bпарламент", r"\bвыборы\b", r"\bпротест",
    r"\bмитинг", r"\bзадержа", r"\bарест", r"\bполици", r"\bфсб", r"\bсанкц",
    r"\bполитик", r"\bпрезидент", r"\bминистр",
    # смерть, трагедии, преступления
    r"\bсмерт", r"\bпогиб", r"\bубий", r"\bумер", r"\bумерл", r"\bне стало",
    r"\bпохорон", r"\bтраур", r"\bтрагед", r"\bкатастроф", r"\bавар",
    r"\bдтп\b", r"\bпожар", r"\bкрушени", r"\bпропал", r"\bутоп",
    r"\bпреступ", r"\bуголовн", r"\bмошенн", r"\bкраж", r"\bкоррупц",
    r"\bследстви", r"\bпрокуратур", r"\bтюрьм", r"\bколони", r"\bприговор",
    r"\bнасили", r"\bизби", r"\bдрак", r"\bтравл", r"\bоскорб", r"\bдомогат",
    # скандалы, ругань, конфликты
    r"\bскандал", r"\bконфликт", r"\bссор", r"\bруган", r"\bразвод",
    r"\bизмен", r"\bбывша", r"\bобвин",
    # «суд» и «иск» — только точные словоформы, иначе съест «судьбу» и «искусство»
    r"\bиск(ом|а|у|е|и|ов|ам|ах)?\b", r"\bсуд(ом|а|у|е|ы|ов|ам|ах|ья|ье|ью)?\b", r"\bсудебн",
    r"\bжалоб", r"\bкритик", r"\bраскритик", r"\bпоруг", r"\bпозор",
    r"\bпровал", r"\bувол", r"\bзапрет", r"\bотмен", r"\bотказ", r"\bбойкот",
    r"\bразочаров", r"\bнедовольн", r"\bобман",
    # болезни, тяжёлое
    r"\bампутац", r"\bонколог", r"\bдиагноз", r"\bинвалид", r"\bболезн",
    r"\bэпидеми", r"\bпандеми", r"\bвирус", r"\bгоспитализ", r"\bопераци[яию]\b",
    # деньги, кризисы, бытовуха
    r"\bкризис", r"\bинфляц", r"\bбезработиц", r"\bштраф", r"\bбанкрот",
    r"\bдолг[иаов]", r"\bтариф", r"\bжкх",
]

NEGATIVE_RE = re.compile("|".join(NEGATIVE_PATTERNS), re.IGNORECASE)

# Слова, за которые наоборот цепляемся при ранжировании
POSITIVE_WORDS = (
    "праздник", "фестиваль", "выставк", "концерт", "премьер", "открыт",
    "побед", "рекорд", "медал", "турнир", "дебют", "юбилей", "премия",
    "красот", "добро", "добрый", "улыбк", "вдохнов", "спас", "помог",
    "дружб", "любов", "счасть", "уют", "нежн", "мил", "забав", "смешн",
    "путешеств", "вкусн", "рецепт", "кухн", "кот", "кошк", "щен", "собак",
    "танец", "танц", "балет", "музык", "художник", "картин", "музей",
    "природа", "закат", "цвет", "весна", "первоцвет",
)
POSITIVE_RE = re.compile("|".join(POSITIVE_WORDS), re.IGNORECASE)


def is_positive(*parts: str | None) -> bool:
    """True, если в тексте нет ни одного запрещённого слова."""
    text = " ".join(p for p in parts if p)
    return not NEGATIVE_RE.search(text)


def positivity(text: str) -> float:
    """0..0.25 — надбавка к рангу за «добрые» слова."""
    hits = len(POSITIVE_RE.findall(text or ""))
    return min(0.25, hits * 0.06)


# ───────────────────────────── парсинг ─────────────────────────────
def _text(node) -> str:
    if node is None:
        return ""
    return WS_RE.sub(" ", html.unescape(TAG_RE.sub(" ", "".join(node.itertext())))).strip()


def _clean(raw: str, limit: int = 220) -> str:
    text = WS_RE.sub(" ", html.unescape(TAG_RE.sub(" ", raw or ""))).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut.rstrip(",.;:") + "…"


def _parse_date(value: str | None) -> str:
    if not value:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")
    value = value.strip()
    for parser in (
        lambda v: parsedate_to_datetime(v),
        lambda v: datetime.fromisoformat(v.replace("Z", "+00:00")),
    ):
        try:
            dt = parser(value)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).isoformat(timespec="seconds")
        except Exception:
            continue
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _image_of(item, description: str) -> Optional[str]:
    for tag in ("enclosure", "media:content", "media:thumbnail"):
        node = item.find(tag)
        if node is not None and node.get("url"):
            return node.get("url")
    node = item.find("{http://search.yahoo.com/mrss/}content")
    if node is not None and node.get("url"):
        return node.get("url")
    match = re.search(r'<img[^>]+src="([^"]+)"', description or "")
    return match.group(1) if match else None


def parse_feed(raw: bytes, topic: str, source_name: str, max_items: int = 25) -> list[dict[str, Any]]:
    """Парсит RSS 2.0 и Atom, нормализует и сразу отсекает негатив."""
    root = ET.fromstring(raw)
    items = root.findall(".//item")
    atom = False
    if not items:
        items = root.findall(f".//{ATOM}entry")
        atom = True

    out: list[dict[str, Any]] = []
    for item in items[:max_items]:
        if atom:
            title = _text(item.find(f"{ATOM}title"))
            link_node = item.find(f"{ATOM}link")
            url = link_node.get("href") if link_node is not None else ""
            raw_desc = _text(item.find(f"{ATOM}summary")) or _text(item.find(f"{ATOM}content"))
            published = _text(item.find(f"{ATOM}updated")) or _text(item.find(f"{ATOM}published"))
        else:
            title = _text(item.find("title"))
            url = _text(item.find("link"))
            raw_desc = _text(item.find("description")) or _text(
                item.find("{http://purl.org/rss/1.0/modules/content/}encoded")
            )
            published = _text(item.find("pubDate"))

        url = (url or "").strip()
        if not title or not url.startswith("http"):
            continue

        summary = _clean(raw_desc, 220)
        # ⬅️ вот здесь негатив не попадает даже в базу
        if not is_positive(title, summary):
            continue

        out.append(
            {
                "topic": topic,
                "source_name": source_name,
                "url": url,
                "url_hash": hashlib.sha1(url.encode()).hexdigest(),
                "title": _clean(title, 140),
                "summary": summary,
                "image_url": _image_of(item, raw_desc),
                "published_at": _parse_date(published),
            }
        )
    return out


def fetch_feed(url: str, topic: str, source_name: str, timeout: int = 12) -> list[dict[str, Any]]:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return parse_feed(response.read(), topic, source_name)


# ───────────────────────────── ранжирование ─────────────────────────────
def _hours_ago(iso_ts: str | None) -> float:
    if not iso_ts:
        return 48.0
    try:
        dt = datetime.fromisoformat(iso_ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return 48.0
    return max(0.5, (datetime.now(timezone.utc) - dt).total_seconds() / 3600)


def _similar(a: str, b: str) -> bool:
    wa = {w for w in re.findall(r"\w{4,}", a.lower())}
    wb = {w for w in re.findall(r"\w{4,}", b.lower())}
    if not wa or not wb:
        return False
    return len(wa & wb) / min(len(wa), len(wb)) > 0.6


def rank(articles: list[dict[str, Any]], limit: int = 6) -> list[dict[str, Any]]:
    """Свежесть + «добрые» слова + популярность. Негатив отсекается повторно."""
    scored: list[tuple[float, dict[str, Any]]] = []
    for art in articles:
        if not is_positive(art.get("title"), art.get("summary")):
            continue
        freshness = 1.0 / (1.0 + _hours_ago(art.get("published_at")) / 12.0)
        mood = positivity(f"{art.get('title')} {art.get('summary')}")
        engagement = min(0.2, (art.get("shares") or 0) * 0.05 + (art.get("likes") or 0) * 0.02)
        scored.append((freshness + mood + engagement, art))

    scored.sort(key=lambda pair: -pair[0])
    picked: list[dict[str, Any]] = []
    for _, art in scored:
        if any(_similar(art["title"], kept["title"]) for kept in picked):
            continue
        picked.append(art)
        if len(picked) >= limit:
            break
    return picked


# Интересы из анкеты, которым нет отдельной темы, но которые логично куда-то отнести
INTEREST_FALLBACK = {
    "животные": "kind",
    "фотография": "art",
    "книги": "culture",
    "психология": "kind",
    "йога": "kind",
    "ночные гулянки": "culture",
    "технологии": "science",
    "игры": "cinema",
    "стартапы": "culture",
}


def topics_from_interests(interests: list[str]) -> list[str]:
    """Не спрашиваем темы повторно — выводим из интересов анкеты."""
    result = [key for key, meta in TOPICS.items() if meta["tag"] and meta["tag"] in interests]
    for interest in interests:
        topic = INTEREST_FALLBACK.get(interest)
        if topic and topic not in result:
            result.append(topic)
    return result or ["art", "kind", "music"]


# ───────────────────────────── тексты ─────────────────────────────
def time_ago(iso_ts: str | None) -> str:
    hours = _hours_ago(iso_ts)
    if hours < 1:
        return f"{int(hours * 60)} мин назад"
    if hours < 24:
        return f"{int(hours)} ч назад"
    return f"{int(hours // 24)} дн назад"


def card_text(article: dict[str, Any], topic_emoji: str | None = None) -> str:
    emoji = topic_emoji or TOPICS.get(article["topic"], {}).get("emoji", "📰")
    summary = html.escape(article.get("summary") or "")
    body = f"\n<blockquote>{summary}</blockquote>" if summary else ""
    return (
        f"{emoji} <b>{html.escape(article['title'])}</b>\n"
        f"<i>{html.escape(article.get('source_name') or '')} · {time_ago(article.get('published_at'))}</i>"
        f"{body}"
    )


def shared_text(sender_name: str, article: dict[str, Any]) -> str:
    emoji = TOPICS.get(article["topic"], {}).get("emoji", "📰")
    summary = html.escape(article.get("summary") or "")
    body = f"\n<blockquote>{summary}</blockquote>" if summary else ""
    return (
        f"💌 <b>{html.escape(sender_name)}</b> поделился:\n\n"
        f"{emoji} <b>{html.escape(article['title'])}</b>\n"
        f"<i>{html.escape(article.get('source_name') or '')} · {time_ago(article.get('published_at'))}</i>"
        f"{body}\n\n{article['url']}"
    )


def digest_intro(name: str, count: int) -> str:
    return (
        f"☕ <b>Доброе утро, {html.escape(name)}</b>\n\n"
        f"{count} хороших материалов по твоим темам — без войн, скандалов и криминала. "
        f"Выбери, что хочется обсудить с кем-то из мэтчей 💌"
    )


def empty_feed_text() -> str:
    return (
        "Лента пока пустая 📭\n\n"
        "Выбери темы — и я принесу первое через несколько минут "
        "(источники обновляются каждые полчаса)."
    )
