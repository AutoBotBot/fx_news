# FX Morning Brief Bot — Masterplan

Numbered build steps for Claude Code. Each step is self-contained — start a new Claude Code session per step and tell it: **"Read CLAUDE.md and masterplan.md, then execute Step N."**

Do not skip steps. Do not combine steps. Commit after every step.

**Important context**: This bot is **strategy-agnostic**. It generates structured session context and captures structured data so you can develop trading ideas through forward observation. It does not recommend setups, predict direction, or commit you to any particular trading style. The brief is a lens, not a strategy.

---

## Pre-build setup (manual, not for Claude Code)

Before Step 1, you must complete the following manually:

### M1. Install tooling on macOS

```bash
# Homebrew (skip if installed)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Core tools
brew install uv gh git

# VS Code
brew install --cask visual-studio-code

# Claude Code
brew install --cask claude-code
```

### M2. VS Code extensions

Install: Python (Microsoft), Pylance, Ruff (Astral), GitLens (optional), Error Lens (optional).

### M3. Create accounts and collect API keys

Keep a scratch text file open with these.

**Anthropic API key**
- console.anthropic.com → API Keys → create "fx-brief"
- Add $10 credit
- Save key (starts with `sk-ant-`)

**Telegram bot**
- Telegram → message `@BotFather` → `/newbot`
- Save the HTTP API token
- Send your new bot any message
- Visit `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` and find `"chat":{"id":<NUMBER>` — save the chat ID

**Notion integration**
- notion.so/my-integrations → New integration → "FX Brief Bot"
- Capabilities: Read, Update, Insert content
- Copy the Internal Integration Secret

**GitHub**
- `gh auth login` in terminal

### M4. Create the Notion database manually

In Notion:

1. Create a page called **FX Trading Hub** at workspace top level
2. Inside it, create a full-page database called **Daily Trading Log**
3. Set up properties (delete defaults first):

| Property | Type | Options |
|---|---|---|
| Name | Title (text) | "YYYY-MM-DD Day" format |
| Date | Date (with time) | |
| Volatility Expectation | Select | Expansion, Contraction, Normal, Unclear |
| Volatility Actual | Select | Expansion, Contraction, Normal |
| Liquidity Context | Select | Thin, Normal, Heavy |
| Asian High | Number | 5 decimal places |
| Asian Low | Number | 5 decimal places |
| Asian Range (pips) | Number | |
| Yesterday High | Number | 5 decimal places |
| Yesterday Low | Number | 5 decimal places |
| DXY Direction | Select | Strong Up, Up, Flat, Down, Strong Down |
| Trades Taken | Number | Integer |
| Net R | Number | Decimal 2 places |
| Net £ | Number | Currency £ |
| News Impact | Select | None, Low, Medium, High |
| Brief Useful | Checkbox | |
| Followed Rules | Checkbox | |
| Tags | Multi-select | Free-form |

4. Share with integration: `•••` menu → Connections → Add → "FX Brief Bot"
5. Get database ID from URL (32-char string before `?v=`)
6. Save it for Step 1

### M5. Create the project directory

```bash
mkdir fx-morning-brief
cd fx-morning-brief
# Copy CLAUDE.md and masterplan.md into this directory
```

Open Claude Code in that directory. You're ready for Step 1.

---

## Step 1 — Project bootstrap

**Tell Claude Code:** "Read CLAUDE.md and masterplan.md, then execute Step 1."

```
Execute Step 1: Project Bootstrap.

Initialise the project scaffold with uv. Do not write any application
code yet — only the directory structure, dependencies, and configuration
files.

Tasks:

1. Initialise a new uv project called fx-morning-brief in the current
   directory (do NOT create a subdirectory — uv init . style)

2. Add these dependencies via `uv add`:
   - anthropic
   - python-telegram-bot
   - feedparser
   - requests
   - python-dotenv
   - pytz
   - notion-client
   - yfinance
   - pandas

3. Create the folder structure:
   - src/ with empty __init__.py
   - prompts/ (empty)
   - tests/ with empty __init__.py
   - .github/workflows/ (empty)

4. Create .gitignore covering Python (__pycache__, *.pyc, .pytest_cache),
   .env, .venv, macOS (.DS_Store), VS Code (.vscode/)

5. Create .env.example with these placeholder lines:
   ANTHROPIC_API_KEY=sk-ant-...
   TELEGRAM_BOT_TOKEN=
   TELEGRAM_CHAT_ID=
   NOTION_TOKEN=
   NOTION_DATABASE_ID=
   FOREX_FACTORY_RSS=https://rss.forexfactory.com

6. Create a minimal README.md that says the project is the FX Morning
   Brief Bot, references CLAUDE.md and masterplan.md for context, and
   notes that the bot is built step-by-step via "execute step N" prompts.

7. Initialise git, make an initial commit "Step 1: project scaffold"

8. Show me the final directory tree.

9. Then walk me through:
   - Creating my private GitHub repo with `gh repo create fx-morning-brief --private --source=. --remote=origin`
   - Pushing the initial commit
   - Copying .env.example to .env so I can fill in real values
   - The list of GitHub secrets I will need to set in Step 11 (just list
     names, do not set them yet)

Do not write any source code in src/. Only the scaffold.
```

