"""
Notion daily log module — one page per trading day.

Section detection approach: we list all page children and walk them in order,
tracking the current heading_2 section. When we find the target heading, we
look at the blocks that follow it (before the next heading_2) to determine
whether content already exists (idempotency guard).
"""

import logging
import os
from datetime import datetime

import pytz
from dotenv import load_dotenv
from notion_client import Client
from notion_client.errors import APIResponseError

load_dotenv()

logger = logging.getLogger(__name__)

LONDON = pytz.timezone("Europe/London")

SECTIONS = [
    "🌅 Morning Brief",
    "📅 Key Events Today",
    "📰 Overnight Headlines",
    "📍 Key Levels & Context",
    "🌍 Correlations",
    "📊 Daily Block Data",
    "👁️ Observation Notes",
    "📈 Trades",
    "📝 End of Day Notes",
]


def _client() -> Client:
    # Pin to 2022-06-28: notion-client v3 defaults to 2025-09-03 which removed
    # the databases/{id}/query endpoint that we rely on.
    return Client(auth=os.environ["NOTION_TOKEN"], notion_version="2022-06-28")


def _today_uk() -> datetime:
    return datetime.now(LONDON)


def _page_title(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d ") + dt.strftime("%a")


def _heading2(text: str) -> dict:
    return {
        "object": "block",
        "type": "heading_2",
        "heading_2": {"rich_text": [{"type": "text", "text": {"content": text}}]},
    }


def _paragraph(text: str) -> dict:
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": [{"type": "text", "text": {"content": text}}]},
    }


def _bullet(text: str) -> dict:
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {
            "rich_text": [{"type": "text", "text": {"content": text}}]
        },
    }


def _heading3(text: str) -> dict:
    return {
        "object": "block",
        "type": "heading_3",
        "heading_3": {"rich_text": [{"type": "text", "text": {"content": text}}]},
    }


def _get_section_blocks(notion: Client, page_id: str) -> dict[str, list]:
    """
    Return a mapping of section heading text → list of content blocks
    that follow that heading (up to the next heading_2).
    """
    sections: dict[str, list] = {s: [] for s in SECTIONS}
    current_section = None

    try:
        response = notion.blocks.children.list(block_id=page_id, page_size=100)
        blocks = response.get("results", [])
    except APIResponseError as e:
        logger.error("Failed to list page blocks: %s", e)
        return sections

    for block in blocks:
        btype = block.get("type")
        if btype == "heading_2":
            rich = block["heading_2"].get("rich_text", [])
            text = "".join(r.get("plain_text", "") for r in rich)
            current_section = text if text in sections else None
        elif current_section is not None:
            sections[current_section].append(block)

    return sections


def _append_blocks_to_section(
    notion: Client, page_id: str, section_heading: str, new_blocks: list
) -> None:
    """
    Find the heading_2 block matching section_heading and append new_blocks
    as children of the page after that heading (using the heading block ID
    as the after= anchor is not supported by Notion; we instead find the
    last block in the section and append after it, or append to the page
    and rely on order).

    Notion's append_block_children appends to the end of the block's
    children list. To insert after a specific heading we locate that
    heading block and append children to the page itself using
    after= parameter.
    """
    try:
        response = notion.blocks.children.list(block_id=page_id, page_size=100)
        blocks = response.get("results", [])
    except APIResponseError as e:
        logger.error("Failed to list page blocks for insertion: %s", e)
        return

    # Find the heading_2 block for the target section
    heading_block_id = None
    for block in blocks:
        if block.get("type") == "heading_2":
            rich = block["heading_2"].get("rich_text", [])
            text = "".join(r.get("plain_text", "") for r in rich)
            if text == section_heading:
                heading_block_id = block["id"]
                break

    if heading_block_id is None:
        logger.error("Section heading '%s' not found on page", section_heading)
        return

    # Find the last block in this section (to use as after= anchor)
    in_section = False
    last_block_id = heading_block_id
    for block in blocks:
        if block.get("type") == "heading_2":
            rich = block["heading_2"].get("rich_text", [])
            text = "".join(r.get("plain_text", "") for r in rich)
            if text == section_heading:
                in_section = True
                continue
            elif in_section:
                break
        if in_section:
            last_block_id = block["id"]

    try:
        notion.blocks.children.append(
            block_id=page_id,
            children=new_blocks,
            after=last_block_id,
        )
    except APIResponseError as e:
        logger.error("Failed to append blocks to section '%s': %s", section_heading, e)


