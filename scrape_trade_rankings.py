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

BASE_URL = "http://preview.hoopshype.com/rumors/tag/trade"

OUTPUT_JSON = "trade_rumor_data.json"
OUTPUT_CSV = "trade_rumor_rankings.csv"

SCRAPE_DAYS = 28
MAX_PAGES = 50

USERNAME = os.getenv("HH_PREVIEW_USER", "preview")
PASSWORD = os.getenv("HH_PREVIEW_PASS", "hhpreview")

NBA_PLAYERS_FILE = "nba_players.txt"


# ----------------------------------------------------------------------
# UTILITIES
# ----------------------------------------------------------------------

def get_session() -> requests.Session:
    """Create authenticated session."""
    session = requests.Session()
    session.auth = HTTPBasicAuth(USERNAME, PASSWORD)
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    })
    return session


def load_nba_players() -> set:
    """Load known NBA player names."""
    players = set()
    try:
        with open(NBA_PLAYERS_FILE, "r", encoding="utf-8") as f:
            for line in f:
                name = line.strip()
                if name:
                    players.add(name.lower())
        print(f"Loaded {len(players)} NBA players from {NBA_PLAYERS_FILE}")
    except FileNotFoundError:
        print(f"WARNING: {NBA_PLAYERS_FILE} not found.")
    return players


def is_player_tag(tag_text: str, known_players: set) -> bool:
    """Check if a tag is a player name."""
    tag_lower = tag_text.lower().strip()
    
    # Exclude non-player tags
    non_player = {
        'trade', 'trades', 'free agency', 'free-agency', 'draft', 'injury',
        'contract', 'extension', 'buyout', 'waiver', 'signing', 'rumors',
        'nba', 'breaking', 'news', 'report', 'update', 'deal', 'talks',
        'hawks', 'celtics', 'nets', 'hornets', 'bulls', 'cavaliers', 'mavericks',
        'nuggets', 'pistons', 'warriors', 'rockets', 'pacers', 'clippers',
        'lakers', 'grizzlies', 'heat', 'bucks', 'timberwolves', 'pelicans',
        'knicks', 'thunder', 'magic', '76ers', 'sixers', 'suns', 'blazers',
        'trail blazers', 'kings', 'spurs', 'raptors', 'jazz', 'wizards',
        'atlanta', 'boston', 'brooklyn', 'charlotte', 'chicago', 'cleveland',
        'dallas', 'denver', 'detroit', 'golden state', 'houston', 'indiana',
        'los angeles', 'la', 'memphis', 'miami', 'milwaukee', 'minnesota',
        'new orleans', 'new york', 'oklahoma city', 'orlando', 'philadelphia',
        'phoenix', 'portland', 'sacramento', 'san antonio', 'toronto', 'utah',
        'washington', 'west', 'east', 'eastern', 'western', 'conference',
        'all-star', 'all star', 'playoffs', 'finals', 'championship'
    }
    
    if tag_lower in non_player:
        return False
    
    # Check known players
    if known_players and tag_lower in known_players:
        return True
    
    # Heuristic: 2-3 capitalized words = likely a name
    words = tag_text.split()
    if 2 <= len(words) <= 4:
        if all(word[0].isupper() for word in words if word):
            return True
    
    return False


def parse_date(text: str) -> Optional[date]:
    """Parse date from various formats."""
    from dateutil import parser as dateparser
    try:
        dt = dateparser.parse(text, fuzzy=True)
        return dt.date() if dt else None
    except:
        return None


# ----------------------------------------------------------------------
# SCRAPING
# ----------------------------------------------------------------------