---

## Step 2 — Telegram delivery module

**Tell Claude Code:** "Read CLAUDE.md and masterplan.md, then execute Step 2."

```
Execute Step 2: Telegram Delivery Module.

Build src/telegram_send.py — the delivery layer for the bot. This must
work end-to-end with a real "hello world" message before we proceed to
any other modules.

Requirements:

1. Function `async def send_message(text: str, parse_mode: str = "MarkdownV2") -> bool`
   - Sends a message to the configured Telegram chat
   - Uses python-telegram-bot v20+ async API
   - Returns True on success, False on failure
   - Logs errors clearly including the Telegram API error response

2. Helper `escape_markdown_v2(text: str) -> str`
   - Properly escapes the MarkdownV2 special characters:
     _ * [ ] ( ) ~ ` > # + - = | { } . !
   - This is a known gotcha that breaks messages silently if missed

3. Reads TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID from environment via
   python-dotenv loading .env

4. `if __name__ == "__main__":` block:
   - Sends "Hello from FX brief bot 🚀" using asyncio.run()
   - Run with: uv run python -m src.telegram_send

5. After writing the module, walk me through running the test and
   verifying the message arrives on my phone

6. Once verified, commit with message "Step 2: Telegram delivery module"

Do NOT proceed to other modules. This step only builds telegram_send.py.
```

---

## Step 3 — Notion daily log module

**Tell Claude Code:** "Read CLAUDE.md and masterplan.md, then execute Step 3."

```
Execute Step 3: Notion Daily Log Module.

Build src/notion_log.py — the memory layer that manages one Notion
page per trading day.

The Notion database is already created manually with the schema
described in CLAUDE.md. The database ID is in NOTION_DATABASE_ID env
var.

Required functions:

1. `get_or_create_today_page() -> str`
   - Returns the Notion page ID for today's date in UK timezone
   - Query the database filtering by Date == today UK
   - If found, return the existing page ID
   - If not found, create a new page with:
     - Name property: "YYYY-MM-DD Day" format e.g. "2026-04-13 Mon"
     - Date property: today's start of day in Europe/London
     - Empty body containing 9 heading_2 section blocks in this order:
       1. 🌅 Morning Brief
       2. 📅 Key Events Today
       3. 📰 Overnight Headlines
       4. 📍 Key Levels & Context
       5. 🌍 Correlations
       6. 📊 Daily Block Data
       7. 👁️ Observation Notes
       8. 📈 Trades
       9. 📝 End of Day Notes
   - MUST be idempotent — calling twice on the same day must return
     the same existing page ID, never create a duplicate

