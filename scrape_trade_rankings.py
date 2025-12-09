"""
NBA Trade Rumor Rankings Scraper
Extracts player tags from HoopsHype trade rumors and calculates weighted scores.

Scoring:
- 1.0 points: Last 7 days
- 0.5 points: Days 8-14
- 0.25 points: Days 15-28
"""

import os
import sys
import time
import json
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional, Tuple
from collections import defaultdict

import requests
from requests.auth import HTTPBasicAuth
from bs4 import BeautifulSoup
import pandas as pd

# ----------------------------------------------------------------------
# CONFIG
# ----------------------------------------------------------------------

# Trade rumors page
BASE_URL = "http://preview.hoopshype.com/rumors/tag/trade"
ARCHIVE_BASE = "http://preview.hoopshype.com/rumors/archive/rumors"

# Output files
OUTPUT_JSON = "trade_rumor_data.json"
OUTPUT_CSV = "trade_rumor_rankings.csv"

# How far back to scrape (28 days covers all scoring windows)
SCRAPE_DAYS = 28
MAX_PAGES_PER_DAY = 5

# Credentials
USERNAME = os.getenv("HH_PREVIEW_USER", "preview")
PASSWORD = os.getenv("HH_PREVIEW_PASS", "hhpreview")

# Known NBA players list (loaded from file)
NBA_PLAYERS_FILE = "nba_players.txt"


# ----------------------------------------------------------------------
# UTILITIES
# ----------------------------------------------------------------------

def get_session() -> requests.Session:
    """Create authenticated session."""
    session = requests.Session()
    session.auth = HTTPBasicAuth(USERNAME, PASSWORD)
    session.headers.update({
        "User-Agent": "HoopsHype Trade Rumor Rankings Bot",
        "Accept-Language": "en-US,en;q=0.9",
    })
    return session


def load_nba_players() -> set:
    """Load known NBA player names to filter tags."""
    players = set()
    try:
        with open(NBA_PLAYERS_FILE, "r", encoding="utf-8") as f:
            for line in f:
                name = line.strip()
                if name:
                    # Store normalized (lowercase) for comparison
                    players.add(name.lower())
        print(f"Loaded {len(players)} NBA players from {NBA_PLAYERS_FILE}")
    except FileNotFoundError:
        print(f"WARNING: {NBA_PLAYERS_FILE} not found. Will use all person-like tags.")
    return players


def is_player_tag(tag_text: str, tag_url: str, known_players: set) -> bool:
    """
    Determine if a tag is a player name.
    
    Checks:
    1. Is it in our known players list?
    2. Does the URL pattern suggest it's a player? (/player/ or person-like slug)
    3. Exclude known non-player tags (teams, topics, etc.)
    """
    tag_lower = tag_text.lower().strip()
    
    # Exclude obvious non-player tags
    non_player_tags = {
        'trade', 'trades', 'free agency', 'free-agency', 'draft', 'injury',
        'contract', 'extension', 'buyout', 'waiver', 'signing', 'rumors',
        'nba', 'breaking', 'news', 'report', 'update', 'deal', 'talks',
        # Team names
        'hawks', 'celtics', 'nets', 'hornets', 'bulls', 'cavaliers', 'mavericks',
        'nuggets', 'pistons', 'warriors', 'rockets', 'pacers', 'clippers',
        'lakers', 'grizzlies', 'heat', 'bucks', 'timberwolves', 'pelicans',
        'knicks', 'thunder', 'magic', '76ers', 'sixers', 'suns', 'blazers',
        'trail blazers', 'kings', 'spurs', 'raptors', 'jazz', 'wizards',
        # Cities
        'atlanta', 'boston', 'brooklyn', 'charlotte', 'chicago', 'cleveland',
        'dallas', 'denver', 'detroit', 'golden state', 'houston', 'indiana',
        'los angeles', 'la', 'memphis', 'miami', 'milwaukee', 'minnesota',
        'new orleans', 'new york', 'oklahoma city', 'orlando', 'philadelphia',
        'phoenix', 'portland', 'sacramento', 'san antonio', 'toronto', 'utah',
        'washington'
    }
    
    if tag_lower in non_player_tags:
        return False
    
    # Check if in known players list
    if known_players and tag_lower in known_players:
        return True
    
    # Check URL pattern - player tags often have /player/ or similar
    if '/player/' in tag_url.lower():
        return True
    
    # Heuristic: if it looks like a name (2-3 words, each capitalized)
    words = tag_text.split()
    if 2 <= len(words) <= 4:
        # Check if words look like a name (start with capital, rest lowercase-ish)
        if all(word[0].isupper() for word in words if word):
            # Additional check: not a known non-player phrase
            return True
    
    return False


def parse_date_text(text: str) -> Optional[date]:
    """Parse date from text like 'December 9, 2025'."""
    from dateutil import parser as dateparser
    try:
        dt = dateparser.parse(text, fuzzy=True)
        return dt.date() if dt else None
    except:
        return None


# ----------------------------------------------------------------------
# SCRAPING
# ----------------------------------------------------------------------

