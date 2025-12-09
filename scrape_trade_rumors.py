import os
import sys
import time
import re
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional, Tuple
from urllib.parse import urlparse

import requests
from requests.auth import HTTPBasicAuth
from bs4 import BeautifulSoup
from dateutil import parser as dateparser
import pandas as pd

# ----------------------------------------------------------------------
# CONFIG
# ----------------------------------------------------------------------

BASE_URL = "http://preview.hoopshype.com/rumors/tag/trade"
OUTPUT_CSV = "trade_rumors.csv"
WINDOW_DAYS = 28
MAX_PAGES = 30

USERNAME = os.getenv("HH_PREVIEW_USER")
PASSWORD = os.getenv("HH_PREVIEW_PASS")

# NBA team names for team detection
NBA_TEAMS = {
    "HAWKS": "Atlanta Hawks", "CELTICS": "Boston Celtics", "NETS": "Brooklyn Nets",
    "HORNETS": "Charlotte Hornets", "BULLS": "Chicago Bulls", "CAVALIERS": "Cleveland Cavaliers",
    "CAVS": "Cleveland Cavaliers", "MAVERICKS": "Dallas Mavericks", "MAVS": "Dallas Mavericks",
    "NUGGETS": "Denver Nuggets", "PISTONS": "Detroit Pistons", "WARRIORS": "Golden State Warriors",
    "ROCKETS": "Houston Rockets", "PACERS": "Indiana Pacers", "CLIPPERS": "LA Clippers",
    "LAKERS": "Los Angeles Lakers", "GRIZZLIES": "Memphis Grizzlies", "HEAT": "Miami Heat",
    "BUCKS": "Milwaukee Bucks", "TIMBERWOLVES": "Minnesota Timberwolves", "WOLVES": "Minnesota Timberwolves",
    "PELICANS": "New Orleans Pelicans", "KNICKS": "New York Knicks", "THUNDER": "Oklahoma City Thunder",
    "MAGIC": "Orlando Magic", "76ERS": "Philadelphia 76ers", "SIXERS": "Philadelphia 76ers",
    "SUNS": "Phoenix Suns", "TRAIL BLAZERS": "Portland Trail Blazers", "BLAZERS": "Portland Trail Blazers",
    "KINGS": "Sacramento Kings", "SPURS": "San Antonio Spurs", "RAPTORS": "Toronto Raptors",
    "JAZZ": "Utah Jazz", "WIZARDS": "Washington Wizards"
}


# ----------------------------------------------------------------------
# UTILITIES
# ----------------------------------------------------------------------

def get_session() -> requests.Session:
    """Create an HTTP session with basic auth."""
    if not USERNAME or not PASSWORD:
        print("ERROR: HH_PREVIEW_USER / HH_PREVIEW_PASS environment variables not set.", file=sys.stderr)
        sys.exit(1)

    session = requests.Session()
    session.auth = HTTPBasicAuth(USERNAME, PASSWORD)
    session.headers.update({
        "User-Agent": "HH Trade Rumor Scraper (NBA Trade Rumor Heat Index)",
        "Accept-Language": "en-US,en;q=0.9",
    })
    return session


def load_players(path: str = "nba_players.txt") -> List[str]:
    """Load NBA player names from file, stored uppercase for matching."""
    players: List[str] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                name = line.strip()
                if name:
                    players.append(name.upper())
        print(f"Loaded {len(players)} players from {path}")
    except FileNotFoundError:
        print(f"WARNING: {path} not found. Player detection will be limited.")
    return players


def parse_date_from_text(text: str) -> Optional[date]:
    """Parse a date from text like 'November 27, 2025'."""
    text = text.strip()
    if not text:
        return None
    try:
        dt = dateparser.parse(text, fuzzy=True)
        return dt.date() if dt else None
    except Exception:
        return None


def guess_player(snippet: str, players_upper: List[str]) -> Optional[str]:
    """
    Find player mentioned in snippet using player list.
    Returns properly formatted name or None (never 'nan').
    """
    if not snippet:
        return None

    text_upper = snippet.upper()
    
    # Try to find the longest matching name first (handles "LeBron James" vs "James")
    matches = []
    for name_upper in players_upper:
        if name_upper in text_upper:
            matches.append(name_upper)
    
    if not matches:
        return None
    
    # Return the longest match (most specific)
    best_match = max(matches, key=len)
    
    # Convert back to title case properly
    # Handle special cases like "LeBron", "DeRozan", "McCollum"
    parts = best_match.split()
    formatted_parts = []
    for part in parts:
        # Check for common prefixes that need special handling
        if part.startswith("MC"):
            formatted_parts.append("Mc" + part[2:].capitalize())
        elif part.startswith("DE") and len(part) > 2:
            formatted_parts.append("De" + part[2:].capitalize())
        elif part.startswith("LE") and len(part) > 2:
            formatted_parts.append("Le" + part[2:].capitalize())
        elif part.startswith("LA") and len(part) > 2:
            formatted_parts.append("La" + part[2:].capitalize())
        else:
            formatted_parts.append(part.capitalize())
    
    return " ".join(formatted_parts)