2. `populate_morning_brief(page_id, brief_text, headlines, calendar,
   levels_text, correlations_text, properties: dict) -> None`
   - Appends brief_text as paragraph blocks under "🌅 Morning Brief"
   - Appends formatted headlines as bulleted_list_items under
     "📰 Overnight Headlines" (format: "[source] title (HH:MM UTC)")
   - Appends formatted calendar events as bulleted_list_items under
     "📅 Key Events Today" (format: "HH:MM UK – country – event
     (forecast: X, previous: Y)")
   - Appends levels_text as paragraph blocks under "📍 Key Levels & Context"
   - Appends correlations_text as paragraph blocks under "🌍 Correlations"
   - Updates these page properties from the properties dict:
     - Volatility Expectation (select)
     - Liquidity Context (select)
     - Asian High (number)
     - Asian Low (number)
     - Asian Range (pips) (number)
     - Yesterday High (number)
     - Yesterday Low (number)
     - DXY Direction (select)
   - Idempotent: before inserting under a section, list the page's
     children blocks and check if the section heading already has
     content blocks following it (before the next heading_2). If yes,
     skip with a warning log and do NOT duplicate.

3. `populate_block_data(page_id, asian_block, open_block, session_block) -> None`
   - Each *_block argument is a dict with keys: high, low, range_pips,
     time_start, time_end
   - Appends formatted block data as paragraph blocks under
     "📊 Daily Block Data"
   - Format example:
     "Asian Block (00:00–07:00 UK): High 1.26845, Low 1.26512, Range 33.3 pips
      Open Block (08:00–08:30 UK): High 1.26891, Low 1.26677, Range 21.4 pips
      Session Block (08:30–12:00 UK): High 1.27102, Low 1.26588, Range 51.4 pips"
   - Idempotent in the same way as populate_morning_brief

4. `append_trade(page_id, trade: dict) -> None`
   - Appends a heading_3 under "📈 Trades" with trade number, direction,
     and a free-text label the user provides
   - Under it, paragraph blocks for entry, stop, target, size,
     confidence, reasoning
   - Increments Trades Taken property by 1

5. `append_end_of_day(page_id, summary_text, volatility_actual, net_r,
   net_gbp) -> None`
   - Appends summary_text under "📝 End of Day Notes"
   - Updates Volatility Actual, Net R, Net £ properties

6. `get_page_url(page_id: str) -> str`
   - Returns notion.so URL usable in Telegram messages

Implementation notes:
- Use notion-client
- Handle API errors gracefully — log clearly, never crash callers
- Use proper Notion block types: heading_2, heading_3, paragraph,
  bulleted_list_item
- Notion API block insertion uses "append block children". To find
  "which blocks belong to which section", list all page children and
  track position relative to heading_2 blocks. Document this approach
  with a comment.

Standalone __main__ block:
- Calls get_or_create_today_page()
- Calls populate_morning_brief with dummy content (clearly fake values)
- Calls populate_block_data with dummy block data
- Prints the page URL
- Calls get_or_create_today_page() a SECOND time and asserts it returns
  the same ID — this verifies idempotency
- Calls populate_morning_brief a second time and verifies no duplicate
  content is added
- Run with: uv run python -m src.notion_log

After verifying it works, commit with message "Step 3: Notion daily log
module with strategy-agnostic schema"

Do NOT build any other modules. Only notion_log.py.
```

---

## Step 4 — Price data, levels, and Asian range module

**Tell Claude Code:** "Read CLAUDE.md and masterplan.md, then execute Step 4."

```
Execute Step 4: Price Data, Levels, and Asian Range Module.

Build src/price_data.py — fetches overnight GBP/USD price action,
Asian range, yesterday's session recap, and key nearby levels.

Required function:

`get_market_context() -> dict`

Returns a dict with these keys:

# Asian range and current state
- asian_high: float (GBP/USD high during 00:00–07:00 UK local today)
- asian_low: float
- asian_range_pips: float (high - low, where 1 pip = 0.0001)
- current_price: float (most recent available)
- distance_from_asian_high_pips: float (negative if below)
- distance_from_asian_low_pips: float (negative if above)

# Overnight context
- yesterday_close: float (22:00 UK previous day)
- overnight_change_pips: float (current_price - yesterday_close in pips)

# Yesterday's London session recap
- yesterday_session_high: float (high during 08:00–17:00 UK yesterday)
- yesterday_session_low: float (low during 08:00–17:00 UK yesterday)
- yesterday_session_close: float (closest to 17:00 UK yesterday)

# Key levels (any within 50 pips of current price are "nearby")
- this_week_high: float (highest price since Monday 00:00 UK this week)
- this_week_low: float (lowest price since Monday 00:00 UK this week)
- last_week_high: float (highest price during the previous calendar week)
- last_week_low: float (lowest price during the previous calendar week)

# Volatility context
- range_20day_avg_pips: float (average daily range over the last 20
  trading days, used to assess whether overnight range is unusual)
- overnight_vs_avg_ratio: float (asian_range_pips / (range_20day_avg_pips
  / 4) — overnight range is roughly a quarter of a full day's range
  on average; ratio > 1.5 suggests an active overnight)

# Human-readable summaries
- summary_text: str (1-2 sentences about overnight action and Asian range)
- levels_text: str (multi-line text listing all key levels with their
  distance from current price in pips, marked "NEARBY" if within 50 pips)
- yesterday_recap_text: str (1 sentence about yesterday's session)

Implementation:
- Use yfinance with ticker "GBPUSD=X"
- Fetch hourly data for the last 30 days to capture weekly levels and
  20-day range average
- yfinance returns UTC timestamps — convert to Europe/London via pytz
- Asian session = 00:00–07:00 UK local time
- London session = 08:00–17:00 UK local time
- "Today" / "Yesterday" / "This week" / "Last week" all in UK local time
- "This week" starts Monday 00:00 UK
- "Last week" is the previous Monday 00:00 to Sunday 23:59 UK

Edge cases:
- Monday morning — yesterday's session is Friday's
- Bank holidays — use whatever data exists, log if significant gaps
- Missing data — return dict with None values and a clear summary_text

Standalone __main__:
- Calls get_market_context() and pretty-prints the dict
- Run with: uv run python -m src.price_data

Code comment near the top: "yfinance FX data is delayed and approximate.
For v1 this is acceptable because we're providing context, not making
trade decisions."

After verifying it returns sensible numbers and the levels_text reads
naturally, commit with message "Step 4: price data with Asian range,
yesterday recap, and key levels"

Do NOT build any other modules.
```

---

## Step 5 — Correlations module

**Tell Claude Code:** "Read CLAUDE.md and masterplan.md, then execute Step 5."

```
Execute Step 5: Correlations Module.

Build src/correlations.py — fetches the broader market context that
influences GBP/USD: dollar index, gold, and US equity futures.

GBP/USD does not trade in isolation. USD strength (DXY), risk
sentiment (gold and equities), and the relationship between them
provides context for whether the day is likely to be USD-driven or
GBP-driven.

Required function:

`get_correlations() -> dict`

Returns a dict with these keys:

- dxy_current: float
- dxy_change_pct_24h: float (% change vs 24h ago)
- dxy_direction: str (one of: "Strong Up", "Up", "Flat", "Down", "Strong Down")
  Thresholds:
    Strong Up:    >= +0.5%
    Up:           +0.15% to +0.5%
    Flat:         -0.15% to +0.15%
    Down:         -0.5% to -0.15%
    Strong Down:  <= -0.5%

- gold_current: float
- gold_change_pct_24h: float
- gold_direction: str (same scheme as DXY)

- es_current: float
- es_change_pct_24h: float
- es_direction: str (same scheme)

- risk_tone: str (one of: "Risk On", "Risk Off", "Mixed")
  Logic:
    Risk On  = ES up + Gold down (or flat)
    Risk Off = ES down + Gold up
    Mixed    = anything else

- correlations_text: str (multi-line human-readable summary, e.g.:
    "DXY: 105.42 (+0.32%, Up)
     Gold: 2387.10 (-0.45%, Down)
     ES futures: 5783.25 (+0.18%, Up)
     Risk tone: Risk On — equities firm, gold soft, USD modestly bid")

Implementation:
- Use yfinance with these tickers:
  - DXY: "DX-Y.NYB"
  - Gold: "GC=F"
  - ES futures: "ES=F"
- Fetch hourly data for the last 48 hours
- "24h ago" = the price closest to 24 hours before the most recent bar
- Compute % change as (current - 24h_ago) / 24h_ago * 100

Edge cases:
- If any ticker fails, set its values to None and log clearly. Do NOT
  crash the function. The brief should still work even if one
  correlation source is down.
- The risk_tone calculation should handle None values by returning "Unknown"
- The correlations_text should clearly indicate any missing data

Standalone __main__:
- Calls get_correlations() and pretty-prints the result
- Run with: uv run python -m src.correlations

After verifying it returns sensible numbers, commit with message
"Step 5: correlations module for DXY, gold, and ES context"

Do NOT build any other modules.
```

---

## Step 6 — Block data module for end-of-day capture

**Tell Claude Code:** "Read CLAUDE.md and masterplan.md, then execute Step 6."

```
Execute Step 6: Block Data Module.

Build src/block_data.py — computes the three time-block extremes that
will be captured into Notion at 12:01 PM UK each weekday.

This module is independent of price_data.py because it uses 5-minute
resolution data and is called from a different workflow at a different
time of day.

Required function:

`get_daily_blocks() -> dict`

Returns a dict with three keys: asian_block, open_block, session_block.
Each is itself a dict with these keys:
- high: float
- low: float
- range_pips: float
- time_start: str (e.g. "00:00")
- time_end: str (e.g. "07:00")

The three blocks are:
1. Asian Block: 00:00–07:00 UK local time today
2. Open Block: 08:00–08:30 UK local time today
3. Session Block: 08:30–12:00 UK local time today

Implementation:
- Use yfinance with ticker "GBPUSD=X"
- Fetch 5-minute interval data for the last 18 hours (this covers all
  three blocks comfortably and stays within yfinance's 60-day window
  for 5m data)
- Convert UTC timestamps to Europe/London
- Filter to today's UK date
- For each block, slice the dataframe by time range and compute high
  and low
- range_pips = (high - low) * 10000

Edge cases:
- If a block has no data (e.g. Session Block called before 12:00, or
  bank holiday), return None for that block's values with a logged
  warning, but still return the dict structure
- If yfinance fails entirely, return all-None blocks with a clear log message

Standalone __main__:
- Calls get_daily_blocks() and pretty-prints the result
- Run with: uv run python -m src.block_data

After verifying it returns sensible numbers, commit with message
"Step 6: block data module for end-of-day capture"

Do NOT build any other modules.
```

---

## Step 7 — Economic calendar module

**Tell Claude Code:** "Read CLAUDE.md and masterplan.md, then execute Step 7."

```
Execute Step 7: Economic Calendar Module.

Build src/calendar_fetch.py — fetches UK and US economic events for
the morning brief.

Required function:

`get_upcoming_events(hours_ahead: int = 6) -> list[dict]`

Returns a list of event dicts, each with:
- time_uk: str (formatted "HH:MM")
- time_utc: datetime
- country: str ("UK" or "US")
- event: str (release name)
- importance: str ("high" or "medium")
- forecast: str | None
- previous: str | None

Implementation:

Implementation — Forex Factory RSS:
- Fetch https://rss.forexfactory.com using feedparser (already a dependency,
  no API key required)
- Each entry has a title containing the currency and event name
- Filter to GBP and USD events only
- Map the FF impact tag to importance: "High" → "high", "Medium" → "medium";
  skip "Low" and "Non-Economic"
- Only include events whose time falls within the next `hours_ahead` hours
- If the feed fetch fails for any reason, return an empty list with a logged
  warning — do NOT crash. The morning brief must still work without calendar data.

Filter results to:
- Only UK and US events
- Only the next `hours_ahead` hours from now
- Only medium or high importance

Standalone __main__:
- Calls get_upcoming_events(hours_ahead=8) and prints results
- Run with: uv run python -m src.calendar_fetch

After verifying it returns events (or an empty list with warning),
commit with message "Step 7: economic calendar module"

Do NOT build any other modules.
```

---

## Step 8 — News module with session context generation

**Tell Claude Code:** "Read CLAUDE.md and masterplan.md, then execute Step 8."

```
Execute Step 8: News Module with Session Context Generation.

Build src/news.py and prompts/session_context.md. This is the most
important module — budget time for prompt iteration.

PART A: Create prompts/session_context.md with EXACTLY this content:

---
You are briefing a discretionary intraday FX trader who trades GBP/USD
during the London session (08:00–12:00 UK time). They will read this
at 07:30, 30 minutes before they start trading.

Your job is to provide STRUCTURED CONTEXT, not trade recommendations.
The trader has not committed to a single strategy and is observing the
market to develop their own ideas. Do not name setups, predict
direction, or tell them what to do.

You are given:
- Headlines from the last 12 hours
- Scheduled economic events for the next 6 hours
- Overnight GBP/USD price action including the Asian range
- Yesterday's London session recap
- Key nearby price levels
- Correlation context (DXY, gold, US equity futures)

Your output, in this exact order:

1. **Overnight summary** (2 sentences max): What GBP/USD did overnight.
   Reference the Asian range explicitly (high, low, pips). State where
   price is now relative to it.

2. **Material catalysts** (bullet list, only if relevant): For each
   item from headlines that materially affects GBP/USD sentiment or
   volatility today:
   - What happened (one sentence)
   - Likely GBP/USD implication (hawkish GBP / dovish GBP / risk-on /
     risk-off / mixed)
   - Confidence (high / medium / low) — be honest, most news is low

3. **Today's calendar** (bullet list): UK and US data or central bank
   events in the next 6 hours. Include time in UK local time and
   consensus if known.

4. **Yesterday's recap** (one sentence): What happened in yesterday's
   London session. Where did it open, where did it close, was it
   trending or ranging.

5. **Volatility expectation** (one line, this exact format):
   "Volatility expectation: [Expansion / Contraction / Normal /
   Unclear]. Reasoning: [one sentence covering overnight range vs
   average, news density, and known catalysts]."

6. **Liquidity context** (one line, this exact format):
   "Liquidity: [Thin / Normal / Heavy]. Reasoning: [one sentence
   covering holidays, day of week, pre/post major event, time of
   month]."

