import os
import sys
import time
import csv
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional
from urllib.parse import urlparse

import requests
from requests.auth import HTTPBasicAuth
from bs4 import BeautifulSoup
from dateutil import parser as dateparser
import pandas as pd

# ----------------------------------------------------------------------
# CONFIG
# ----------------------------------------------------------------------

# ⚠️ If your current file has a different base URL (e.g. preview.hoopshype.com),
# change this to match what you already had.
BASE_URL = "http://preview.hoopshype.com/rumors/tag/trade"

OUTPUT_CSV = "trade_rumors.csv"

# How many days back we care about
WINDOW_DAYS = 28

# Max number of pages to scan as a hard safety cap
MAX_PAGES = 30

USERNAME = os.getenv("HH_PREVIEW_USER")
PASSWORD = os.getenv("HH_PREVIEW_PASS")


# ----------------------------------------------------------------------
# UTILITIES
# ----------------------------------------------------------------------

def get_session() -> requests.Session:
    """
    Create an HTTP session with basic auth using HH_PREVIEW_USER / HH_PREVIEW_PASS.
    """
    if not USERNAME or not PASSWORD:
        print("ERROR: HH_PREVIEW_USER / HH_PREVIEW_PASS environment variables not set.", file=sys.stderr)
        sys.exit(1)

    session = requests.Session()
    session.auth = HTTPBasicAuth(USERNAME, PASSWORD)
    # Some basic headers just to be nice
    session.headers.update(
        {
            "User-Agent": "HH Trade Rumor Scraper (NBA Trade Rumor Heat Index)",
            "Accept-Language": "en-US,en;q=0.9",
        }
    )
    return session


def load_players(path: str = "nba_players.txt") -> List[str]:
    """
    Load NBA player names from a newline-separated file.
    We store them in UPPERCASE to make matching easier.
    """
    players: List[str] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                name = line.strip()
                if name:
                    players.append(name.upper())
        print(f"Loaded {len(players)} players from {path}")
    except FileNotFoundError:
        print(f"WARNING: {path} not found. Player detection will be very limited.")
    return players


def parse_date_from_text(text: str) -> Optional[date]:
    """
    Parse a date from a string like "November 27, 2025".
    Uses dateutil.parser with fuzzy matching.
    """
    text = text.strip()
    if not text:
        return None
    try:
        dt = dateparser.parse(text, fuzzy=True)
        if dt is None:
            return None
        return dt.date()
    except Exception:
        return None


def guess_player(snippet: str, players_upper: List[str]) -> Optional[str]:
    """
    Try to guess which player is mentioned in the snippet using nba_players.txt.
    We do a simple substring match on an uppercase version of the snippet.
    Returns the matched name in Title Case or None.
    """
    if not snippet:
        return None

    text_upper = snippet.upper()
    for name_upper in players_upper:
        if name_upper in text_upper:
            # convert "LEBRON JAMES" back to "LeBron James" reasonably
            return " ".join(part.capitalize() for part in name_upper.split())
    return None


def extract_source_from_url(url: Optional[str]) -> Optional[str]:
    """
    Derive a 'media outlet' style source from the URL's domain.
    E.g. https://www.espn.com/... -> "espn.com"
    """
    if not url:
        return None
    try:
        parsed = urlparse(url)
        host = parsed.netloc or ""
        if host.startswith("www."):
            host = host[4:]
        return host or None
    except Exception:
        return None


# ----------------------------------------------------------------------
# SCRAPING CORE
# ----------------------------------------------------------------------