def guess_teams(snippet: str) -> List[str]:
    """Find NBA teams mentioned in the snippet."""
    if not snippet:
        return []
    
    text_upper = snippet.upper()
    found_teams = set()
    
    for team_key, team_name in NBA_TEAMS.items():
        if team_key in text_upper:
            found_teams.add(team_name)
    
    return sorted(found_teams)


def extract_source_from_url(url: Optional[str]) -> Optional[str]:
    """Extract domain from URL as source."""
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
# SCRAPING
# ----------------------------------------------------------------------

def scrape_page(session: requests.Session,
                page: int,
                cutoff_date: date,
                players_upper: List[str]) -> Tuple[List[Dict], bool]:
    """
    Scrape a single page.
    Returns (rows, reached_older_than_cutoff_flag).
    """
    url = BASE_URL if page == 1 else f"{BASE_URL}?page={page}"

    print(f"Fetching {url}")
    resp = session.get(url, timeout=20)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    all_rumors = soup.select("div.rumor")
    print(f"Found {len(all_rumors)} rumors on page {page}")

    rows: List[Dict] = []
    reached_old = False

    if not all_rumors:
        return rows, True

    for rumor_div in all_rumors:
        # Find date holder
        date_holder = rumor_div.find_previous("div", class_="date-holder")
        if not date_holder:
            date_holder = rumor_div.find_previous(
                lambda tag: tag.name == "div" and "date" in " ".join(tag.get("class", []))
            )

        if not date_holder:
            continue

        date_text = date_holder.get_text(" ", strip=True)
        rumor_date = parse_date_from_text(date_text)
        if rumor_date is None:
            continue

        if rumor_date < cutoff_date:
            reached_old = True
            continue

        # Extract content
        snippet = rumor_div.get_text(" ", strip=True)
        
        link = rumor_div.find("a", href=True)
        url_val: Optional[str] = None
        title_val: Optional[str] = None

        if link:
            url_val = link["href"]
            title_val = link.get_text(" ", strip=True) or snippet[:140]
        else:
            title_val = snippet[:140]

        # Get player - only include if we find a valid player
        player_name = guess_player(snippet, players_upper)
        
        # Skip rumors where we can't identify a player
        if not player_name:
            continue
            
        # Get teams mentioned
        teams = guess_teams(snippet)
        team_str = ", ".join(teams) if teams else ""
        
        source_val = extract_source_from_url(url_val)

        row = {
            "date": rumor_date.isoformat(),
            "player": player_name,
            "team": team_str,
            "source": source_val or "",
            "snippet": snippet,
            "url": url_val or "",
            "title": title_val or "",
        }
        rows.append(row)

    print(f"Collected {len(rows)} valid rows from page {page}. Reached old date: {reached_old}")
    return rows, reached_old


def scrape() -> None:
    """Main scraping function."""
    session = get_session()
    players_upper = load_players()
    today = date.today()
    cutoff_date = today - timedelta(days=WINDOW_DAYS)
    print(f"Scraping rumors back to {cutoff_date.isoformat()} (WINDOW_DAYS = {WINDOW_DAYS})")

    all_rows: List[Dict] = []
    
    for page in range(1, MAX_PAGES + 1):
        rows, reached_old = scrape_page(session, page, cutoff_date, players_upper)

        if not rows and page > 1:
            print(f"No rows on page {page}, stopping pagination.")
            break

        all_rows.extend(rows)

        if reached_old:
            print("Reached cutoff date; stopping pagination.")
            break

        time.sleep(1.0)

    print(f"Total rows before dedup: {len(all_rows)}")

    if not all_rows:
        print("No rows collected; writing empty CSV.")
        df_empty = pd.DataFrame(
            columns=["date", "player", "team", "source", "snippet", "url", "title"]
        )
        df_empty.to_csv(OUTPUT_CSV, index=False)
        return

    df = pd.DataFrame(all_rows)
    
    # Clean up
    df = df[df["date"].notna()]
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    df = df[df["date"].notna()]
    df = df[df["date"] >= cutoff_date]
    
    # Remove any remaining invalid player entries
    df = df[df["player"].notna()]
    df = df[df["player"].str.strip() != ""]
    df = df[~df["player"].str.lower().isin(["nan", "none", ""])]
    
    # Dedup
    df = df.drop_duplicates(subset=["date", "player", "url", "snippet"])
    df = df.sort_values("date", ascending=False)

    print(f"Final row count: {len(df)}")
    df.to_csv(OUTPUT_CSV, index=False)
    print(f"Wrote {len(df)} rows to {OUTPUT_CSV}")


if __name__ == "__main__":
    scrape()
