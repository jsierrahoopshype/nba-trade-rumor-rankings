import os
import sys
import time
from datetime import datetime, timedelta
from typing import List, Dict, Tuple

import requests
from bs4 import BeautifulSoup

import pandas as pd

# -------------------------------------------------------------------
# Configuration
# -------------------------------------------------------------------

BASE_URL = "http://preview.hoopshype.com/rumors/tag/trade"
OUTPUT_CSV = "trade_rumors.csv"

# How many days back we care about
WINDOW_DAYS = 28

# Safety: how many pages of /tag/trade to scan at most
MAX_PAGES = 15

# Simple headers so preview doesn’t get suspicious
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0 Safari/537.36"
    )
}


# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------

def get_session() -> requests.Session:
    """
    Create an authenticated requests session using HH_PREVIEW_USER/PASS.
    """
    user = os.getenv("HH_PREVIEW_USER")
    pwd = os.getenv("HH_PREVIEW_PASS")

    if not user or not pwd:
        print("ERROR: HH_PREVIEW_USER / HH_PREVIEW_PASS not set in environment.", file=sys.stderr)
        sys.exit(1)

    s = requests.Session()
    s.auth = (user, pwd)
    s.headers.update(HEADERS)
    return s


def load_players(path: str = "nba_players.txt") -> List[str]:
    """
    Load NBA player names from a text file, one per line.
    We keep both the original and a lowercase version for matching.
    """
    if not os.path.exists(path):
        print(f"WARNING: {path} not found. No players will be matched.", file=sys.stderr)
        return []

    players = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            name = line.strip()
            if name:
                players.append(name)

    print(f"Loaded {len(players)} players from {path}")
    return players


def norm(text: str) -> str:
    return text.lower().strip()


def parse_date_from_rumor_div(div) -> datetime:
    """
    Try to extract a date associated with a rumor div.

    We don't know the exact markup here, so we try a few reasonable
    options and fall back to 'today' if none are found.
    """
    # Strategy 1: attribute on the div (very common)
    possible_attrs = ["data-date", "data-date-iso", "data-published"]
    date_str = None
    for attr in possible_attrs:
        val = div.get(attr)
        if val:
            date_str = val
            break

    # Strategy 2: look for an element inside with plausible date text
    if not date_str:
        for cls in ["date", "time", "posted", "rumor-date"]:
            el = div.find(class_=cls)
            if el and el.get_text(strip=True):
                date_str = el.get_text(strip=True)
                break

    # Strategy 3: walk upwards to a parent with a date-like attribute
    if not date_str:
        parent = div.parent
        while parent is not None and parent.name not in ("body", "html"):
            for attr in possible_attrs:
                val = parent.get(attr)
                if val:
                    date_str = val
                    break
            if date_str:
                break
            parent = parent.parent

    if not date_str:
        # Fallback: assume "today" if we truly cannot find anything.
        return datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    # Let pandas handle the various human formats
    parsed = pd.to_datetime(date_str, errors="coerce", utc=True)
    if pd.isna(parsed):
        # Fallback again to today in UTC
        return datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    # Normalize to midnight (we only care about the date)
    parsed = parsed.tz_convert("UTC") if parsed.tzinfo is not None else parsed
    return parsed.replace(hour=0, minute=0, second=0, microsecond=0)


def extract_text_and_link(div) -> Tuple[str, str, str]:
    """
    Extract:
      - main text snippet for the rumor
      - media outlet (if we can spot it, otherwise '')
      - canonical rumor URL

    We'll be intentionally tolerant here.
    """
    # Try to find a main link for the rumor
    link_el = div.find("a", href=True)
    url = ""
    if link_el:
        url = link_el["href"]
        # Some previews might use relative URLs
        if url.startswith("/"):
            url = "https://hoopshype.com" + url

    # Full text of the rumor
    text = div.get_text(" ", strip=True)

    # Look for something that might be the outlet (e.g. italic or strong)
    outlet = ""
    outlet_el = div.find("i") or div.find("em") or div.find("strong")
    if outlet_el and outlet_el.get_text(strip=True):
        outlet = outlet_el.get_text(strip=True)

    return text, outlet, url


def find_players_in_text(text: str, players: List[str]) -> List[str]:
    """
    Return all player names that appear in the given text.
    We do a simple case-insensitive substring match.
    """
    text_norm = norm(text)
    found = []
    for name in players:
        if not name:
            continue
        if norm(name) in text_norm:
            found.append(name)
    return sorted(set(found))


