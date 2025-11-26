import csv
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Tuple

import requests
from bs4 import BeautifulSoup
from requests.auth import HTTPBasicAuth
from urllib.parse import urljoin

BASE_URL = "http://preview.hoopshype.com/rumors/tag/trade"
DAYS_BACK = 28
MAX_PAGES = 10  # safety limit so we don't crawl forever


def slugify(name: str) -> str:
    """Convert 'LaMelo Ball' -> 'lamelo-ball'."""
    name = name.strip().lower()
    name = re.sub(r"[^a-z0-9]+", "-", name)
    return name.strip("-")


def load_players(path: str = "nba_players.txt") -> List[str]:
    """Load the list of NBA player names from the text file."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"{path} not found")

    players: List[str] = []
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                players.append(line)
    return players


def fetch_page(session: requests.Session, auth: HTTPBasicAuth, page: int) -> str:
    """Download a rumors page, returning its HTML."""
    if page == 1:
        url = BASE_URL
    else:
        url = f"{BASE_URL}?page={page}"

    resp = session.get(url, auth=auth, timeout=30)
    resp.raise_for_status()
    return resp.text


def parse_page(
    html: str,
    player_set_norm: set,
    cutoff_date: datetime,
) -> Tuple[List[Dict], bool]:
    """
    Parse one page of HTML.

    Returns:
      rows: list of dicts {player, slug, date, title, url}
      reached_cutoff: True if we saw dates older than cutoff_date
    """
    soup = BeautifulSoup(html, "html.parser")
    rows: List[Dict] = []
    reached_cutoff = False

    # Each date section is wrapped in div.date-holder, followed by div.rumors
    for date_holder in soup.select("div.date-holder"):
        date_text = date_holder.get_text(" ", strip=True)
        # Example: "November 19, 2025 Updates"
        date_text = date_text.replace("Updates", "").strip()
        try:
            dt = datetime.strptime(date_text, "%B %d, %Y")
        except ValueError:
            # If we can't parse, skip this date section
            continue

        if dt < cutoff_date:
            # This date (and anything after it on later pages) is too old
            reached_cutoff = True
            continue

        rumors_block = date_holder.find_next_sibling("div", class_="rumors")
        if not rumors_block:
            continue

        for rumor_div in rumors_block.select("div.rumor"):
            # Rumor text (full paragraph)
            p = rumor_div.find("p", class_="rumortext")
            if not p:
                continue
            title = p.get_text(" ", strip=True)

            # Link to original article / tweet (quote or rumormedia)
            link_tag = rumor_div.find("a", class_="quote") or rumor_div.find(
                "a", class_="rumormedia"
            )
            if link_tag and link_tag.get("href"):
                url = urljoin(BASE_URL, link_tag["href"])
            else:
                url = BASE_URL

            # Tags: players, teams, etc.
            tag_block = rumor_div.find("div", class_="tag")
            if not tag_block:
                continue

            for a in tag_block.find_all("a"):
                tag_name = a.get_text(strip=True)
                if not tag_name:
                    continue

                # Normalize tag text for comparison with players
                norm = tag_name.strip().lower()
                if norm not in player_set_norm:
                    continue  # skip non-player tags

                player_name = tag_name
                slug = slugify(player_name)

                rows.append(
                    {
                        "player": player_name,
                        "slug": slug,
                        "date": dt.isoformat(),
                        "title": title,
                        "url": url,
                    }
                )

    return rows, reached_cutoff


def scrape() -> List[Dict]:
    """Scrape up to DAYS_BACK of trade rumors across multiple pages."""
    preview_user = os.getenv("HH_PREVIEW_USER")
    preview_pass = os.getenv("HH_PREVIEW_PASS")

    if not preview_user or not preview_pass:
        raise RuntimeError(
            "HH_PREVIEW_USER / HH_PREVIEW_PASS environment variables are required."
        )

    players = load_players()
    # Use a normalized set for comparison (lowercase)
    player_set_norm = {p.strip().lower() for p in players}

    cutoff_date = datetime.utcnow() - timedelta(days=DAYS_BACK)

    session = requests.Session()
    auth = HTTPBasicAuth(preview_user, preview_pass)

    all_rows: List[Dict] = []
    reached_cutoff_any = False

    for page in range(1, MAX_PAGES + 1):
        print(f"Fetching page {page}...")
        html = fetch_page(session, auth, page)
        page_rows, reached_cutoff = parse_page(html, player_set_norm, cutoff_date)
        print(f"  Found {len(page_rows)} player-tagged rumors on this page.")
        all_rows.extend(page_rows)

        if reached_cutoff:
            reached_cutoff_any = True
            print("  Reached cutoff date; stopping pagination.")
            break

    if not reached_cutoff_any:
        print(
            f"Warning: did not reach cutoff date after {MAX_PAGES} pages; "
            f"you may want to increase MAX_PAGES."
        )

    # Deduplicate by (player, slug, date, title, url)
    seen = set()
    deduped: List[Dict] = []
    for row in all_rows:
        key = (row["player"], row["slug"], row["date"], row["title"], row["url"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)

    print(f"Total rows after deduplication: {len(deduped)}")
    return deduped


def write_csv(rows: List[Dict], path: str = "trade_rumors.csv") -> None:
    fieldnames = ["player", "slug", "date", "title", "url"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    print(f"Wrote {len(rows)} rows to {path}")


if __name__ == "__main__":
    data = scrape()
    write_csv(data)