**Critical rules:**
- Be concise. The trader is experienced.
- If nothing material happened overnight, say so plainly. Do NOT
  manufacture insights. "Quiet overnight, Asian range was tight at
  18 pips, no Tier-1 catalysts pending, normal session expected" is
  a correct brief on a quiet day.
- Never predict direction. Never say "GBP/USD is likely to move higher/lower."
  Describe context and let the trader decide.
- Never name a setup or trading style. Do not say "look for breakouts"
  or "expect mean reversion." Describe what IS, not what to DO.
- Never use hype words (massive, huge, crashed, plunged). Neutral
  language only.
- The Volatility expectation and Liquidity lines must use the exact
  wording from the lists above so they can be parsed programmatically.

---

INPUTS:

Headlines (last 12 hours):
{headlines}

Economic calendar (next 6 hours):
{calendar}

Overnight GBP/USD price action and Asian range:
{price_summary}

Yesterday's London session recap:
{yesterday_recap}

Key nearby price levels:
{levels_text}

Correlation context (DXY, gold, ES futures):
{correlations_text}
---

PART B: Build src/news.py with these functions:

1. `fetch_headlines(hours_back: int = 12) -> list[dict]`
   - Fetches from these RSS feeds (FEEDS constant):
     * Reuters business: https://feeds.reuters.com/reuters/businessNews
     * FT markets: https://www.ft.com/markets?format=rss
     * BBC business: http://feeds.bbci.co.uk/news/business/rss.xml
     * ForexLive: https://www.forexlive.com/feed/news
     * Investing.com forex: https://www.investing.com/rss/news_1.rss
   - Returns list of dicts with: title, summary, source, published
     (UTC datetime), link
   - Filters to last `hours_back` hours
   - Handles individual feed failures gracefully — one bad feed must
     not break the function
   - De-duplicates by approximate title match (lowercase, stripped)
   - If a feed returns nothing or errors on first run, log it clearly

