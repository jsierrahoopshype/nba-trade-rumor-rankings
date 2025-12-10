#!/usr/bin/env python3
"""
NBA Trade Rumor Rankings Scraper
Scrapes trade rumors from HoopsHype and ranks players by mention frequency.
Only includes players from nba_players.txt - no guessing.
"""

import os
import json
import re
from datetime import datetime, timedelta
from collections import defaultdict
from requests.auth import HTTPBasicAuth
import requests
from bs4 import BeautifulSoup
from dateutil import parser as date_parser

# Configuration
BASE_URL = "http://preview.hoopshype.com/rumors/tag/trade"
SCRAPE_WINDOW_DAYS = 28
MAX_PAGES = 100

# Weights for scoring
WEIGHT_WEEK1 = 1.0    # Last 7 days
WEIGHT_WEEK2 = 0.5    # Days 8-14
WEIGHT_WEEKS3_4 = 0.25  # Days 15-28


def load_known_players():
    """Load known NBA players from file. Returns set of lowercase names."""
    players = set()
    player_file = 'nba_players.txt'
    if os.path.exists(player_file):
        with open(player_file, 'r') as f:
            for line in f:
                name = line.strip()
                # Skip header or empty lines
                if name and name.upper() != 'PLAYER':
                    players.add(name.lower())
    print(f"Loaded {len(players)} known players from {player_file}")
    return players


def is_player_tag(tag_text, known_players):
    """Check if tag is a known player. Strict matching only."""
    tag_lower = tag_text.lower().strip()
    return tag_lower in known_players


def parse_date(date_str):
    """Parse date string from HoopsHype format."""
    # Format: "December 10, 2025 Updates"
    date_str = date_str.replace(' Updates', '').strip()
    try:
        return date_parser.parse(date_str).date()
    except:
        return None


def scrape_page(session, url, known_players, auth):
    """Scrape a single page of trade rumors."""
    rumors = []
    has_more = False
    oldest_date = None
    
    try:
        response = session.get(url, auth=auth, timeout=30)
        print(f"  HTTP {response.status_code} - {len(response.text)} bytes")
        
        if response.status_code != 200:
            print(f"  Error: HTTP {response.status_code}")
            return rumors, False, None
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Track current date as we parse
        current_date = None
        
        # Find all date holders and rumor divs
        date_holders = soup.find_all('div', class_='date-holder')
        rumor_divs = soup.find_all('div', class_='rumor')
        print(f"    Found {len(date_holders)} date holders, {len(rumor_divs)} rumors")
        
        # Process date holders and rumors in document order
        all_elements = soup.find_all('div', class_=['date-holder', 'rumor'])
        
        for element in all_elements:
            classes = element.get('class', [])
            
            # Check if this is a date holder
            if 'date-holder' in classes:
                date_div = element.find('div', class_='date')
                if date_div:
                    current_date = parse_date(date_div.get_text())
                    if current_date:
                        oldest_date = current_date
            
            # Check if this is a rumor
            elif 'rumor' in classes:
                if current_date is None:
                    continue
                
                # Find rumor text
                rumor_text_elem = element.find('p', class_='rumortext')
                rumor_text = rumor_text_elem.get_text(strip=True) if rumor_text_elem else ""
                
                # Find outlet
                outlet_elem = element.find('a', class_='rumormedia')
                outlet = outlet_elem.get_text(strip=True) if outlet_elem else "Unknown"
                
                # Find source URL
                source_elem = element.find('a', class_='quote') or element.find('a', class_='rumormedia')
                source_url = source_elem.get('href', '') if source_elem else ""
                
                # Find player tags - STRICT matching only
                tag_div = element.find('div', class_='tag')
                players_in_rumor = []
                
                if tag_div:
                    for tag_link in tag_div.find_all('a', class_='tag'):
                        tag_text = tag_link.get_text(strip=True)
                        if is_player_tag(tag_text, known_players):
                            players_in_rumor.append(tag_text)
                
                # Create rumor entry for each player mentioned
                for player in players_in_rumor:
                    rumors.append({
                        'date': current_date.isoformat(),
                        'player': player,
                        'text': rumor_text,  # Full text, no truncation
                        'outlet': outlet,
                        'source_url': source_url
                    })
        
        # Check for next page
        pager = soup.find('div', class_='pagernext')
        if pager and pager.find('a'):
            has_more = True
        
        # Count unique players found
        unique_players = set(r['player'] for r in rumors)
        print(f"    Found {len(rumors)} player mentions ({len(unique_players)} unique players)")
        
    except Exception as e:
        print(f"  Error scraping page: {e}")
        import traceback
        traceback.print_exc()
    
    return rumors, has_more, oldest_date


def scrape_all_rumors(username, password):
    """Scrape all trade rumors within the time window."""
    all_rumors = []
    known_players = load_known_players()
    
    if not known_players:
        print("WARNING: No known players loaded! Check nba_players.txt")
    
    session = requests.Session()
    auth = HTTPBasicAuth(username, password)
    
    cutoff_date = (datetime.now() - timedelta(days=SCRAPE_WINDOW_DAYS)).date()
    print(f"Scraping rumors from {cutoff_date} to today")
    
    page = 1
    while page <= MAX_PAGES:
        url = BASE_URL if page == 1 else f"{BASE_URL}?page={page}"
        print(f"Scraping page {page}: {url}")
        
        rumors, has_more, oldest_date = scrape_page(session, url, known_players, auth)
        all_rumors.extend(rumors)
        
        # Check if we've gone past our date window
        if oldest_date and oldest_date < cutoff_date:
            print(f"Reached cutoff date ({oldest_date} < {cutoff_date})")
            break
        
        if not has_more:
            print("No more pages")
            break
        
        page += 1
    
    # Filter to only include rumors within our window
    all_rumors = [r for r in all_rumors if r['date'] >= cutoff_date.isoformat()]
    
    print(f"\nTotal rumors collected: {len(all_rumors)}")
    return all_rumors


