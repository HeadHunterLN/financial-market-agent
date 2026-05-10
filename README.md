# Financial Market Agent

Репозиторий для персонального финансового аналитического агента.

Your financial agent that helps you follow recent financial market trends and structure investment research.

Агент еженедельно собирает рыночные данные и новости, обновляет память, формирует отчёт на русском языке и сохраняет выводы в Git, чтобы историю можно было переносить в GitHub.

## Структура

- `AGENTS.md` — контекст агента и правила его поведения.
- `financial_agent/config/` — источники, watchlist и инвестиционная политика.
- `financial_agent/reports/` — еженедельные Markdown-отчёты.
- `financial_agent/memory/session/` — сессионная память: выводы конкретного запуска.
- `financial_agent/memory/long_term/` — долгосрочная память: таблицы динамики рынка, действий и рекомендаций.
- `financial_agent/prompts/` — промпты для расширенного анализа.
- `.codex/skills/financial-market-analyst/SKILL.md` — локальный skill агента.

## Еженедельный workflow

1. Собрать котировки и новости.
2. Сформировать отчёт в `financial_agent/reports/`.
3. Обновить сессионную память.
4. Обновить долгосрочные таблицы:
   - `market_dynamics.csv`;
   - `investment_recommendations.csv`;
   - `weekly_actions.csv`.
5. Пометить устаревшие идеи как `stale` или `retired`, если рынок изменился.
6. Закоммитить изменения и синхронизировать с GitHub.

## Запуск

```bash
python3 financial_agent/scripts/run_weekly_brief.py
```

## Важное ограничение

Выводы агента являются исследовательскими заметками, а не персональной финансовой консультацией. Перед инвестиционным решением нужно проверять отчётность, оценку, риски, налоговые последствия и соответствие портфелю.