2. `generate_session_context(headlines, calendar, price_summary,
   yesterday_recap, levels_text, correlations_text) -> str`
   - Loads the prompt template from prompts/session_context.md
   - Formats inputs into the template:
     - headlines: bulleted list "[source] title (HH:MM UTC)"
     - calendar: bulleted list "HH:MM UK – country – event (forecast: X,
       previous: Y)"
     - price_summary, yesterday_recap, levels_text, correlations_text:
       passed through as-is
   - Calls the Claude API via the anthropic SDK
   - IMPORTANT: check the anthropic Python SDK docs for the current
     Sonnet model string. Do NOT hardcode from memory. Use the latest
     claude-sonnet-* model identifier.
   - max_tokens=1500, temperature=0.3
   - Returns the response text
   - On API failure returns "Brief generation failed: [error]. Check logs."

3. `parse_brief(brief_text: str) -> dict`
   - Parses the brief and returns:
     - volatility_expectation: str | None (Expansion / Contraction /
       Normal / Unclear)
     - liquidity_context: str | None (Thin / Normal / Heavy)
   - Use regex matching the exact formats specified in the prompt
   - Returns None for any field that fails to parse
   - Capitalisation must match the Notion select option capitalisation
     exactly

4. Standalone __main__:
   - Fetches real headlines
   - Imports get_market_context from price_data and uses real values
   - Imports get_correlations from correlations and uses real values
   - Uses mock or real calendar data
   - Calls generate_session_context
   - Prints the full brief
   - Calls parse_brief and prints the parsed dict
   - Run with: uv run python -m src.news