def scrape_page(session: requests.Session, players: List[str], page: int,
                cutoff_date: datetime) -> Tuple[List[Dict], bool]:
    """
    Scrape a single /tag/trade page.

    Returns:
      rows: list of dicts for each (player, rumor)
      has_rumor_divs: True if the page contained any `div.rumor` at all
                      (even if we didn't match any players).
    """
    if page == 1:
        url = BASE_URL
    else:
        url = f"{BASE_URL}?page={page}"

    print(f"Fetching {url}")
    try:
        resp = session.get(url, timeout=30)
    except Exception as e:
        print(f"Request error on page {page}: {e}", file=sys.stderr)
        return [], False

    if resp.status_code != 200:
        print(f"Non-200 status code on page {page}: {resp.status_code}", file=sys.stderr)
        return [], False

    soup = BeautifulSoup(resp.text, "html.parser")

    # Core Hoopshype rumor cards
    all_rumors = soup.select("div.rumor")
    print("Total div.rumor found:", len(all_rumors))

    if not all_rumors:
        # No rumor blocks → we can stop paginating after this
        print(f"No div.rumor blocks on page {page}.")
        return [], False

    rows: List[Dict] = []
    cutoff_only_date = cutoff_date.date()

    for div in all_rumors:
        rumor_date = parse_date_from_rumor_div(div)
        if rumor_date.date() < cutoff_only_date:
            # This rumor is older than our 28-day window, but we **do not**
            # break pagination here; older rumors might still be on
            # later pages and we filter globally afterwards anyway.
            continue

        text, outlet, url = extract_text_and_link(div)

        matched_players = find_players_in_text(text, players)
        if not matched_players:
            # No player match → skip this rumor
            continue

        # TEAM: we don't have a robust way yet → leave blank.
        # (Streamlit side can still aggregate by player and date.)
        for player in matched_players:
            rows.append(
                {
                    "date": rumor_date.date().isoformat(),
                    "player": player,
                    "team": "",
                    "source": outlet,
                    "snippet": text,
                    "url": url,
                    "title": text[:140],  # simple short title
                }
            )

    print(f"Collected {len(rows)} rows from this page.")
    return rows, True


# -------------------------------------------------------------------
# Main scrape routine
# -------------------------------------------------------------------

def scrape():
    session = get_session()
    players = load_players()

    # 28-day cutoff (UTC)
    today_utc = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    cutoff_date = today_utc - timedelta(days=WINDOW_DAYS)

    all_rows: List[Dict] = []

    for page in range(1, MAX_PAGES + 1):
        page_rows, has_rumor_divs = scrape_page(session, players, page, cutoff_date)

        # ✅ KEY CHANGE: we **do not** stop just because page_rows == 0.
        # We only stop if there are no rumor divs at all (meaning no more pages).
        if not has_rumor_divs:
            print(f"Page {page} has no rumor blocks; stopping pagination.")
            break

        print(f"Page {page}: collected {len(page_rows)} rows.")
        all_rows.extend(page_rows)

        # Be polite to the preview site
        time.sleep(1)

    print(f"Total rows before de-dup / filtering: {len(all_rows)}")

    if not all_rows:
        print("No rows scraped at all; writing an empty CSV just in case.")
        df_empty = pd.DataFrame(
            columns=["date", "player", "team", "source", "snippet", "url", "title"]
        )
        df_empty.to_csv(OUTPUT_CSV, index=False)
        print(f"Wrote 0 rows to {OUTPUT_CSV}")
        return

    df = pd.DataFrame(all_rows)

    # Ensure date column is proper datetime for filtering & sorting
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"])

    # Apply final 28-day window filter (double safety)
    cutoff_only_date = cutoff_date.date()
    df = df[df["date"].dt.date >= cutoff_only_date].copy()

    # Sort newest first
    df = df.sort_values(["date", "player"], ascending=[False, True])

    # Drop exact duplicates
    df = df.drop_duplicates(
        subset=["date", "player", "snippet", "url"], keep="first"
    )

    print(f"Total unique rows to write: {len(df)}")

    df.to_csv(OUTPUT_CSV, index=False)
    print(f"Wrote {len(df)} rows to {OUTPUT_CSV}")


if __name__ == "__main__":
    scrape()