def get_or_create_today_page() -> str:
    """Return the Notion page ID for today (UK time), creating it if needed."""
    notion = _client()
    db_id = os.environ["NOTION_DATABASE_ID"]
    today = _today_uk()
    today_start = LONDON.localize(
        datetime(today.year, today.month, today.day, 0, 0, 0)
    )
    today_iso = today_start.isoformat()
    # Notion date filter `equals` requires YYYY-MM-DD, not a full ISO string
    today_date_str = today_start.strftime("%Y-%m-%d")

    # Query for existing page with Date == today
    # notion-client v3 removed databases.query(); use raw request instead.
    try:
        results = notion.request(
            path=f"databases/{db_id}/query",
            method="POST",
            body={
                "filter": {
                    "property": "Date",
                    "date": {"equals": today_date_str},
                }
            },
        )
        pages = results.get("results", [])
        if pages:
            page_id = pages[0]["id"]
            logger.info("Found existing page: %s", page_id)
            return page_id
    except APIResponseError as e:
        logger.error("Failed to query Notion database: %s", e)
        raise

    # Create new page
    # Store Date as plain YYYY-MM-DD (no time/timezone) so the equals filter
    # always matches regardless of BST vs GMT — avoids the UTC conversion gotcha.
    title = _page_title(today)
    try:
        page = notion.pages.create(
            parent={"database_id": db_id},
            properties={
                "Name": {"title": [{"text": {"content": title}}]},
                "Date": {"date": {"start": today_date_str}},
            },
            children=[_heading2(s) for s in SECTIONS],
        )
        page_id = page["id"]
        logger.info("Created new page '%s': %s", title, page_id)
        return page_id
    except APIResponseError as e:
        logger.error("Failed to create Notion page: %s", e)
        raise