After verifying real headlines come through and the Claude brief looks
sensible with all parsed fields populated, commit with message
"Step 8: news module with session context generation"

I will iterate on prompts/session_context.md myself in subsequent
sessions without touching Python.

Do NOT build any other modules.
```

---

## Step 9 — Morning brief orchestrator

**Tell Claude Code:** "Read CLAUDE.md and masterplan.md, then execute Step 9."

```
Execute Step 9: Morning Brief Orchestrator.

Build src/main.py — the orchestrator that ties together price_data,
correlations, calendar_fetch, news, notion_log, and telegram_send to
deliver the 07:30 UK morning brief.

Required behaviour:

1. Load .env via python-dotenv at the top of main()

2. Time gate (Europe/London via pytz):
   - If today is Saturday or Sunday → log "skipping, weekend" and exit 0
   - If current UK time is outside 07:25–07:35 AND env var FORCE_RUN
     is not set → log "outside window, skipping" and exit 0
   - FORCE_RUN bypass lets me test manually without waiting for 07:30

3. Fetch pipeline (each in try/except so one failure doesn't crash
   the whole flow):
   a. market = price_data.get_market_context()
   b. corr = correlations.get_correlations()
   c. calendar = calendar_fetch.get_upcoming_events(hours_ahead=6)
   d. headlines = news.fetch_headlines(hours_back=12)

4. Generate the brief by calling:
   news.generate_session_context(
     headlines=headlines,
     calendar=calendar,
     price_summary=market['summary_text'],
     yesterday_recap=market['yesterday_recap_text'],
     levels_text=market['levels_text'],
     correlations_text=corr['correlations_text']
   )

5. Parse the brief:
   parsed = news.parse_brief(brief_text)
   # gives volatility_expectation and liquidity_context

6. Notion writes:
   a. page_id = notion_log.get_or_create_today_page()
   b. Build properties dict:
      properties = {
        'volatility_expectation': parsed['volatility_expectation'],
        'liquidity_context': parsed['liquidity_context'],
        'asian_high': market['asian_high'],
        'asian_low': market['asian_low'],
        'asian_range_pips': market['asian_range_pips'],
        'yesterday_high': market['yesterday_session_high'],
        'yesterday_low': market['yesterday_session_low'],
        'dxy_direction': corr['dxy_direction'],
      }
   c. notion_log.populate_morning_brief(
        page_id=page_id,
        brief_text=brief_text,
        headlines=headlines,
        calendar=calendar,
        levels_text=market['levels_text'],
        correlations_text=corr['correlations_text'],
        properties=properties
      )
   d. notion_url = notion_log.get_page_url(page_id)

7. Format the Telegram message (keep under 1500 chars total):
   - Header: "🌅 GBP/USD Brief — [today's date in DD MMM format]"
   - Asian range line: "Asian: H [asian_high] L [asian_low] ([range] pips)"
   - Volatility line: "Vol: [volatility_expectation]"
   - Liquidity line: "Liquidity: [liquidity_context]"
   - DXY line: "DXY: [dxy_direction]"
   - One blank line
   - The first paragraph of the brief (overnight summary)
   - Footer: "📔 [Open today's log](<notion_url>)"
   - The full brief lives in Notion. Telegram is the push notification
     and quick context, not a document viewer.

8. Send via telegram_send.send_message()

9. Log success to stdout

Error handling:
- If any stage fails, send a Telegram message:
  "⚠️ Morning brief failed at [stage_name]: [error message]"
  Never let failures be silent.
- If Notion writes fail but the brief was generated, send the brief
  text to Telegram without the Notion link
- If Telegram fails but Notion succeeded, log clearly — at least the
  page exists in Notion

