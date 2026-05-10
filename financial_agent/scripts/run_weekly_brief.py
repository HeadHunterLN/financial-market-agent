#!/usr/bin/env python3
"""Generate a lightweight weekly market brief from public RSS and quote data."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import html
import json
import math
import re
import sys
import textwrap
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config"
REPORTS_DIR = ROOT / "reports"
MEMORY_DIR = ROOT / "memory"
SESSION_MEMORY_DIR = MEMORY_DIR / "session"
LONG_TERM_MEMORY_DIR = MEMORY_DIR / "long_term"
USER_AGENT = "financial-agent/0.1 (+local research workflow)"


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def fetch_url(url: str, timeout: int = 20) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(html.unescape(value).split())


def fetch_rss_items(source: dict, limit: int = 8) -> list[dict]:
    try:
        raw = fetch_url(source["url"])
        root = ET.fromstring(raw)
    except (urllib.error.URLError, ET.ParseError, KeyError, TimeoutError) as exc:
        return [{
            "title": f"Could not fetch source: {exc}",
            "link": source.get("url", ""),
            "published": "",
            "error": True,
        }]

    items = []
    for item in root.findall(".//item")[:limit]:
        items.append({
            "title": clean_text(item.findtext("title")),
            "link": clean_text(item.findtext("link")),
            "published": clean_text(item.findtext("pubDate")),
            "error": False,
        })
    return items


def fetch_quote(symbol: str) -> dict:
    encoded = urllib.parse.quote(symbol)
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}?range=5d&interval=1d"
    try:
        payload = json.loads(fetch_url(url).decode("utf-8"))
        result = payload["chart"]["result"][0]
        meta = result["meta"]
        quote = result["indicators"]["quote"][0]
        closes = [value for value in quote.get("close", []) if isinstance(value, (int, float))]
        last = meta.get("regularMarketPrice") or (closes[-1] if closes else None)
        first = closes[0] if closes else None
        change_pct = None
        if first and last:
            change_pct = ((last - first) / first) * 100
        return {
            "symbol": symbol,
            "price": last,
            "currency": meta.get("currency", "USD"),
            "five_day_change_pct": change_pct,
            "ok": True,
            "error": "",
        }
    except (urllib.error.URLError, KeyError, IndexError, json.JSONDecodeError, TimeoutError) as exc:
        return {
            "symbol": symbol,
            "price": None,
            "currency": "",
            "five_day_change_pct": None,
            "ok": False,
            "error": str(exc),
        }


def flatten_watchlist(watchlist: dict) -> list[str]:
    symbols = []
    for values in watchlist.values():
        for symbol in values:
            if symbol not in symbols:
                symbols.append(symbol)
    return symbols


def build_category_map(watchlist: dict) -> dict[str, str]:
    category_by_symbol = {}
    for category, symbols in watchlist.items():
        for symbol in symbols:
            category_by_symbol[symbol] = category
    return category_by_symbol


def format_pct(value: float | None) -> str:
    if value is None or math.isnan(value):
        return "n/a"
    return f"{value:+.2f}%"


def format_money(value: float | None, currency: str = "USD") -> str:
    if value is None:
        return "n/a"
    return f"{value:,.2f} {currency}"


def score_symbol(quote: dict, news_mentions: int) -> float:
    momentum = quote.get("five_day_change_pct")
    if momentum is None:
        momentum_score = 0
    elif momentum > 8:
        momentum_score = 1.0
    elif momentum > 2:
        momentum_score = 2.0
    elif momentum > -3:
        momentum_score = 1.0
    else:
        momentum_score = -1.0
    return momentum_score + min(news_mentions, 5) * 0.35


def count_symbol_mentions(symbol: str, titles: list[str]) -> int:
    if len(symbol) < 3:
        return 0
    pattern = re.compile(rf"(?<![A-Z0-9]){re.escape(symbol)}(?![A-Z0-9])")
    return sum(len(pattern.findall(title.upper())) for title in titles)


def build_shortlist(quotes: list[dict], all_titles: list[str], limit: int = 5) -> list[dict]:
    candidates = []
    for quote in quotes:
        symbol = quote["symbol"]
        mentions = count_symbol_mentions(symbol, all_titles)
        candidates.append({
            "symbol": symbol,
            "score": score_symbol(quote, mentions),
            "mentions": mentions,
            "quote": quote,
        })
    return sorted(candidates, key=lambda item: item["score"], reverse=True)[:limit]


def position_size(policy: dict) -> str:
    capital = policy.get("portfolio_capital")
    max_new_position_pct = policy.get("max_new_position_pct")
    if not capital or not max_new_position_pct:
        return "укажи portfolio_capital в config/investment_policy.json, чтобы агент рассчитал диапазон суммы"
    max_position = capital * (max_new_position_pct / 100)
    half_position = max_position / 2
    return f"{format_money(half_position)} - {format_money(max_position)}"


def append_csv_rows(path: Path, fieldnames: list[str], rows: list[dict], replace_date: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing_rows = []
    if path.exists() and path.stat().st_size > 0:
        with path.open("r", encoding="utf-8", newline="") as file:
            existing_rows = list(csv.DictReader(file))
    if replace_date:
        existing_rows = [row for row in existing_rows if row.get("date") != replace_date]
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(existing_rows)
        writer.writerows(rows)


def scenario_text(horizon: str, symbol: str, quote: dict, score: float) -> str:
    change = quote.get("five_day_change_pct")
    if change is None:
        return f"{horizon}: данных по momentum недостаточно; нужен ручной анализ отчётности и оценки."
    if score >= 2:
        return f"{horizon}: базовый сценарий — умеренный рост при сохранении спроса и позитивного новостного фона; вход только после проверки оценки."
    if change < -5:
        return f"{horizon}: идея повышенного риска; возможен отскок, но требуется подтверждение разворота и проверка причин падения."
    return f"{horizon}: нейтральный сценарий; наблюдать за катализаторами, отчётностью и реакцией сектора."


def illustrative_return_range(horizon: str, score: float, quote: dict) -> str:
    change = quote.get("five_day_change_pct")
    high_momentum = change is not None and change > 8
    weak_momentum = change is not None and change < -5
    if horizon == "3-6m":
        if score >= 2 and not high_momentum:
            return "-5% to +12%"
        if high_momentum:
            return "-12% to +18%"
        if weak_momentum:
            return "-18% to +10%"
        return "-8% to +8%"
    if horizon == "1y":
        if score >= 2:
            return "-12% to +25%"
        if weak_momentum:
            return "-25% to +18%"
        return "-15% to +15%"
    if horizon == "5y":
        return "-40% to +150% при сохранении тезиса; высокая неопределённость"
    if horizon == "10y":
        return "-60% to +300% при сохранении тезиса; очень высокая неопределённость"
    return "n/a"


def write_memory(quotes: list[dict], shortlist: list[dict], policy: dict, watchlist: dict, today: str) -> None:
    category_by_symbol = build_category_map(watchlist)
    position = position_size(policy)

    append_csv_rows(
        LONG_TERM_MEMORY_DIR / "market_dynamics.csv",
        ["date", "ticker", "category", "price", "currency", "five_day_change_pct", "status"],
        [{
            "date": today,
            "ticker": quote["symbol"],
            "category": category_by_symbol.get(quote["symbol"], "unknown"),
            "price": quote["price"],
            "currency": quote["currency"],
            "five_day_change_pct": quote["five_day_change_pct"],
            "status": "ok" if quote["ok"] else quote["error"],
        } for quote in quotes],
        replace_date=today,
    )

    append_csv_rows(
        LONG_TERM_MEMORY_DIR / "investment_recommendations.csv",
        [
            "date",
            "ticker",
            "category",
            "score",
            "price",
            "starter_position_range",
            "illustrative_return_3_6m",
            "illustrative_return_1y",
            "illustrative_return_5y",
            "illustrative_return_10y",
            "three_to_six_months",
            "one_year",
            "five_years",
            "ten_years",
            "risks",
            "status",
            "last_reviewed",
        ],
        [{
            "date": today,
            "ticker": item["symbol"],
            "category": category_by_symbol.get(item["symbol"], "unknown"),
            "score": f"{item['score']:.2f}",
            "price": item["quote"]["price"],
            "starter_position_range": position,
            "illustrative_return_3_6m": illustrative_return_range("3-6m", item["score"], item["quote"]),
            "illustrative_return_1y": illustrative_return_range("1y", item["score"], item["quote"]),
            "illustrative_return_5y": illustrative_return_range("5y", item["score"], item["quote"]),
            "illustrative_return_10y": illustrative_return_range("10y", item["score"], item["quote"]),
            "three_to_six_months": scenario_text("3-6 месяцев", item["symbol"], item["quote"], item["score"]),
            "one_year": scenario_text("1 год", item["symbol"], item["quote"], item["score"]),
            "five_years": scenario_text("5 лет", item["symbol"], item["quote"], item["score"]),
            "ten_years": scenario_text("10 лет", item["symbol"], item["quote"], item["score"]),
            "risks": "Отчётность, мультипликаторы, ставки, regulation, sector rotation, liquidity.",
            "status": "active",
            "last_reviewed": today,
        } for item in shortlist],
        replace_date=today,
    )

    append_csv_rows(
        LONG_TERM_MEMORY_DIR / "weekly_actions.csv",
        ["date", "priority", "action", "reason", "status"],
        [{
            "date": today,
            "priority": "high",
            "action": "Проверить shortlist вручную перед сделками.",
            "reason": "Автоматический скоринг учитывает momentum и новости, но не заменяет фундаментальную оценку.",
            "status": "open",
        }, {
            "date": today,
            "priority": "medium",
            "action": "Обновить капитал и еженедельный бюджет в investment_policy.json.",
            "reason": "Без этого агент не может рассчитать точные суммы входа.",
            "status": "open" if policy.get("portfolio_capital") is None else "done",
        }],
        replace_date=today,
    )

    SESSION_MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    session_path = SESSION_MEMORY_DIR / f"session_{today}.md"
    tickers = ", ".join(item["symbol"] for item in shortlist)
    session_path.write_text(
        "\n".join([
            f"# Сессионная память - {today}",
            "",
            "## Выводы текущей сессии",
            "",
            f"- Сформирован еженедельный отчёт и обновлена долгосрочная память.",
            f"- Текущий shortlist для проверки: {tickers or 'нет данных'}.",
            "- Точные суммы инвестиций появятся после заполнения `portfolio_capital` и `weekly_new_capital`.",
            "- Все идеи имеют статус research draft и требуют проверки отчётности, оценки и рисков.",
            "",
        ]),
        encoding="utf-8",
    )


def build_context(quotes: list[dict], news_by_source: list[dict], policy: dict, watchlist: dict) -> dict:
    today = dt.datetime.now().date().isoformat()
    benchmark_symbols = set(watchlist.get("market_benchmarks", []))
    company_quotes = [quote for quote in quotes if quote["symbol"] not in benchmark_symbols]
    all_titles = [
        item["title"]
        for source in news_by_source
        for item in source["items"]
        if item.get("title") and not item.get("error")
    ]
    shortlist = build_shortlist(company_quotes, all_titles)
    return {
        "today": today,
        "all_titles": all_titles,
        "shortlist": shortlist,
    }


def render_report(quotes: list[dict], news_by_source: list[dict], policy: dict, context: dict) -> str:
    today = context["today"]
    shortlist = context["shortlist"]
    position = position_size(policy)

    lines = [
        f"# Еженедельная финансовая сводка - {today}",
        "",
        "> Черновик исследования на основе публичных котировок и RSS-заголовков. Используй его как отправную точку для анализа, а не как персональную финансовую рекомендацию.",
        "",
        "## Динамика рынка",
        "",
        "| Тикер | Цена | 5D динамика | Статус |",
        "|---|---:|---:|---|",
    ]

    for quote in quotes:
        status = "ok" if quote["ok"] else f"ошибка: {quote['error']}"
        lines.append(
            f"| {quote['symbol']} | {format_money(quote['price'], quote['currency'])} | "
            f"{format_pct(quote['five_day_change_pct'])} | {status} |"
        )

    lines.extend([
        "",
        "## Новостная лента",
        "",
    ])

    for source in news_by_source:
        lines.append(f"### {source['name']} ({source['category']})")
        lines.append("")
        if not source["items"]:
            lines.append("- Нет свежих элементов или источник вернул пустую ленту.")
        for item in source["items"]:
            title = item["title"] or "Untitled"
            link = item["link"]
            published = f" - {item['published']}" if item.get("published") else ""
            if link:
                lines.append(f"- [{title}]({link}){published}")
            else:
                lines.append(f"- {title}{published}")
        lines.append("")

    lines.extend([
        "## Shortlist для дальнейшего анализа",
        "",
        f"Ориентировочный диапазон стартовой позиции на одну новую идею: {position}",
        "",
    ])

    for item in shortlist:
        quote = item["quote"]
        lines.extend([
            f"### {item['symbol']}",
            "",
            f"- Скоринг: {item['score']:.2f}",
            f"- 5D momentum: {format_pct(quote['five_day_change_pct'])}",
            f"- Упоминания тикера в заголовках: {item['mentions']}",
            f"- Сценарный диапазон 3-6 месяцев: {illustrative_return_range('3-6m', item['score'], quote)}",
            f"- Сценарный диапазон 1 год: {illustrative_return_range('1y', item['score'], quote)}",
            f"- Сценарный диапазон 5 лет: {illustrative_return_range('5y', item['score'], quote)}",
            f"- Сценарный диапазон 10 лет: {illustrative_return_range('10y', item['score'], quote)}",
            "- Действие: проверить оценку, последний отчёт, guidance и отраслевые катализаторы до сделки.",
            "- Условие входа: предпочтительны поэтапные входы после проверки тренда, ликвидности и дат отчётности.",
            "- Негативный сценарий: слабый guidance, сжатие мультипликаторов, общий risk-off или отраслевое регулирование.",
            "",
        ])

    lines.extend([
        "## Что аналитику нужно дополнить",
        "",
        "- Добавить качественный вывод недели.",
        "- Проверить даты отчётности и последние SEC filings.",
        "- Сравнить каждую компанию из shortlist с отраслевыми бенчмарками.",
        "- Добавить сценарии: базовый, позитивный, негативный.",
        "- Проверить, вписывается ли идея в текущую структуру портфеля.",
        "",
        "## Что нужно настроить",
        "",
    ])

    if policy.get("portfolio_capital") is None:
        lines.append("- `portfolio_capital` не указан, поэтому точные суммы аллокации не рассчитаны.")
    if policy.get("weekly_new_capital") is None:
        lines.append("- `weekly_new_capital` не указан, поэтому темп еженедельного инвестирования не рассчитан.")
    lines.append("- Добавь свои порталы в `config/sources.json`, чтобы покрытие источников было точнее.")

    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate weekly financial market brief.")
    parser.add_argument("--rss-limit", type=int, default=8, help="Max RSS items per source.")
    parser.add_argument("--quote-limit", type=int, default=50, help="Max symbols to fetch.")
    args = parser.parse_args()

    sources = load_json(CONFIG_DIR / "sources.json")
    watchlist = load_json(CONFIG_DIR / "watchlist.json")
    policy = load_json(CONFIG_DIR / "investment_policy.json")

    symbols = flatten_watchlist(watchlist)[: args.quote_limit]
    quotes = [fetch_quote(symbol) for symbol in symbols]
    news_by_source = []
    for source in sources.get("rss_sources", []):
        news_by_source.append({
            "name": source["name"],
            "category": source.get("category", "general"),
            "items": fetch_rss_items(source, limit=args.rss_limit),
        })

    context = build_context(quotes, news_by_source, policy, watchlist)
    today = context["today"]
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORTS_DIR / f"weekly_brief_{today}.md"
    report_path.write_text(render_report(quotes, news_by_source, policy, context), encoding="utf-8")
    write_memory(quotes, context["shortlist"], policy, watchlist, today)
    print(textwrap.dedent(f"""
        Created report:
        {report_path}
    """).strip())
    return 0


if __name__ == "__main__":
    sys.exit(main())
