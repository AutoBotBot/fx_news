# FX Morning Brief Bot — Project Context

**This file is read at the start of every Claude Code session. It is the single source of truth for project context. Do not add features or change architecture without the user's explicit instruction.**

---

## Project purpose

Personal automation for a UK-based discretionary intraday FX trader who trades GBP/USD during the London session (08:00–12:00 UK time).

**The bot is strategy-agnostic.** It provides structured context and captures structured data so the user can develop their own trading ideas through forward observation. It does not recommend setups, predict direction, or commit the user to any particular trading style.

The system has two production runs per trading day:

1. **07:30 UK — Morning Brief.** Generates and delivers a structured pre-session briefing covering overnight GBP/USD price action, the Asian range (as raw data), the previous session recap, key nearby price levels, the economic calendar, news sentiment, volatility expectation, and correlation context. Delivered to Telegram with a tap-through link to today's Notion log page.

2. **12:01 PM UK — End-of-Day Capture.** Pulls 5-minute GBP/USD data for the morning, computes the three time-block extremes (Asian Block 00:00–07:00, Open Block 08:00–08:30, Session Block 08:30–12:00), and appends them to today's Notion page under a structured Block Data section.

## User context

- Engineer by trade, comfortable with code, new to the Python ecosystem
- Uses Claude Code as primary dev tool, VS Code as editor
- Develops on macOS, production runs on GitHub Actions
- Values reliability and honesty in output over cleverness
- Has not yet committed to a specific trading strategy — using the bot to gather data and observations to inform strategy development
- Builds via "execute step N" prompts — each session executes one numbered step from masterplan.md

## How to work in this repo

- The user will tell you "execute step N" where N is a step number from `masterplan.md`
- Read the step in `masterplan.md`, follow it exactly, do not skip ahead
- Each step is self-contained — do not depend on context from a previous session
- After completing a step, summarise what was done and remind the user to commit
- If a step is ambiguous, ask before assuming
- Never add features that are not in the step you were asked to execute

## Architecture

```
07:30 UK (weekdays) — GitHub Actions cron fires
            │
            ▼
src/main.py orchestrator
  1. Fetch overnight GBP/USD price + Asian range  (yfinance)
  2. Fetch yesterday's session recap                (yfinance)
  3. Fetch key nearby levels                        (yfinance)
  4. Fetch correlation context (DXY, gold, ES)      (yfinance)
  5. Fetch economic calendar                        (Trading Economics)
  6. Fetch RSS headlines                            (feedparser)
  7. Generate session context brief                 (Claude API)
  8. Create today's Notion page                     (notion-client)
  9. Populate brief into page body                  (notion-client)
 10. Send Telegram message + link                   (python-telegram-bot)

12:01 PM UK (weekdays) — Second cron fires
            │
            ▼
src/end_of_day.py
  1. Fetch 5-minute GBP/USD data for last 18 hours (yfinance)
  2. Compute Asian Block extremes  (00:00–07:00 UK)
  3. Compute Open Block extremes   (08:00–08:30 UK)
  4. Compute Session Block extremes (08:30–12:00 UK)
  5. Append "📊 Daily Block Data" section to today's Notion page
  6. Send confirmation Telegram message
```

**Notion = memory layer.** One page per trading day. Brief at top, observation notes added by user, trades appended through session, block data added by bot at 12:01, end-of-day notes by user.

**Telegram = delivery layer.** Short push notifications only. Full content lives in Notion.

**GitHub Actions = scheduler.** Two crons per day, weekdays only.

**Claude API = brief generation.** Produces structured session context, never recommendations.

**yfinance = price data.** Adequate for v1. Do not introduce IG API or other broker APIs.

## What the brief contains (strategy-agnostic structure)

The morning brief is built from these data sources and structured to inform any intraday strategy:

1. **Overnight price action** — what GBP/USD did overnight, with Asian range high/low/pips as raw data
2. **Yesterday's session recap** — London session high/low/close from yesterday (often more useful than overnight news for priming the day)
3. **Key nearby levels** — yesterday's high/low, this week's high/low, last week's high/low — all price levels within roughly 50 pips of current
4. **Economic calendar** — UK and US data and central bank events in the next 6 hours
5. **News catalysts** — material headlines from the last 12 hours, with implication for GBP/USD
6. **Volatility expectation** — Expansion / Contraction / Normal / Unclear, based on overnight range vs the 20-day average, news density, and known catalysts
7. **Liquidity context** — Thin / Normal / Heavy, based on holidays, half-days, end-of-month, pre-event days
8. **Correlation flags** — DXY position, gold direction, ES futures sentiment — context for whether USD is being driven by broader risk on/off

The brief describes context. It never names a setup, predicts direction, or tells the user to take a trade.

## Non-goals

- NOT a trading bot. Does not place trades.
- NOT a signal generator. Presents context; the human decides.
- NOT a backtester. The user observes forward.
- NOT a price predictor. Never asks the LLM to forecast direction.
- NOT strategy-specific. Does not assume the user trades any particular setup.
- NOT integrated with brokers (no IG API, no MetaTrader, etc.) in v1.

## Design principles

1. **Every module runs standalone** — `uv run python -m src.news` must work for iteration without running the whole pipeline.
2. **Prompts live in `/prompts` as markdown**, version-controlled. Editing a prompt must not require touching Python.
3. **Secrets never in code** — environment variables via `.env` locally, GitHub Actions secrets in CI.
4. **Honest output.** The brief must be allowed to say "quiet overnight, no catalysts, normal volatility expected" on slow days. Never manufacture insights.
5. **Strategy-agnostic.** Do not introduce setup names, regime classifications tied to specific strategies, or any field that pre-commits the user to a trading style.
6. **Notion operations must be idempotent.** Safe to re-run any workflow without creating duplicate pages or duplicate content. This is the most important invariant.
7. **Errors are never silent.** If any stage fails, the user gets a Telegram message telling them what broke.
8. **v1 is minimal.** Resist feature creep. Do not add anything not explicitly in the current step.