Test locally:
FORCE_RUN=1 uv run python -m src.main

After verifying:
- A short Telegram message arrives with Asian range, volatility,
  liquidity, DXY, and a working Notion link
- Tapping the link opens today's Notion page with the full brief,
  headlines, calendar, levels section, and correlations section all
  populated, and properties set
- Re-running with FORCE_RUN=1 does NOT duplicate Notion content

Commit with message "Step 9: morning brief orchestrator end-to-end"

This is v0.9 — functionally complete morning brief, not yet automated.
Do NOT build the end-of-day workflow yet.
```

---

## Step 10 — End-of-day capture orchestrator

**Tell Claude Code:** "Read CLAUDE.md and masterplan.md, then execute Step 10."

```
Execute Step 10: End-of-Day Capture Orchestrator.

Build src/end_of_day.py — the 12:01 PM UK orchestrator that captures
the three time-block extremes into today's Notion page.

This is the second production workflow, separate from main.py.

Required behaviour:

1. Load .env via python-dotenv

2. Time gate (Europe/London):
   - If weekend → log "skipping, weekend" and exit 0
   - If current UK time is outside 11:55–12:15 AND env var FORCE_RUN
     is not set → log "outside window, skipping" and exit 0
   - The window is slightly wider than morning brief because Session
     Block ends at 12:00 and we need data settled before fetching

3. Fetch pipeline (try/except wrapped):
   - blocks = block_data.get_daily_blocks()

4. Notion writes:
   a. page_id = notion_log.get_or_create_today_page()
      (This will return the same page created by the morning brief —
      the idempotency we built in Step 3 ensures no duplicate)
   b. notion_log.populate_block_data(
        page_id=page_id,
        asian_block=blocks['asian_block'],
        open_block=blocks['open_block'],
        session_block=blocks['session_block']
      )
   c. notion_url = notion_log.get_page_url(page_id)

5. Format a confirmation Telegram message (keep short):
   - Header: "📊 Block Data Captured — [today's date]"
   - Asian Block summary line
   - Open Block summary line
   - Session Block summary line
   - Footer: "📔 [Today's log](<notion_url>)"

6. Send via telegram_send.send_message()

7. Log success to stdout

Error handling:
- If block_data fetch fails, send Telegram alert and exit non-zero
- If Notion write fails, send Telegram alert with the block data
  values in the message body so I have them even if Notion is down
- If Telegram fails but Notion succeeded, log clearly

Test locally:
FORCE_RUN=1 uv run python -m src.end_of_day

(Note: this will only work properly during or after the trading day
when 5-minute data is available. Morning testing will return None
values for Open and Session blocks, which is expected.)

After verifying it works (test in the afternoon UK time for best
results), commit with message "Step 10: end-of-day capture orchestrator"

Do NOT build the GitHub Actions workflows yet.
```

---

## Step 11 — GitHub Actions workflows

**Tell Claude Code:** "Read CLAUDE.md and masterplan.md, then execute Step 11."

```
Execute Step 11: GitHub Actions Workflows.

Create both production workflow files for scheduled execution.

PART A: Create .github/workflows/morning-brief.yml

Requirements:
- Triggers:
  - Cron at 06:30 UTC AND 07:30 UTC on weekdays Mon–Fri (the dual
    cron handles BST/GMT — main.py's time check silently no-ops when
    not actually 07:25–07:35 UK local)
  - workflow_dispatch with input "force_run" (boolean, default false)
    that sets FORCE_RUN=1 in script env
- Runs on ubuntu-latest
- Steps:
  1. actions/checkout@v4
  2. astral-sh/setup-uv@v3
  3. uv sync
  4. uv run python -m src.main
- Environment variables (from secrets):
  - ANTHROPIC_API_KEY
  - TELEGRAM_BOT_TOKEN
  - TELEGRAM_CHAT_ID
  - NOTION_TOKEN
  - NOTION_DATABASE_ID
  - FORCE_RUN (from workflow_dispatch input, empty otherwise)

PART B: Create .github/workflows/end-of-day.yml