def scrape_rumors_page(session: requests.Session, url: str, known_players: set) -> List[Dict]:
    """
    Scrape a single page of trade rumors.
    Returns list of rumor dicts with player tags extracted.
    """
    try:
        response = session.get(url, timeout=20)
        response.raise_for_status()
    except Exception as e:
        print(f"  Error fetching {url}: {e}")
        return []
    
    soup = BeautifulSoup(response.text, "html.parser")
    rumors = []
    
    # Find all rumor divs
    rumor_divs = soup.select("div.rumor")
    
    current_date = None
    
    for rumor_div in rumor_divs:
        # Find the date for this rumor (from preceding date-holder)
        date_holder = rumor_div.find_previous("div", class_="date-holder")
        if date_holder:
            date_text = date_holder.get_text(strip=True)
            parsed_date = parse_date_text(date_text)
            if parsed_date:
                current_date = parsed_date
        
        if not current_date:
            continue
        
        # Extract tags
        tags_div = rumor_div.find("div", class_="tags")
        player_tags = []
        all_tags = []
        
        if tags_div:
            for tag_link in tags_div.find_all("a"):
                tag_text = tag_link.get_text(strip=True)
                tag_url = tag_link.get("href", "")
                all_tags.append(tag_text)
                
                if is_player_tag(tag_text, tag_url, known_players):
                    player_tags.append(tag_text)
        
        # Skip rumors with no player tags
        if not player_tags:
            continue
        
        # Get rumor text
        rumor_text_p = rumor_div.find("p", class_="rumor-content")
        rumor_text = rumor_text_p.get_text(strip=True) if rumor_text_p else ""
        
        # Get source URL and outlet
        source_url = ""
        outlet = ""
        if rumor_text_p:
            quote_link = rumor_text_p.find("a", class_="quote")
            if quote_link:
                source_url = quote_link.get("href", "")
            media_link = rumor_text_p.find("a", class_="rumormedia")
            if media_link:
                outlet = media_link.get_text(strip=True)
        
        rumor = {
            "date": current_date.isoformat(),
            "players": player_tags,
            "all_tags": all_tags,
            "text": rumor_text[:500],  # Truncate for storage
            "outlet": outlet,
            "source_url": source_url,
        }
        rumors.append(rumor)
    
    return rumors


def scrape_trade_tag_page(session: requests.Session, page: int, known_players: set) -> Tuple[List[Dict], bool]:
    """
    Scrape the /rumors/tag/trade page (paginated).
    Returns (rumors, has_more_pages).
    """
    if page == 1:
        url = BASE_URL
    else:
        url = f"{BASE_URL}?page={page}"
    
    print(f"  Fetching {url}")
    rumors = scrape_rumors_page(session, url, known_players)
    
    # Check if there are more pages (look for pagination)
    try:
        response = session.get(url, timeout=20)
        soup = BeautifulSoup(response.text, "html.parser")
        # Look for "next" link or page numbers
        has_more = soup.select_one("a.next") is not None or soup.select_one(f'a[href*="page={page+1}"]') is not None
    except:
        has_more = False
    
    return rumors, has_more


def scrape_all_rumors(days_back: int = SCRAPE_DAYS) -> List[Dict]:
    """
    Scrape trade rumors from the last N days.
    Uses both the tag page and archive pages.
    """
    session = get_session()
    known_players = load_nba_players()
    
    today = date.today()
    cutoff = today - timedelta(days=days_back)
    
    all_rumors = []
    seen_texts = set()  # For deduplication
    
    print(f"\nScraping trade rumors from {cutoff} to {today}")
    print("=" * 60)
    
    # First, scrape the main /rumors/tag/trade pages
    print("\n📰 Scraping /rumors/tag/trade pages...")
    page = 1
    oldest_date_seen = today
    
    while page <= 50:  # Safety limit
        rumors, has_more = scrape_trade_tag_page(session, page, known_players)
        
        if not rumors:
            print(f"  No rumors on page {page}, stopping.")
            break
        
        for rumor in rumors:
            rumor_date = date.fromisoformat(rumor["date"])
            oldest_date_seen = min(oldest_date_seen, rumor_date)
            
            # Skip if older than cutoff
            if rumor_date < cutoff:
                continue
            
            # Dedup by text snippet
            text_key = rumor["text"][:100]
            if text_key in seen_texts:
                continue
            seen_texts.add(text_key)
            
            all_rumors.append(rumor)
        
        print(f"  Page {page}: {len(rumors)} rumors (oldest: {oldest_date_seen})")
        
        # Stop if we've gone past our window
        if oldest_date_seen < cutoff:
            print(f"  Reached cutoff date, stopping pagination.")
            break
        
        if not has_more:
            break
        
        page += 1
        time.sleep(0.5)
    
    print(f"\n✅ Total rumors collected: {len(all_rumors)}")
    return all_rumors


# ----------------------------------------------------------------------
# SCORING & RANKING
# ----------------------------------------------------------------------