def scrape_page(session: requests.Session,
                page: int,
                cutoff_date: date,
                players_upper: List[str]) -> (List[Dict], bool):
    """
    Scrape a single page.
    Returns (rows, reached_older_than_cutoff_flag).

    Strategy:
      * Select all div.rumor (20 per page).
      * For each rumor, look backwards in the DOM for the nearest div.date-holder.
      * That div.date-holder text is the date section for that rumor.
      * If that date is older than cutoff_date, we mark reached_old = True
        (so caller can stop pagination).
    """
    if page == 1:
        url = BASE_URL
    else:
        url = f"{BASE_URL}?page={page}"

    print(f"Fetching {url}")
    resp = session.get(url, timeout=20)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    # All rumor cards
    all_rumors = soup.select("div.rumor")
    print(f"Total div.rumor found on page {page}: {len(all_rumors)}")

    rows: List[Dict] = []
    reached_old = False

    if not all_rumors:
        # If there are literally no rumor blocks, likely we hit the end.
        return rows, True

    for rumor_div in all_rumors:
        # Find the nearest previous date-holder in the DOM
        date_holder = rumor_div.find_previous("div", class_="date-holder")
        if not date_holder:
            # Try a more generic search if needed (fallback)
            date_holder = rumor_div.find_previous(
                lambda tag: tag.name == "div" and "date" in " ".join(tag.get("class", []))
            )

        if not date_holder:
            # If we truly can't find a date, skip this rumor instead of guessing "today"
            continue

        date_text = date_holder.get_text(" ", strip=True)
        rumor_date = parse_date_from_text(date_text)
        if rumor_date is None:
            # Can't parse date; skip (better to have fewer rows than wrong dates)
            continue

        # Apply our 28-day window
        if rumor_date < cutoff_date:
            # We've gone past the window. Mark flag; keep going through rest of page
            # (in case some weird ordering exists), but we won't include this rumor.
            reached_old = True
            continue

        # Basic text for the snippet: whole block text
        snippet = rumor_div.get_text(" ", strip=True)

        # Find first hyperlink as the canonical URL and title
        link = rumor_div.find("a", href=True)
        url_val: Optional[str] = None
        title_val: Optional[str] = None

        if link:
            url_val = link["href"]
            title_val = link.get_text(" ", strip=True) or snippet[:140]
        else:
            # Fallbacks if somehow there is no link
            url_val = None
            title_val = snippet[:140]

        player_name = guess_player(snippet, players_upper)
        source_val = extract_source_from_url(url_val)

        row = {
            "date": rumor_date.isoformat(),
            "player": player_name or "",
            "team": "",   # reserved column; not parsed right now
            "source": source_val or "",
            "snippet": snippet,
            "url": url_val or "",
            "title": title_val or "",
        }
        rows.append(row)

    print(f"Collected {len(rows)} rows from page {page}. Reached old date: {reached_old}")
    return rows, reached_old


def scrape() -> None:
    """
    Scrape multiple pages until we either:
      * Hit an older date than our WINDOW_DAYS cutoff, or
      * Reach MAX_PAGES, or
      * Encounter a page with no div.rumor blocks.
    """
    session = get_session()
    players_upper = load_players()
    today = date.today()
    cutoff_date = today - timedelta(days=WINDOW_DAYS)
    print(f"Scraping rumors back to {cutoff_date.isoformat()} (WINDOW_DAYS = {WINDOW_DAYS})")

    all_rows: List[Dict] = []
    reached_old_global = False

    for page in range(1, MAX_PAGES + 1):
        rows, reached_old = scrape_page(session, page, cutoff_date, players_upper)

        if not rows and page > 1:
            # No rows from this page – assume we've hit the end
            print(f"No rows on page {page}, stopping pagination.")
            break

        all_rows.extend(rows)

        if reached_old:
            print("Encountered rumor(s) older than cutoff date; stopping pagination after this page.")
            reached_old_global = True
            break

        # Be nice to the server
        time.sleep(1.0)

    print(f"Total rows before de-dup / filtering: {len(all_rows)}")

    if not all_rows:
        print("No rows collected; writing empty CSV.")
        # Still write an empty CSV with the expected columns so the app doesn't crash.
        df_empty = pd.DataFrame(
            columns=["date", "player", "team", "source", "snippet", "url", "title"]
        )
        df_empty.to_csv(OUTPUT_CSV, index=False)
        return

    df = pd.DataFrame(all_rows)

    # Remove rows without a date or URL (if any slipped through)
    df = df[df["date"].notna()]

    # Ensure date column is true datetime for sorting and further processing
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    df = df[df["date"].notna()]

    # Enforce cutoff again just in case
    df = df[df["date"] >= cutoff_date]

    # Drop duplicates based on date, player, url, and snippet to keep the CSV tidy
    df = df.drop_duplicates(subset=["date", "player", "url", "snippet"])

    # Sort newest first
    df = df.sort_values("date", ascending=False)

    print(f"Total unique rows to write: {len(df)}")

    df.to_csv(OUTPUT_CSV, index=False)
    print(f"Wrote {len(df)} rows to {OUTPUT_CSV}")


# ----------------------------------------------------------------------
# ENTRY POINT
# ----------------------------------------------------------------------

if __name__ == "__main__":
    scrape()