def scrape_page(session: requests.Session, url: str, known_players: set) -> Tuple[List[Dict], bool, Optional[date]]:
    """
    Scrape a single page.
    Returns (rumors, has_more, oldest_date_on_page).
    """
    print(f"  Fetching {url}")
    
    try:
        response = session.get(url, timeout=30)
        print(f"  Status: {response.status_code}")
        
        if response.status_code == 401:
            print("  ERROR: Authentication failed!")
            return [], False, None
            
        response.raise_for_status()
    except Exception as e:
        print(f"  Error: {e}")
        return [], False, None
    
    soup = BeautifulSoup(response.text, "html.parser")
    
    # Debug: print page info
    print(f"  Page length: {len(response.text)} chars")
    
    # Try multiple selectors for rumors
    rumors_divs = soup.select("div.rumor")
    if not rumors_divs:
        rumors_divs = soup.select(".rumor")
    if not rumors_divs:
        rumors_divs = soup.select("div[class*='rumor']")
    
    print(f"  Found {len(rumors_divs)} rumor divs")
    
    # Debug: if no rumors found, print page structure
    if not rumors_divs:
        if "login" in response.text.lower() or "password" in response.text.lower():
            print("  WARNING: Looks like a login page - auth may have failed")
        
        print(f"  Page preview: {response.text[:1000]}...")
        
        all_divs = soup.find_all("div", class_=True)
        classes = set()
        for div in all_divs[:100]:
            classes.update(div.get("class", []))
        print(f"  Found div classes: {sorted(classes)[:30]}")
        
        return [], False, None
    
    rumors = []
    oldest_date = None
    current_date = None
    
    # Process all elements in document order
    for element in soup.find_all(["div"], class_=True):
        classes = element.get("class", [])
        class_str = " ".join(classes)
        
        # Date header - try multiple patterns
        if "date-holder" in classes or "date" in class_str:
            date_text = element.get_text(strip=True)
            parsed = parse_date(date_text)
            if parsed:
                current_date = parsed
                if oldest_date is None or parsed < oldest_date:
                    oldest_date = parsed
        
        # Rumor div
        if "rumor" in classes and "rumor-content" not in classes:
            # Try to get date from within rumor if not set
            if not current_date:
                date_span = element.find(class_="rumorDate")
                if not date_span:
                    date_span = element.find(class_="date")
                if date_span:
                    parsed = parse_date(date_span.get_text(strip=True))
                    if parsed:
                        current_date = parsed
            
            # Also check for date-holder that's a sibling/cousin
            if not current_date:
                prev = element.find_previous(class_="date-holder")
                if prev:
                    parsed = parse_date(prev.get_text(strip=True))
                    if parsed:
                        current_date = parsed
            
            if not current_date:
                # Skip if we really can't find a date
                continue
            
            # Extract tags
            tags_div = element.find(class_="tags")
            
            player_tags = []
            all_tags = []
            
            if tags_div:
                for tag_link in tags_div.find_all("a"):
                    tag_text = tag_link.get_text(strip=True)
                    if tag_text:
                        all_tags.append(tag_text)
                        if is_player_tag(tag_text, known_players):
                            player_tags.append(tag_text)
            
            # Skip rumors with no player tags
            if not player_tags:
                continue
            
            # Get rumor text
            text_elem = element.find(class_="rumor-content")
            if not text_elem:
                text_elem = element.find("p")
            rumor_text = text_elem.get_text(strip=True) if text_elem else element.get_text(strip=True)
            
            # Get source info
            outlet = ""
            source_url = ""
            if text_elem:
                media_link = text_elem.find(class_="rumormedia")
                if media_link:
                    outlet = media_link.get_text(strip=True)
                quote_link = text_elem.find(class_="quote")
                if quote_link:
                    source_url = quote_link.get("href", "")
            
            rumor = {
                "date": current_date.isoformat(),
                "players": player_tags,
                "all_tags": all_tags,
                "text": rumor_text[:500],
                "outlet": outlet,
                "source_url": source_url,
            }
            rumors.append(rumor)
            
            if oldest_date is None or current_date < oldest_date:
                oldest_date = current_date
    
    # Check for pagination
    has_more = False
    if soup.select_one("a.next") or soup.select_one("a[rel='next']"):
        has_more = True
    else:
        page_links = soup.select("a[href*='page=']")
        if page_links:
            has_more = True
    
    print(f"  Extracted {len(rumors)} rumors with player tags, oldest: {oldest_date}")
    return rumors, has_more, oldest_date


def scrape_all(days_back: int = SCRAPE_DAYS) -> List[Dict]:
    """Scrape all trade rumors."""
    session = get_session()
    known_players = load_nba_players()
    
    today = date.today()
    cutoff = today - timedelta(days=days_back)
    
    print(f"\nScraping trade rumors from {cutoff} to {today}")
    print("=" * 60)
    
    all_rumors = []
    seen = set()
    
    page = 1
    while page <= MAX_PAGES:
        if page == 1:
            url = BASE_URL
        else:
            url = f"{BASE_URL}?page={page}"
        
        rumors, has_more, oldest = scrape_page(session, url, known_players)
        
        if not rumors:
            print(f"  No rumors on page {page}, stopping.")
            break
        
        for rumor in rumors:
            rumor_date = date.fromisoformat(rumor["date"])
            
            if rumor_date < cutoff:
                continue
            
            # Dedup
            key = (rumor["date"], rumor["text"][:50])
            if key in seen:
                continue
            seen.add(key)
            
            all_rumors.append(rumor)
        
        if oldest and oldest < cutoff:
            print(f"  Reached cutoff date ({oldest} < {cutoff}), stopping.")
            break
        
        if not has_more:
            print(f"  No more pages.")
            break
        
        page += 1
        time.sleep(1)
    
    print(f"\n✅ Total rumors collected: {len(all_rumors)}")
    return all_rumors