Requirements:
- Triggers:
  - Cron at 11:01 UTC AND 12:01 UTC on weekdays Mon–Fri (dual cron
    for BST/GMT, end_of_day.py's time check handles the gating)
  - workflow_dispatch with same force_run input
- Runs on ubuntu-latest
- Steps:
  1. actions/checkout@v4
  2. astral-sh/setup-uv@v3
  3. uv sync
  4. uv run python -m src.end_of_day
- Same environment variables as morning-brief.yml

PART C: Print the exact `gh secret set` commands I need to run to set
all secrets from my local .env values. Format example:
  echo "sk-ant-..." | gh secret set ANTHROPIC_API_KEY
List one command per secret in the order I should set them.

PART D: Walk me through:
1. Setting all GitHub secrets via the printed commands
2. Committing both workflow files with message "Step 11: GitHub Actions
   workflows for morning brief and end-of-day capture"
3. Pushing to GitHub
4. Triggering morning-brief manually with force_run=true via:
   gh workflow run morning-brief.yml -f force_run=true
5. Tailing the run with: gh run watch
6. Verifying the Telegram message arrives and the Notion page is created
7. Triggering end-of-day manually the same way and verifying

Do NOT build anything else. This step is purely workflow files and
verification.
```

---

## Step 12 — Production verification and handover

**Tell Claude Code:** "Read CLAUDE.md and masterplan.md, then execute Step 12."

```
Execute Step 12: Production Verification.

This is the final step. No new code. Verify everything works end-to-end
and the bot is ready for live use starting the next trading day.

Tasks:

1. Verify all GitHub secrets are set:
   gh secret list
   Should show: ANTHROPIC_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
   NOTION_TOKEN, NOTION_DATABASE_ID

2. Verify both workflows are visible in GitHub Actions:
   gh workflow list
   Should show: morning-brief, end-of-day

3. Trigger morning-brief manually with force_run=true:
   gh workflow run morning-brief.yml -f force_run=true
   Then: gh run watch
   Verify:
   - Telegram message arrives with Asian range, volatility expectation,
     liquidity, DXY direction
   - Tapping the link opens today's Notion page
   - Notion page has all sections populated correctly:
     * 🌅 Morning Brief
     * 📅 Key Events Today
     * 📰 Overnight Headlines
     * 📍 Key Levels & Context
     * 🌍 Correlations
   - Properties (Volatility Expectation, Liquidity Context, Asian
     High/Low/Range, Yesterday High/Low, DXY Direction) are set on
     the page

4. Trigger end-of-day manually with force_run=true:
   gh workflow run end-of-day.yml -f force_run=true
   Then: gh run watch
   Verify:
   - Telegram confirmation arrives with block data
   - Today's Notion page has the 📊 Daily Block Data section populated
   - No duplicate page was created (the same page from step 3)

5. Run the morning-brief workflow a SECOND time manually and verify
   no duplicate Notion content is added. This confirms idempotency
   in production, not just locally.

6. Update CLAUDE.md "Current status" section to read:
   "v1 live. Morning brief delivers at 07:30 UK weekdays, end-of-day
   capture at 12:01 PM UK weekdays. Strategy-agnostic context provider.
   Bot is in production."

7. Commit the CLAUDE.md update with message "Step 12: v1 production
   verified and live"

8. Print a final summary covering:
   - What runs automatically (morning brief, end-of-day capture)
   - What the user does manually (observation notes 8-10 AM, trade
     logging during session, end-of-day notes after session, weekly
     review on Saturday)
   - What is NOT in v1 (no IG API, no auto trade execution, no
     backtest builder, no signal generation, no setup recommendations)
   - The next trading day's expected first automated run time

Do not add any features. Do not propose v2 work. Step 12 is purely
verification and handover.
```

---

## After v1 is live

The bot is now in production. The next phase is **not** more building. It is:

1. **Use it for 30 days minimum** before considering any v2 features.
2. **Observe forward** during the 8–10 AM window each trading day. Write notes in the Observation Notes section of each day's Notion page. Specifically watch how the actual session compares to the brief's volatility expectation and the key levels.
3. **Do not trade live** until you have at least 4 weeks of observation in the current market regime.
4. **Develop your trading ideas from the data.** Look at the patterns in the captured block data, the relationship between volatility expectation and what actually happened, how price behaved at the levels the bot flagged. Your strategy should emerge from observed patterns, not be imposed before you've watched.
5. **Run the Saturday review** every weekend: fill in Volatility Actual, Brief Useful, Followed Rules, tags, and write a weekly summary in a separate "Weekly Reviews" Notion page.

Only after 30 days of v1 in real use should you consider any v2 features. By then you'll know what's actually missing.

---

## Risk rules (print this and stick it next to your monitor)

These are not negotiable. They go on a sticky note before you place a single live trade, *whatever strategy you eventually settle on*.

- **Risk per trade: 0.5% of account** (£10 on a £2,000 account)
- **Position size derived from stop distance**, not the other way around
- **Guaranteed stops on every London open trade** (the IG premium is small, slippage at 8 AM is real)
- **Take profit ≥ 2× stop distance** (1:2 R:R minimum)
- **One trade per day maximum** for the first 30 days of live trading
- **A+ setups only** — if your confidence is below 4/5, do not take it
- **Stop trading after two consecutive losses** for the day. Walk away.
- **Stop trading for the day after any rule violation** — the rule violation matters more than the outcome

If you cannot follow these, you should not be trading live. Go back to observation.

---

## Final reminder

The tool exists to serve the trading, not replace it. The bot gives you context every morning and captures data every afternoon. *You* develop the trading ideas from what you observe over weeks and months. If you spend more time fiddling with the bot than watching cable, you have the ratio wrong.

Ship v1, leave it alone, and put your hours into the screens.

Good luck.
