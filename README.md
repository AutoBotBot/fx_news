# FX Morning Brief Bot

A personal automation bot that delivers a structured pre-session briefing for GBP/USD intraday trading during the London session.

The bot is strategy-agnostic — it provides structured context and captures structured data to support forward observation. It does not recommend setups or predict direction.

## Context

- See `CLAUDE.md` for full project context, architecture, and design principles.
- See `masterplan.md` for the numbered build steps.

## Development

Built step-by-step using Claude Code. Each session executes one numbered step from `masterplan.md` via the prompt:

> "Read CLAUDE.md and masterplan.md, then execute Step N."

## Setup

```bash
cp .env.example .env
# Fill in real values in .env
uv sync
```