#!/usr/bin/env python3
"""
NBA Trade Rumor Rankings Scraper
Scrapes trade rumors from HoopsHype and ranks players by mention frequency.
Preserves hyperlinks in rumor text.
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

# Accurate 2025-26 player-team mapping
PLAYER_TEAMS_2025 = {
    'Giannis Antetokounmpo': 'Milwaukee Bucks',
    'Anthony Davis': 'Dallas Mavericks',
    'Ja Morant': 'Memphis Grizzlies',
    'LaMelo Ball': 'Charlotte Hornets',
    'Terry Rozier': 'Miami Heat',
    'Jonathan Kuminga': 'Golden State Warriors',
    'Keon Ellis': 'Sacramento Kings',
    'Domantas Sabonis': 'Sacramento Kings',
    'Kyrie Irving': 'Dallas Mavericks',
    "D'Angelo Russell": 'Dallas Mavericks',
    'Daniel Gafford': 'Dallas Mavericks',
    'Trae Young': 'Atlanta Hawks',
    'Zach LaVine': 'Sacramento Kings',
    'Herb Jones': 'New Orleans Pelicans',
    'Herbert Jones': 'New Orleans Pelicans',
    'James Harden': 'Los Angeles Clippers',
    'Klay Thompson': 'Dallas Mavericks',
    'Trey Murphy': 'New Orleans Pelicans',
    'Trey Murphy III': 'New Orleans Pelicans',
    'Anfernee Simons': 'Boston Celtics',
    'Andrew Wiggins': 'Miami Heat',
    'DeMar DeRozan': 'Sacramento Kings',
    'Sam Hauser': 'Boston Celtics',
    'Bobby Portis': 'Milwaukee Bucks',
    'Chris Paul': 'Los Angeles Clippers',
    'Ivica Zubac': 'Los Angeles Clippers',
    'Karl-Anthony Towns': 'New York Knicks',
    'Kawhi Leonard': 'Los Angeles Clippers',
    "Kel'el Ware": 'Miami Heat',
    'LeBron James': 'Los Angeles Lakers',
    'Luka Doncic': 'Los Angeles Lakers',
    'Luka Dončić': 'Los Angeles Lakers',
    'Malik Monk': 'Sacramento Kings',
    'Myles Turner': 'Milwaukee Bucks',
    'Pelle Larsson': 'Miami Heat',
    'Stephon Castle': 'San Antonio Spurs',
    'Walker Kessler': 'Utah Jazz',
    'Zion Williamson': 'New Orleans Pelicans',
    'Lauri Markkanen': 'Utah Jazz',
    'Keegan Murray': 'Sacramento Kings',
    'Anthony Edwards': 'Minnesota Timberwolves',
    'Brandon Ingram': 'Toronto Raptors',
    'Buddy Hield': 'Golden State Warriors',
    'Devin Booker': 'Phoenix Suns',
    'Jaden McDaniels': 'Minnesota Timberwolves',
    'Josh Hart': 'New York Knicks',
    'Kyle Kuzma': 'Milwaukee Bucks',
    'Lonzo Ball': 'Cleveland Cavaliers',
    'Max Christie': 'Dallas Mavericks',
    'Nick Richards': 'Phoenix Suns',
    'Robert Williams': 'Portland Trail Blazers',
    'Robert Williams III': 'Portland Trail Blazers',
    'Kevin Porter': 'Milwaukee Bucks',
    'Kevin Porter Jr.': 'Milwaukee Bucks',
    'Dylan Harper': 'San Antonio Spurs',
    'Julius Randle': 'Minnesota Timberwolves',
    'Pascal Siakam': 'Indiana Pacers',
    'Jimmy Butler': 'Golden State Warriors',
    'Jimmy Butler III': 'Golden State Warriors',
    'Bradley Beal': 'Los Angeles Clippers',
    'Dejounte Murray': 'New Orleans Pelicans',
    'Nikola Vucevic': 'Chicago Bulls',
    'Nikola Vučević': 'Chicago Bulls',
    'Marcus Smart': 'Los Angeles Lakers',
    'Jarrett Allen': 'Cleveland Cavaliers',
    'Collin Sexton': 'Charlotte Hornets',
    'Jordan Clarkson': 'New York Knicks',
    'John Collins': 'Los Angeles Clippers',
    'Cameron Johnson': 'Denver Nuggets',
    'Dorian Finney-Smith': 'Los Angeles Lakers',
    'Bruce Brown': 'Denver Nuggets',
    'Jakob Poeltl': 'Toronto Raptors',
    'OG Anunoby': 'New York Knicks',
    'Mikal Bridges': 'New York Knicks',
    'Jalen Brunson': 'New York Knicks',
    'Tyrese Haliburton': 'Indiana Pacers',
    'Cade Cunningham': 'Detroit Pistons',
    'Scottie Barnes': 'Toronto Raptors',
    'Evan Mobley': 'Cleveland Cavaliers',
    'Franz Wagner': 'Orlando Magic',
    'Paolo Banchero': 'Orlando Magic',
    'Victor Wembanyama': 'San Antonio Spurs',
    'Chet Holmgren': 'Oklahoma City Thunder',
    'Shai Gilgeous-Alexander': 'Oklahoma City Thunder',
    'Jayson Tatum': 'Boston Celtics',
    'Jaylen Brown': 'Boston Celtics',
    'Donovan Mitchell': 'Cleveland Cavaliers',
    'Bam Adebayo': 'Miami Heat',
    'Tyler Herro': 'Miami Heat',
    "De'Aaron Fox": 'San Antonio Spurs',
    'Alperen Sengun': 'Houston Rockets',
    'Jalen Green': 'Phoenix Suns',
    'Amen Thompson': 'Houston Rockets',
    'Jabari Smith Jr.': 'Houston Rockets',
    'Desmond Bane': 'Orlando Magic',
    'Jaren Jackson Jr.': 'Memphis Grizzlies',
    'Jalen Williams': 'Oklahoma City Thunder',
    'Darius Garland': 'Cleveland Cavaliers',
    'Coby White': 'Chicago Bulls',
    'Ayo Dosunmu': 'Chicago Bulls',
    'Patrick Williams': 'Chicago Bulls',
    'Kevin Durant': 'Houston Rockets',
    'Austin Reaves': 'Los Angeles Lakers',
    'Jamal Murray': 'Denver Nuggets',
    'Stephen Curry': 'Golden State Warriors',
    'Norman Powell': 'Miami Heat',
    'Michael Porter Jr.': 'Brooklyn Nets',
    'Jalen Johnson': 'Atlanta Hawks',
    'Miles Bridges': 'Charlotte Hornets',
    'Tyrese Maxey': 'Philadelphia 76ers',
    'Nikola Jokic': 'Denver Nuggets',
    'Nikola Jokić': 'Denver Nuggets',
    'Deni Avdija': 'Portland Trail Blazers',
    'Immanuel Quickley': 'Toronto Raptors',
    'Payton Pritchard': 'Boston Celtics',
    'CJ McCollum': 'Washington Wizards',
    'Derrick White': 'Boston Celtics',
    'Dillon Brooks': 'Phoenix Suns',
    'Jalen Duren': 'Detroit Pistons',
    'Onyeka Okongwu': 'Atlanta Hawks',
    'Jaime Jaquez Jr.': 'Miami Heat',
    'Deandre Ayton': 'Los Angeles Lakers',
    'Naz Reid': 'Minnesota Timberwolves',
    'P.J. Washington': 'Dallas Mavericks',
    'Donte DiVincenzo': 'Minnesota Timberwolves',
    'Santi Aldama': 'Memphis Grizzlies',
    'Naji Marshall': 'Dallas Mavericks',
    'Brandin Podziemski': 'Golden State Warriors',
    'Nic Claxton': 'Brooklyn Nets',
    'Harrison Barnes': 'San Antonio Spurs',
    'Rui Hachimura': 'Los Angeles Lakers',
    'Alex Sarr': 'Washington Wizards',
    'Jalen Suggs': 'Orlando Magic',
    'Keldon Johnson': 'San Antonio Spurs',
    'Andrew Nembhard': 'Indiana Pacers',
    'Wendell Carter Jr.': 'Orlando Magic',
    'Bennedict Mathurin': 'Indiana Pacers',
    'Reed Sheppard': 'Houston Rockets',
    'Grayson Allen': 'Phoenix Suns',
    'Dyson Daniels': 'Atlanta Hawks',
    'Moses Moody': 'Golden State Warriors',
    'Rudy Gobert': 'Minnesota Timberwolves',
    'Mark Williams': 'Phoenix Suns',
    'Aaron Gordon': 'Denver Nuggets',
    'Zaccharie Risacher': 'Atlanta Hawks',
    'Gary Trent Jr.': 'Milwaukee Bucks',
    'Isaiah Hartenstein': 'Oklahoma City Thunder',
    'Miles McBride': 'New York Knicks',
    'Dennis Schröder': 'Sacramento Kings',
    'Zach Edey': 'Memphis Grizzlies',
    'Vince Williams Jr.': 'Memphis Grizzlies',
    'Cam Thomas': 'Brooklyn Nets',
    'Gradey Dick': 'Toronto Raptors',
    'Draymond Green': 'Golden State Warriors',
    'Joel Embiid': 'Philadelphia 76ers',
    'Paul George': 'Philadelphia 76ers',
    'Jared McCain': 'Philadelphia 76ers',
    'Kelly Oubre Jr.': 'Philadelphia 76ers',
    'Brook Lopez': 'Los Angeles Clippers',
    'Jrue Holiday': 'Portland Trail Blazers',
    'Tobias Harris': 'Detroit Pistons',
    'Jonas Valančiūnas': 'Denver Nuggets',
    'Kentavious Caldwell-Pope': 'Memphis Grizzlies',
    'Christian Braun': 'Denver Nuggets',
    'Dalton Knecht': 'Los Angeles Lakers',
    'Cooper Flagg': 'Dallas Mavericks',
    'Ace Bailey': 'Utah Jazz',
    'Tre Johnson': 'Washington Wizards',
    'Caleb Martin': 'Dallas Mavericks',
}

# Runtime team mapping (populated during scrape)
PLAYER_TEAMS = {}


def load_known_players():
    """Load known NBA players from file. Returns set of lowercase names."""
    players = set()
    player_file = 'nba_players.txt'
    if os.path.exists(player_file):
        with open(player_file, 'r') as f:
            for line in f:
                name = line.strip()
                if name and name.upper() != 'PLAYER':
                    players.add(name.lower())
    print(f"Loaded {len(players)} known players from {player_file}")
    return players


def is_player_tag(tag_text, known_players):
    """Check if tag is a known player. Strict matching only."""
    tag_lower = tag_text.lower().strip()
    return tag_lower in known_players


def get_team_from_tags(tag_div):
    """Extract team name from rumor tags."""
    team_names = [
        'Atlanta Hawks', 'Boston Celtics', 'Brooklyn Nets', 'Charlotte Hornets',
        'Chicago Bulls', 'Cleveland Cavaliers', 'Dallas Mavericks', 'Denver Nuggets',
        'Detroit Pistons', 'Golden State Warriors', 'Houston Rockets', 'Indiana Pacers',
        'Los Angeles Clippers', 'Los Angeles Lakers', 'Memphis Grizzlies', 'Miami Heat',
        'Milwaukee Bucks', 'Minnesota Timberwolves', 'New Orleans Pelicans', 'New York Knicks',
        'Oklahoma City Thunder', 'Orlando Magic', 'Philadelphia 76ers', 'Phoenix Suns',
        'Portland Trail Blazers', 'Sacramento Kings', 'San Antonio Spurs', 'Toronto Raptors',
        'Utah Jazz', 'Washington Wizards'
    ]
    
    if tag_div:
        for tag_link in tag_div.find_all('a', class_='tag'):
            tag_text = tag_link.get_text(strip=True)
            if tag_text in team_names:
                return tag_text
    return None


def get_player_team(player_name, tag_team=None):
    """Get team for a player, prioritizing our accurate 2024-25 mapping."""
    # First check our accurate mapping
    if player_name in PLAYER_TEAMS_2025:
        return PLAYER_TEAMS_2025[player_name]
    # Then check runtime mapping from tags
    if player_name in PLAYER_TEAMS:
        return PLAYER_TEAMS[player_name]
    # Finally use the tag team if available
    return tag_team


def parse_date(date_str):
    """Parse date string from HoopsHype format."""
    date_str = date_str.replace(' Updates', '').strip()
    try:
        return date_parser.parse(date_str).date()
    except:
        return None


def get_rumor_html(rumor_text_elem):
    """Extract rumor text with hyperlinks preserved."""
    if not rumor_text_elem:
        return "", ""
    
    # Get the inner HTML
    inner_html = str(rumor_text_elem)
    
    # Clean up - remove the outer <p> tags
    inner_html = re.sub(r'^<p[^>]*>', '', inner_html)
    inner_html = re.sub(r'</p>$', '', inner_html)
    
    # Find the quote link (the hyperlinked part)
    quote_link = rumor_text_elem.find('a', class_='quote')
    quote_url = quote_link.get('href', '') if quote_link else ""
    
    # Get plain text version too
    plain_text = rumor_text_elem.get_text(strip=True)
    
    # Create clean HTML with only the essential link
    # Replace the quote link to open in new tab
    if quote_link:
        quote_text = quote_link.get_text(strip=True)
        quote_href = quote_link.get('href', '#')
        # Rebuild with target="_blank"
        inner_html = inner_html.replace(
            str(quote_link),
            f'<a href="{quote_href}" target="_blank" style="color: #1a73e8;">{quote_text}</a>'
        )
    
    # Remove rumormedia links (redundant)
    inner_html = re.sub(r'<a[^>]*class="rumormedia"[^>]*>.*?</a>', '', inner_html)
    
    # Clean up extra whitespace
    inner_html = re.sub(r'\s+', ' ', inner_html).strip()
    
    return inner_html, plain_text


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
        
        current_date = None
        
        date_holders = soup.find_all('div', class_='date-holder')
        rumor_divs = soup.find_all('div', class_='rumor')
        print(f"    Found {len(date_holders)} date holders, {len(rumor_divs)} rumors")
        
        all_elements = soup.find_all('div', class_=['date-holder', 'rumor'])
        
        for element in all_elements:
            classes = element.get('class', [])
            
            if 'date-holder' in classes:
                date_div = element.find('div', class_='date')
                if date_div:
                    current_date = parse_date(date_div.get_text())
                    if current_date:
                        oldest_date = current_date
            
            elif 'rumor' in classes:
                if current_date is None:
                    continue
                
                # Get rumor text with HTML preserved
                rumor_text_elem = element.find('p', class_='rumortext')
                rumor_html, rumor_plain = get_rumor_html(rumor_text_elem)
                
                # Find outlet
                outlet_elem = element.find('a', class_='rumormedia')
                outlet = outlet_elem.get_text(strip=True) if outlet_elem else "Unknown"
                
                # Find source URL
                source_elem = element.find('a', class_='quote') or element.find('a', class_='rumormedia')
                source_url = source_elem.get('href', '') if source_elem else ""
                
                # Find tags and team
                tag_div = element.find('div', class_='tag')
                tag_team = get_team_from_tags(tag_div)
                
                # Find player tags
                players_in_rumor = []
                if tag_div:
                    for tag_link in tag_div.find_all('a', class_='tag'):
                        tag_text = tag_link.get_text(strip=True)
                        if is_player_tag(tag_text, known_players):
                            players_in_rumor.append(tag_text)
                            # Store player-team mapping from tags (as backup)
                            if tag_team and tag_text not in PLAYER_TEAMS:
                                PLAYER_TEAMS[tag_text] = tag_team
                
                # Create rumor entry for each player
                for player in players_in_rumor:
                    # Get team using our priority system
                    player_team = get_player_team(player, tag_team)
                    rumors.append({
                        'date': current_date.isoformat(),
                        'player': player,
                        'text': rumor_plain,
                        'text_html': rumor_html,
                        'outlet': outlet,
                        'source_url': source_url,
                        'team': player_team
                    })
        
        # Check for next page
        pager = soup.find('div', class_='pagernext')
        if pager and pager.find('a'):
            has_more = True
        
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
        print("WARNING: No known players loaded!")
    
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
        
        if oldest_date and oldest_date < cutoff_date:
            print(f"Reached cutoff date ({oldest_date} < {cutoff_date})")
            break
        
        if not has_more:
            print("No more pages")
            break
        
        page += 1
    
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
        'team': None,
        'rumors': [],
        'daily_counts': defaultdict(int)
    })
    
    for rumor in rumors:
        player = rumor['player']
        rumor_date = datetime.strptime(rumor['date'], '%Y-%m-%d').date()
        days_ago = (today - rumor_date).days
        
        if days_ago <= 7:
            player_data[player]['mentions_week1'] += 1
        elif days_ago <= 14:
            player_data[player]['mentions_week2'] += 1
        else:
            player_data[player]['mentions_weeks3_4'] += 1
        
        player_data[player]['total_mentions'] += 1
        player_data[player]['daily_counts'][rumor['date']] += 1
        
        # Store team (use our mapping)
        if not player_data[player]['team']:
            player_data[player]['team'] = get_player_team(player, rumor.get('team'))
        
        if player_data[player]['first_mention'] is None or rumor['date'] < player_data[player]['first_mention']:
            player_data[player]['first_mention'] = rumor['date']
        if player_data[player]['last_mention'] is None or rumor['date'] > player_data[player]['last_mention']:
            player_data[player]['last_mention'] = rumor['date']
        
        # Store rumor (avoid duplicates)
        rumor_key = (rumor['date'], rumor['text'][:100])
        existing_keys = [(r['date'], r['text'][:100]) for r in player_data[player]['rumors']]
        if rumor_key not in existing_keys:
            player_data[player]['rumors'].append({
                'date': rumor['date'],
                'text': rumor['text'],
                'text_html': rumor.get('text_html', rumor['text']),
                'outlet': rumor['outlet'],
                'source_url': rumor['source_url']
            })
    
    # Calculate scores
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
            'last_mention': data['last_mention'],
            'team': data['team']
        })
    
    rankings.sort(key=lambda x: (-x['score'], -x['total_mentions'], x['player']))
    
    for i, r in enumerate(rankings, 1):
        r['rank'] = i
    
    return rankings, player_data


def main():
    username = os.environ.get('HH_PREVIEW_USER', 'preview')
    password = os.environ.get('HH_PREVIEW_PASS', 'hhpreview')
    
    print("=" * 60)
    print("NBA Trade Rumor Rankings Scraper")
    print("=" * 60)
    
    rumors = scrape_all_rumors(username, password)
    
    if not rumors:
        print("\nNo rumors found!")
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
    
    rankings, player_data = calculate_rankings(rumors)
    
    print(f"\nTop 10 Players:")
    for r in rankings[:10]:
        print(f"  {r['rank']}. {r['player']} ({r['team']}): {r['score']} pts ({r['total_mentions']} mentions)")
    
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
    
    with open('trade_rumor_data.json', 'w') as f:
        json.dump(output_data, f, indent=2)
    
    print(f"\nData saved to trade_rumor_data.json")
    print(f"Total players ranked: {len(rankings)}")


if __name__ == '__main__':
    main()