def calculate_rankings(rumors):
    """Calculate player rankings based on weighted mentions."""
    today = datetime.now().date()
    
    player_data = defaultdict(lambda: {
        'mentions_week1': 0,
        'mentions_week2': 0,
        'mentions_weeks3_4': 0,
        'total_mentions': 0,
        'first_mention': None,
        'last_mention': None,
        'rumors': [],
        'daily_counts': defaultdict(int)
    })
    
    for rumor in rumors:
        player = rumor['player']
        rumor_date = datetime.strptime(rumor['date'], '%Y-%m-%d').date()
        days_ago = (today - rumor_date).days
        
        # Update mention counts by time period
        if days_ago <= 7:
            player_data[player]['mentions_week1'] += 1
        elif days_ago <= 14:
            player_data[player]['mentions_week2'] += 1
        else:
            player_data[player]['mentions_weeks3_4'] += 1
        
        player_data[player]['total_mentions'] += 1
        player_data[player]['daily_counts'][rumor['date']] += 1
        
        # Track first/last mention dates
        if player_data[player]['first_mention'] is None or rumor['date'] < player_data[player]['first_mention']:
            player_data[player]['first_mention'] = rumor['date']
        if player_data[player]['last_mention'] is None or rumor['date'] > player_data[player]['last_mention']:
            player_data[player]['last_mention'] = rumor['date']
        
        # Store rumor details (avoid duplicates for same rumor)
        rumor_key = (rumor['date'], rumor['text'][:100])
        existing_keys = [(r['date'], r['text'][:100]) for r in player_data[player]['rumors']]
        if rumor_key not in existing_keys:
            player_data[player]['rumors'].append({
                'date': rumor['date'],
                'text': rumor['text'],
                'outlet': rumor['outlet'],
                'source_url': rumor['source_url']
            })
    
    # Calculate weighted scores
    rankings = []
    for player, data in player_data.items():
        score = (
            data['mentions_week1'] * WEIGHT_WEEK1 +
            data['mentions_week2'] * WEIGHT_WEEK2 +
            data['mentions_weeks3_4'] * WEIGHT_WEEKS3_4
        )
        rankings.append({
            'player': player,
            'score': round(score, 2),
            'mentions_week1': data['mentions_week1'],
            'mentions_week2': data['mentions_week2'],
            'mentions_weeks3_4': data['mentions_weeks3_4'],
            'total_mentions': data['total_mentions'],
            'first_mention': data['first_mention'],
            'last_mention': data['last_mention']
        })
    
    # Sort by score descending
    rankings.sort(key=lambda x: (-x['score'], -x['total_mentions'], x['player']))
    
    # Add ranks
    for i, r in enumerate(rankings, 1):
        r['rank'] = i
    
    return rankings, player_data


def main():
    """Main function."""
    # Get credentials from environment or use defaults
    username = os.environ.get('HH_PREVIEW_USER', 'preview')
    password = os.environ.get('HH_PREVIEW_PASS', 'hhpreview')
    
    print("=" * 60)
    print("NBA Trade Rumor Rankings Scraper")
    print("=" * 60)
    
    # Scrape rumors
    rumors = scrape_all_rumors(username, password)
    
    if not rumors:
        print("\nNo rumors found!")
        # Create empty data file
        data = {
            'generated_at': datetime.now().isoformat(),
            'scrape_window_days': SCRAPE_WINDOW_DAYS,
            'total_rumors': 0,
            'total_players': 0,
            'rankings': [],
            'player_rumors': {},
            'daily_counts': {}
        }
        with open('trade_rumor_data.json', 'w') as f:
            json.dump(data, f, indent=2)
        return
    
    # Calculate rankings
    rankings, player_data = calculate_rankings(rumors)
    
    print(f"\nTop 10 Players:")
    for r in rankings[:10]:
        print(f"  {r['rank']}. {r['player']}: {r['score']} pts ({r['total_mentions']} mentions)")
    
    # Prepare output data
    today = datetime.now().date()
    window_start = today - timedelta(days=SCRAPE_WINDOW_DAYS)
    
    output_data = {
        'generated_at': datetime.now().isoformat(),
        'scrape_window_days': SCRAPE_WINDOW_DAYS,
        'window_start': window_start.isoformat(),
        'window_end': today.isoformat(),
        'total_rumors': len(rumors),
        'total_players': len(rankings),
        'rankings': rankings,
        'player_rumors': {
            player: sorted(data['rumors'], key=lambda x: x['date'], reverse=True)
            for player, data in player_data.items()
        },
        'daily_counts': {
            player: dict(data['daily_counts'])
            for player, data in player_data.items()
        }
    }
    
    # Save to JSON
    with open('trade_rumor_data.json', 'w') as f:
        json.dump(output_data, f, indent=2)
    
    print(f"\nData saved to trade_rumor_data.json")
    print(f"Total players ranked: {len(rankings)}")


if __name__ == '__main__':
    main()
