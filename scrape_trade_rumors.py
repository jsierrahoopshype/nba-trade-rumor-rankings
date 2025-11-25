import os
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from dateutil import parser as dateparser
import pandas as pd

PREVIEW_URL = "http://preview.hoopshype.com/rumors/tag/trade"


def slugify(name: str) -> str:
    return name.lower().replace(" ", "-")


def load_player_whitelist(path="nba_players.txt"):
    """
    Load NBA players (one name per line, case-insensitive).
    """
    if not os.path.exists(path):
        print(f"WARNING: {path} not found. All tags will be included.")
        return None

    players = set()
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            name = line.strip()
            if not name:
                continue
            players.add(name.lower())

    print(f"Loaded {len(players)} players from {path}")
    return players


def scrape():
    # Read preview credentials from environment (GitHub secrets will provide these)
    user = os.getenv("HH_PREVIEW_USER")
    pw = os.getenv("HH_PREVIEW_PASS")
    if not user or not pw:
        raise RuntimeError("HH_PREVIEW_USER or HH_PREVIEW_PASS not set")

    auth = (user, pw)

    # Load whitelist of players
    player_whitelist = load_player_whitelist("nba_players.txt")

    # Fetch preview page with authentication
    resp = requests.get(PREVIEW_URL, auth=auth, timeout=15)
    print("Status code:", resp.status_code)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    all_rumors = soup.select("div.rumor")
    print("Total div.rumor found:", len(all_rumors))

    rows = []

    for rumor in all_rumors:
        # Find nearest previous date-holder and parse its date
        date_holder = rumor.find_previous("div", class_="date-holder")
        if not date_holder:
            continue

        date_str = date_holder.get_text(strip=True)
        if "Updates" in date_str:
            date_str = date_str.replace("Updates", "").strip()

        try:
            date_val = dateparser.parse(date_str)
        except Exception as e:
            print("Could not parse date:", date_str, "error:", e)
            continue

        # Rumor text
        p = rumor.select_one("p.rumortext")
        text = p.get_text(" ", strip=True) if p else ""

        # Anchor URL on public site
        rumor_id = rumor.get("id", "")
        if rumor_id:
            public_url = f"https://hoopshype.com/rumors/tag/trade/#{rumor_id}"
        else:
            public_url = "https://hoopshype.com/rumors/tag/trade/"

        # Tags under this rumor
        for tag in rumor.select("div.tag a"):
            player_name = tag.get_text(strip=True)
            if not player_name:
                continue

            # If we have a whitelist, filter by it
            if player_whitelist is not None:
                if player_name.lower() not in player_whitelist:
                    continue  # coach / exec / team / generic; skip

            rows.append(
                {
                    "player": player_name,
                    "slug": slugify(player_name),
                    "date": date_val.isoformat(),
                    "title": text,
                    "url": public_url,
                }
            )

    df = pd.DataFrame(rows)
    df.to_csv("trade_rumors.csv", index=False, encoding="utf-8")
    print(f"Wrote {len(df)} rows to trade_rumors.csv")


if __name__ == "__main__":
    scrape()