def calculate_rankings(rumors: List[Dict]) -> pd.DataFrame:
    """
    Calculate player rankings based on weighted scoring.
    
    Scoring:
    - 1.0 points: Last 7 days
    - 0.5 points: Days 8-14  
    - 0.25 points: Days 15-28
    """
    today = date.today()
    
    # Aggregate by player
    player_data = defaultdict(lambda: {
        "mentions_0_7": 0,
        "mentions_8_14": 0,
        "mentions_15_28": 0,
        "total_mentions": 0,
        "rumors": [],
        "first_mention": None,
        "last_mention": None,
    })
    
    for rumor in rumors:
        rumor_date = date.fromisoformat(rumor["date"])
        days_ago = (today - rumor_date).days
        
        for player in rumor["players"]:
            data = player_data[player]
            data["total_mentions"] += 1
            data["rumors"].append(rumor)
            
            # Track first/last mention
            if data["first_mention"] is None or rumor_date < date.fromisoformat(data["first_mention"]):
                data["first_mention"] = rumor["date"]
            if data["last_mention"] is None or rumor_date > date.fromisoformat(data["last_mention"]):
                data["last_mention"] = rumor["date"]
            
            # Categorize by recency
            if days_ago <= 7:
                data["mentions_0_7"] += 1
            elif days_ago <= 14:
                data["mentions_8_14"] += 1
            else:
                data["mentions_15_28"] += 1
    
    # Calculate scores
    rankings = []
    for player, data in player_data.items():
        score = (
            data["mentions_0_7"] * 1.0 +
            data["mentions_8_14"] * 0.5 +
            data["mentions_15_28"] * 0.25
        )
        
        rankings.append({
            "player": player,
            "score": round(score, 2),
            "mentions_week1": data["mentions_0_7"],
            "mentions_week2": data["mentions_8_14"],
            "mentions_weeks3_4": data["mentions_15_28"],
            "total_mentions": data["total_mentions"],
            "first_mention": data["first_mention"],
            "last_mention": data["last_mention"],
        })
    
    # Sort by score descending
    rankings.sort(key=lambda x: (-x["score"], -x["total_mentions"], x["player"]))
    
    # Add rank
    for i, r in enumerate(rankings):
        r["rank"] = i + 1
    
    return pd.DataFrame(rankings)


def build_player_rumors_index(rumors: List[Dict]) -> Dict[str, List[Dict]]:
    """Build an index of rumors by player for the detail pages."""
    index = defaultdict(list)
    
    for rumor in rumors:
        for player in rumor["players"]:
            # Store a simplified version for the index
            index[player].append({
                "date": rumor["date"],
                "text": rumor["text"],
                "outlet": rumor["outlet"],
                "source_url": rumor["source_url"],
            })
    
    # Sort each player's rumors by date descending
    for player in index:
        index[player].sort(key=lambda x: x["date"], reverse=True)
    
    return dict(index)


def build_daily_counts(rumors: List[Dict]) -> Dict[str, Dict[str, int]]:
    """Build daily mention counts per player for timeline charts."""
    counts = defaultdict(lambda: defaultdict(int))
    
    for rumor in rumors:
        for player in rumor["players"]:
            counts[player][rumor["date"]] += 1
    
    return {player: dict(dates) for player, dates in counts.items()}


# ----------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------

def main():
    print("🏀 NBA Trade Rumor Rankings Scraper")
    print("=" * 60)
    
    # Scrape rumors
    rumors = scrape_all_rumors(days_back=SCRAPE_DAYS)
    
    if not rumors:
        print("No rumors found!")
        return
    
    # Calculate rankings
    print("\n📊 Calculating rankings...")
    rankings_df = calculate_rankings(rumors)
    print(f"Ranked {len(rankings_df)} players")
    
    # Build supporting data
    player_rumors = build_player_rumors_index(rumors)
    daily_counts = build_daily_counts(rumors)
    
    # Save rankings CSV
    rankings_df.to_csv(OUTPUT_CSV, index=False)
    print(f"✅ Saved rankings to {OUTPUT_CSV}")
    
    # Save full data JSON (for the web app)
    full_data = {
        "generated_at": datetime.now().isoformat(),
        "scrape_window_days": SCRAPE_DAYS,
        "total_rumors": len(rumors),
        "total_players": len(rankings_df),
        "rankings": rankings_df.to_dict(orient="records"),
        "player_rumors": player_rumors,
        "daily_counts": daily_counts,
    }
    
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(full_data, f, indent=2)
    print(f"✅ Saved full data to {OUTPUT_JSON}")
    
    # Print top 15
    print("\n" + "=" * 60)
    print("🔥 TOP 15 TRADE RUMOR RANKINGS")
    print("=" * 60)
    print(f"{'Rank':<5} {'Player':<25} {'Score':<8} {'7d':<5} {'14d':<5} {'28d':<5}")
    print("-" * 60)
    
    for _, row in rankings_df.head(15).iterrows():
        print(f"{row['rank']:<5} {row['player']:<25} {row['score']:<8} {row['mentions_week1']:<5} {row['mentions_week2']:<5} {row['mentions_weeks3_4']:<5}")


if __name__ == "__main__":
    main()