## Tech stack

- Python 3.11+
- `uv` (package manager)
- `anthropic` SDK (Claude API) — **Sonnet only for v1.** One brief per weekday means cost optimisation does not matter (~£1–2/month), and Sonnet's instru
- `notion-client`
- `feedparser` (RSS)
- `yfinance` (price data — primary source for v1)
- `pandas` (timeseries handling)
- `pytz` (Europe/London timezone handling)
- `python-dotenv` (local secrets)
- GitHub Actions (scheduler)

## Repository layout

```
fx-morning-brief/
├── .github/
│   └── workflows/
│       ├── morning-brief.yml      # 07:30 UK workflow
│       └── end-of-day.yml         # 12:01 PM UK workflow
├── src/
│   ├── __init__.py
│   ├── main.py                    # Morning orchestrator
│   ├── end_of_day.py              # 12:01 PM orchestrator
│   ├── price_data.py              # Overnight + Asian range + recap + levels
│   ├── correlations.py            # DXY, gold, ES context
│   ├── block_data.py              # 5-min block extremes for end-of-day
│   ├── calendar_fetch.py          # Trading Economics calendar
│   ├── news.py                    # RSS + Claude session context brief
│   ├── telegram_send.py           # Delivery
│   └── notion_log.py              # Daily log page management
├── prompts/
│   └── session_context.md         # Claude prompt template
├── tests/
│   └── __init__.py
├── .env.example
├── .env                           # Local secrets (gitignored)
├── .gitignore
├── CLAUDE.md                      # This file
├── masterplan.md                  # Numbered build steps
├── pyproject.toml
└── README.md
```

## Notion database schema

Database name: **Daily Trading Log**

| Property | Type | Notes |
|---|---|---|
| Name | Title (text) | "YYYY-MM-DD Day" e.g. "2026-04-13 Mon" |
| Date | Date (with time) | Today's start of day UK |
| Volatility Expectation | Select | Expansion, Contraction, Normal, Unclear |
| Volatility Actual | Select | Expansion, Contraction, Normal *(filled by user end of day)* |
| Liquidity Context | Select | Thin, Normal, Heavy |
| Asian High | Number | 5 decimal places |
| Asian Low | Number | 5 decimal places |
| Asian Range (pips) | Number | Computed |
| Yesterday High | Number | 5 decimal places |
| Yesterday Low | Number | 5 decimal places |
| DXY Direction | Select | Strong Up, Up, Flat, Down, Strong Down |
| Trades Taken | Number | Integer, incremented by append_trade |
| Net R | Number | Decimal, 2 places |
| Net £ | Number | Currency £ |
| News Impact | Select | None, Low, Medium, High |
| Brief Useful | Checkbox | User fills honestly during weekly review |
| Followed Rules | Checkbox | User fills honestly |
| Tags | Multi-select | Free-form: FOMC, BoE, NFP, CPI, A+ day, tilt, etc. |

Page body section structure (heading_2 blocks, in order):

1. 🌅 Morning Brief
2. 📅 Key Events Today
3. 📰 Overnight Headlines
4. 📍 Key Levels & Context
5. 🌍 Correlations
6. 📊 Daily Block Data       *(populated at 12:01 PM by end_of_day.py)*
7. 👁️ Observation Notes      *(filled by user during 8–10 AM observation)*
8. 📈 Trades                 *(appended by user as trades are taken)*
9. 📝 End of Day Notes       *(filled by user after session)*

## Key constraints and gotchas

- **Timezones**: yfinance returns UTC. All "today" logic must convert to Europe/London first via pytz. BST vs GMT matters twice a year. Asian session is 00:00–07:00 UK *local time*.
- **Telegram MarkdownV2**: escapes are `_ * [ ] ( ) ~ \` > # + - = | { } . !` — forgetting any of these breaks the message silently.
- **python-telegram-bot v20+ is async.** Use `asyncio.run()` in `__main__` blocks.
- **Notion block insertion**: use "append block children" with the section heading as parent. To find "which blocks belong to which section", list all page children and track position relative to heading_2 blocks.
- **Idempotency test**: always run main.py and end_of_day.py twice in testing and verify no duplicate pages or duplicate content.
- **Claude model string**: check the anthropic docs for the current Sonnet model string. Do not hardcode from memory — model strings change.
- **yfinance 5-minute data**: only available for the last ~60 days. Acceptable for v1's end-of-day capture which only needs the current day.
- **yfinance correlation tickers**: DXY = "DX-Y.NYB", Gold = "GC=F", ES = "ES=F". Some are delayed; that's fine for context.

## When iterating, prefer

- Editing `prompts/session_context.md` over Python changes for brief output tuning
- Adding logging over adding features
- Testing idempotency after every Notion change
- Running individual modules standalone before running orchestrators

## When iterating, avoid

- Adding features that aren't in the step the user asked you to execute
- Asking the LLM to predict direction or recommend trades
- Introducing setup names, regime labels tied to strategies, or "expected setup" fields
- Silent failure modes — every error path must surface to Telegram
- Hardcoding paths, model strings, or secrets
- Making Telegram messages long (full content belongs in Notion)
- Introducing new dependencies without asking

## Current status

Pre-build. Follow `masterplan.md` step by step. The user will say "execute step N" — read that step, do exactly what it says, then stop.