def populate_morning_brief(
    page_id: str,
    brief_text: str,
    headlines: list[dict],
    calendar: list[dict],
    levels_text: str,
    correlations_text: str,
    properties: dict,
) -> None:
    """
    Populate morning brief sections and update page properties.

    headlines: list of dicts with keys: source, title, published (HH:MM UTC)
    calendar: list of dicts with keys: time (HH:MM UK), country, event,
              forecast, previous
    properties: dict with keys matching Notion property names
    """
    notion = _client()
    section_blocks = _get_section_blocks(notion, page_id)

    # Morning Brief
    if not section_blocks["🌅 Morning Brief"]:
        _append_blocks_to_section(
            notion, page_id, "🌅 Morning Brief",
            [_paragraph(line) for line in brief_text.split("\n") if line.strip()],
        )
    else:
        logger.warning("'🌅 Morning Brief' already has content — skipping to avoid duplicate")

    # Overnight Headlines
    if not section_blocks["📰 Overnight Headlines"]:
        headline_blocks = [
            _bullet(f"[{h['source']}] {h['title']} ({h['published']})")
            for h in headlines
        ] or [_paragraph("No headlines found.")]
        _append_blocks_to_section(
            notion, page_id, "📰 Overnight Headlines", headline_blocks
        )
    else:
        logger.warning("'📰 Overnight Headlines' already has content — skipping")

    # Key Events Today
    if not section_blocks["📅 Key Events Today"]:
        calendar_blocks = []
        for ev in calendar:
            forecast = ev.get("forecast") or "n/a"
            previous = ev.get("previous") or "n/a"
            calendar_blocks.append(
                _bullet(
                    f"{ev['time_uk']} UK – {ev['country']} – {ev['event']} "
                    f"(forecast: {forecast}, previous: {previous})"
                )
            )
        if not calendar_blocks:
            calendar_blocks = [_paragraph("No medium/high impact events in window.")]
        _append_blocks_to_section(
            notion, page_id, "📅 Key Events Today", calendar_blocks
        )
    else:
        logger.warning("'📅 Key Events Today' already has content — skipping")

    # Key Levels & Context
    if not section_blocks["📍 Key Levels & Context"]:
        _append_blocks_to_section(
            notion, page_id, "📍 Key Levels & Context",
            [_paragraph(line) for line in levels_text.split("\n") if line.strip()],
        )
    else:
        logger.warning("'📍 Key Levels & Context' already has content — skipping")

    # Correlations
    if not section_blocks["🌍 Correlations"]:
        _append_blocks_to_section(
            notion, page_id, "🌍 Correlations",
            [_paragraph(line) for line in correlations_text.split("\n") if line.strip()],
        )
    else:
        logger.warning("'🌍 Correlations' already has content — skipping")

    # Update page properties
    prop_updates: dict = {}
    prop_map = {
        "Volatility Expectation": ("select", properties.get("volatility_expectation")),
        "Liquidity Context": ("select", properties.get("liquidity_context")),
        "Asian High": ("number", properties.get("asian_high")),
        "Asian Low": ("number", properties.get("asian_low")),
        "Asian Range (pips)": ("number", properties.get("asian_range_pips")),
        "Yesterday High": ("number", properties.get("yesterday_high")),
        "Yesterday Low": ("number", properties.get("yesterday_low")),
        "DXY Direction": ("select", properties.get("dxy_direction")),
    }
    for prop_name, (prop_type, value) in prop_map.items():
        if value is None:
            continue
        if prop_type == "select":
            prop_updates[prop_name] = {"select": {"name": value}}
        elif prop_type == "number":
            prop_updates[prop_name] = {"number": value}

    if prop_updates:
        try:
            notion.pages.update(page_id=page_id, properties=prop_updates)
        except APIResponseError as e:
            logger.error("Failed to update page properties: %s", e)


def populate_block_data(
    page_id: str,
    asian_block: dict,
    open_block: dict,
    session_block: dict,
) -> None:
    """
    Append block data under '📊 Daily Block Data'.

    Each *_block dict: high, low, range_pips, time_start, time_end
    """
    notion = _client()
    section_blocks = _get_section_blocks(notion, page_id)

    if section_blocks["📊 Daily Block Data"]:
        logger.warning("'📊 Daily Block Data' already has content — skipping")
        return

    lines = [
        (
            f"Asian Block ({asian_block['time_start']}–{asian_block['time_end']} UK): "
            f"High {asian_block['high']:.5f}, Low {asian_block['low']:.5f}, "
            f"Range {asian_block['range_pips']:.1f} pips"
        ),
        (
            f"Open Block ({open_block['time_start']}–{open_block['time_end']} UK): "
            f"High {open_block['high']:.5f}, Low {open_block['low']:.5f}, "
            f"Range {open_block['range_pips']:.1f} pips"
        ),
        (
            f"Session Block ({session_block['time_start']}–{session_block['time_end']} UK): "
            f"High {session_block['high']:.5f}, Low {session_block['low']:.5f}, "
            f"Range {session_block['range_pips']:.1f} pips"
        ),
    ]
    _append_blocks_to_section(
        notion, page_id, "📊 Daily Block Data",
        [_paragraph(line) for line in lines],
    )


def append_trade(page_id: str, trade: dict) -> None:
    """
    Append a trade entry under '📈 Trades' and increment Trades Taken.

    trade dict keys: number, direction, label, entry, stop, target,
                     size, confidence, reasoning
    """
    notion = _client()
    heading = f"Trade {trade['number']} — {trade['direction']} — {trade['label']}"
    blocks = [
        _heading3(heading),
        _paragraph(f"Entry: {trade.get('entry', '')}"),
        _paragraph(f"Stop: {trade.get('stop', '')}"),
        _paragraph(f"Target: {trade.get('target', '')}"),
        _paragraph(f"Size: {trade.get('size', '')}"),
        _paragraph(f"Confidence: {trade.get('confidence', '')}"),
        _paragraph(f"Reasoning: {trade.get('reasoning', '')}"),
    ]
    _append_blocks_to_section(notion, page_id, "📈 Trades", blocks)

    # Increment Trades Taken
    try:
        page = notion.pages.retrieve(page_id=page_id)
        current = page["properties"].get("Trades Taken", {}).get("number") or 0
        notion.pages.update(
            page_id=page_id,
            properties={"Trades Taken": {"number": current + 1}},
        )
    except APIResponseError as e:
        logger.error("Failed to increment Trades Taken: %s", e)


