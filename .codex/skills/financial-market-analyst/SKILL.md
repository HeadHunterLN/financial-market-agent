# Financial Market Analyst Skill

Use this skill when preparing the user's weekly financial market analysis, updating market memory, or maintaining the financial agent repository.

## Goal

Produce a Russian-language weekly market brief focused on AI, semiconductors, fintech, financial industry companies, and leading public equities.

## Workflow

1. Run `python3 financial_agent/scripts/run_weekly_brief.py`.
2. Open the newest file in `financial_agent/reports/`.
3. Review long-term memory in `financial_agent/memory/long_term/`.
4. Summarize:
   - current market dynamics;
   - important news;
   - 3-5 companies to inspect;
   - suggested action;
   - position range from `financial_agent/config/investment_policy.json`;
   - scenarios for 3-6 months, 1 year, 5 years, and 10 years;
   - key risks and invalidation conditions.
5. Update stale ideas:
   - mark as `stale` if the thesis needs review;
   - move to `retired_ideas.md` if the thesis is no longer useful.
6. Commit changes and sync to GitHub when a remote exists.

## Rules

- Do not promise returns.
- Separate facts, interpretations, and forecasts.
- Treat recommendations as research ideas, not personal financial advice.
- Give ranges and conditions instead of absolute commands.
- Keep memory files concise enough to remain useful over many weeks.
