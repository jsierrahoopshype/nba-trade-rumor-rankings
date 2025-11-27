import csv
import os
from datetime import datetime, timedelta
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "http://preview.hoopshype.com/rumors/tag/trade"
AUTH_USER = os.environ.get("HH_PREVIEW_USER")
AUTH_PASS = os.environ.get("HH_PREVIEW_PASS")

WINDOW_DAYS = 28
MAX_PAGES = 200  # just a safety cap


def load_players(path="nba_players.txt"):
    players = set()
    if not os.path.exists(path):
        print(f"Warning: {path} not found, player filtering will be very loose.")
        return players

    with open(path, encoding="utf-8") as f:
        for line in f:
            name = line.strip()
            if name:
                players.add(name.lower())
    print(f"Loaded {len(players)} players from {path}")
    return players


def is_player_name(text: str, player_set) -> bool:
    if not player_set:
        # If we don't have a list, allow everything
        return True
    return text.lower() in player_set


def parse_date_text(date_text: str) -> datetime:
    """
    Examples of date headers:
    - "November 19, 2025 Updates"
    We'll parse the "Month DD, YYYY" part.
    """
    # Take the first 3 tokens, e.g. "November 19, 2025"
    parts = date_text.strip().split()
    date_str = " ".join(parts[:3])
    return datetime.strptime(date_str, "%B %d, %Y")


def scrape():
    session = requests.Session()
    session.auth = (AUTH_USER, AUTH_PASS)

    players = load_players()
    today = datetime.utcnow()

    rows = []
    total_rumors = 0

    url = BASE_URL
    pages = 0

    while url and pages < MAX_PAGES:
        pages += 1
        print(f"Fetching page: {url}")
        resp = session.get(url)
        print("Status code:", resp.status_code)
        if resp.status_code != 200:
            break

        soup = BeautifulSoup(resp.text, "html.parser")

        content_div = soup.find("div", id="content")
        if not content_div:
            break

        date_holders = content_div.select("div.date-holder")
        print(f"Found {len(date_holders)} date-holder blocks")

        stop_due_to_age = False

        for holder in date_holders:
            date_text = holder.get_text(strip=True)
            try:
                rumor_date = parse_date_text(date_text)
            except Exception as e:
                print("Could not parse date:", date_text, "error:", e)
                continue

            days_ago = (today - rumor_date).days
            if days_ago > WINDOW_DAYS:
                stop_due_to_age = True
                continue

            rumors_container = holder.find_next_sibling("div", class_="rumors")
            if not rumors_container:
                continue

            rumor_divs = rumors_container.select("div.rumor")
            print(f"Date {date_text}: {len(rumor_divs)} rumor blocks")

            for rumor_div in rumor_divs:
                total_rumors += 1

                # Main text block
                p = rumor_div.find("p", class_="rumortext")
                if not p:
                    continue

                # IMPORTANT: keep HTML, including <strong> for highlighted part
                title_html = p.decode_contents().replace("\n", " ").strip()

                # Link to external article (quote or media)
                link = rumor_div.find("a", class_="rumormedia")
                if not link:
                    link = rumor_div.find("a", class_="quote")

                if link and link.has_attr("href"):
                    href = link["href"]
                    url_full = href if href.startswith("http") else urljoin(BASE_URL, href)
                else:
                    url_full = BASE_URL

                # Tag links (teams, players, etc.)
                tag_div = rumor_div.find("div", class_="tag")
                if not tag_div:
                    continue

                tag_links = tag_div.find_all("a")
                for tag in tag_links:
                    tag_text = tag.get_text(strip=True)
                    href = tag.get("href", "")

                    # We only want *players* in our rankings
                    if not is_player_name(tag_text, players):
                        continue

                    slug = href.rstrip("/").split("/")[-1] if href else tag_text.lower().replace(" ", "-")

                    rows.append(
                        [
                            tag_text,                        # player
                            slug,                            # slug
                            rumor_date.strftime("%Y-%m-%d"), # date
                            title_html,                      # title (HTML with <strong>)
                            url_full,                        # article URL
                        ]
                    )

        if stop_due_to_age:
            print("Reached rumors older than window; stopping pagination.")
            break

        # Next page link (if any)
        next_div = content_div.find("div", class_="swipe_next")
        next_link = next_div.find("a") if next_div else None
        if next_link and next_link.has_attr("href"):
            href = next_link["href"]
            url = href if href.startswith("http") else urljoin(BASE_URL, href)
        else:
            url = None

    print(f"Total div.rumor blocks processed: {total_rumors}")
    print(f"Total player-tag rows collected: {len(rows)}")

    # Write CSV
    out_path = "trade_rumors.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["player", "slug", "date", "title", "url"])
        writer.writerows(rows)

    print(f"Wrote {len(rows)} rows to {out_path}")


if __name__ == "__main__":
    scrape()