def append_end_of_day(
    page_id: str,
    summary_text: str,
    volatility_actual: str,
    net_r: float,
    net_gbp: float,
) -> None:
    """Append end-of-day notes and update outcome properties."""
    notion = _client()
    _append_blocks_to_section(
        notion, page_id, "📝 End of Day Notes",
        [_paragraph(line) for line in summary_text.split("\n") if line.strip()],
    )
    try:
        notion.pages.update(
            page_id=page_id,
            properties={
                "Volatility Actual": {"select": {"name": volatility_actual}},
                "Net R": {"number": net_r},
                "Net £": {"number": net_gbp},
            },
        )
    except APIResponseError as e:
        logger.error("Failed to update end-of-day properties: %s", e)


def get_page_url(page_id: str) -> str:
    """Return the Notion URL for a page."""
    clean_id = page_id.replace("-", "")
    return f"https://notion.so/{clean_id}"


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    print("--- Creating/fetching today's page ---")
    page_id = get_or_create_today_page()
    print(f"Page ID: {page_id}")
    print(f"URL: {get_page_url(page_id)}")

    print("\n--- Populating morning brief with dummy data ---")
    populate_morning_brief(
        page_id=page_id,
        brief_text="[TEST] Overnight range was quiet. No major moves.",
        headlines=[
            {"source": "Reuters", "title": "Test headline one", "published": "05:30 UTC"},
            {"source": "BBC", "title": "Test headline two", "published": "06:00 UTC"},
        ],
        calendar=[
            {
                "time": "09:30",
                "country": "UK",
                "event": "CPI YoY",
                "forecast": "3.1%",
                "previous": "3.4%",
            }
        ],
        levels_text="Yesterday High: 1.26900\nYesterday Low: 1.26400",
        correlations_text="DXY: Flat. Gold: Up slightly. ES: Flat.",
        properties={
            "volatility_expectation": "Normal",
            "liquidity_context": "Normal",
            "asian_high": 1.26845,
            "asian_low": 1.26512,
            "asian_range_pips": 33.3,
            "yesterday_high": 1.26900,
            "yesterday_low": 1.26400,
            "dxy_direction": "Flat",
        },
    )

    print("\n--- Populating block data with dummy values ---")
    populate_block_data(
        page_id=page_id,
        asian_block={"high": 1.26845, "low": 1.26512, "range_pips": 33.3, "time_start": "00:00", "time_end": "07:00"},
        open_block={"high": 1.26891, "low": 1.26677, "range_pips": 21.4, "time_start": "08:00", "time_end": "08:30"},
        session_block={"high": 1.27102, "low": 1.26588, "range_pips": 51.4, "time_start": "08:30", "time_end": "12:00"},
    )

    print("\n--- Idempotency check: calling get_or_create_today_page() again ---")
    page_id_2 = get_or_create_today_page()
    assert page_id == page_id_2, f"FAIL: got different IDs: {page_id} vs {page_id_2}"
    print("PASS: same page ID returned")

    print("\n--- Idempotency check: calling populate_morning_brief() again ---")
    populate_morning_brief(
        page_id=page_id,
        brief_text="[DUPLICATE — should not appear]",
        headlines=[],
        calendar=[],
        levels_text="[DUPLICATE]",
        correlations_text="[DUPLICATE]",
        properties={},
    )
    print("PASS: duplicate call completed (check Notion page for no duplicates)")

    print(f"\nDone. View page: {get_page_url(page_id)}")