# ----------------------------------------------------------------------
# SCORING
# ----------------------------------------------------------------------

def calculate_rankings(rumors: List[Dict]) -> pd.DataFrame:
    """Calculate weighted rankings."""
    today = date.today()
    
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
            
            if data["first_mention"] is None or rumor_date < date.fromisoformat(data["first_mention"]):
                data["first_mention"] = rumor["date"]
            if data["last_mention"] is None or rumor_date > date.fromisoformat(data["last_mention"]):
                data["last_mention"] = rumor["date"]
            
            if days_ago <= 7:
                data["mentions_0_7"] += 1
            elif days_ago <= 14:
                data["mentions_8_14"] += 1
            else:
                data["mentions_15_28"] += 1
    
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
    
    rankings.sort(key=lambda x: (-x["score"], -x["total_mentions"], x["player"]))
    
    for i, r in enumerate(rankings):
        r["rank"] = i + 1
    
    return pd.DataFrame(rankings)


def build_player_index(rumors: List[Dict]) -> Dict[str, List[Dict]]:
    """Build rumor index by player."""
    index = defaultdict(list)
    
    for rumor in rumors:
        for player in rumor["players"]:
            index[player].append({
                "date": rumor["date"],
                "text": rumor["text"],
                "outlet": rumor["outlet"],
                "source_url": rumor["source_url"],
            })
    
    for player in index:
        index[player].sort(key=lambda x: x["date"], reverse=True)
    
    return dict(index)


def build_daily_counts(rumors: List[Dict]) -> Dict[str, Dict[str, int]]:
    """Build daily counts per player."""
    counts = defaultdict(lambda: defaultdict(int))
    
    for rumor in rumors:
        for player in rumor["players"]:
            counts[player][rumor["date"]] += 1
    
    return {p: dict(d) for p, d in counts.items()}


# ----------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------

def main():
    print("🏀 NBA Trade Rumor Rankings Scraper")
    print("=" * 60)
    
    rumors = scrape_all(days_back=SCRAPE_DAYS)
    
    if not rumors:
        print("No rumors found!")
        # Create empty files so app doesn't crash
        empty_data = {
            "generated_at": datetime.now().isoformat(),
            "scrape_window_days": SCRAPE_DAYS,
            "total_rumors": 0,
            "total_players": 0,
            "rankings": [],
            "player_rumors": {},
            "daily_counts": {},
        }
        with open(OUTPUT_JSON, "w") as f:
            json.dump(empty_data, f, indent=2)
        print(f"Wrote empty {OUTPUT_JSON}")
        return
    
    print("\n📊 Calculating rankings...")
    rankings_df = calculate_rankings(rumors)
    print(f"Ranked {len(rankings_df)} players")
    
    player_rumors = build_player_index(rumors)
    daily_counts = build_daily_counts(rumors)
    
    rankings_df.to_csv(OUTPUT_CSV, index=False)
    print(f"✅ Saved {OUTPUT_CSV}")
    
    full_data = {
        "generated_at": datetime.now().isoformat(),
        "scrape_window_days": SCRAPE_DAYS,
        "total_rumors": len(rumors),
        "total_players": len(rankings_df),
        "rankings": rankings_df.to_dict(orient="records"),
        "player_rumors": player_rumors,
        "daily_counts": daily_counts,
    }
    
    with open(OUTPUT_JSON, "w") as f:
        json.dump(full_data, f, indent=2)
    print(f"✅ Saved {OUTPUT_JSON}")
    
    print("\n" + "=" * 60)
    print("🔥 TOP 15 TRADE RUMOR RANKINGS")
    print("=" * 60)
    print(f"{'Rank':<5} {'Player':<25} {'Score':<8} {'7d':<5} {'14d':<5} {'28d':<5}")
    print("-" * 60)
    
    for _, row in rankings_df.head(15).iterrows():
        print(f"{row['rank']:<5} {row['player']:<25} {row['score']:<8} {row['mentions_week1']:<5} {row['mentions_week2']:<5} {row['mentions_weeks3_4']:<5}")


if __name__ == "__main__":
    main()
