import csv
import os
import re
from datetime import datetime, date
from typing import List, Dict, Optional

import requests
from bs4 import BeautifulSoup
from requests.auth import HTTPBasicAuth

# HoopsHype preview trade-rumor tag URL
BASE_URL = "http://preview.hoopshype.com/rumors/tag/trade"
OUTPUT_CSV = "trade_rumors.csv"
MAX_PAGES = 10  # safety cap on pagination


def get_auth() -> HTTPBasicAuth:
    """
    Read preview credentials from environment variables
    (set in GitHub Secrets as HH_PREVIEW_USER / HH_PREVIEW_PASS).
    """
    user = os.getenv("HH_PREVIEW_USER")
    pwd = os.getenv("HH_PREVIEW_PASS")
    if not user or not pwd:
        raise RuntimeError("Missing HH_PREVIEW_USER or HH_PREVIEW_PASS.")
    return HTTPBasicAuth(user, pwd)


def parse_date_from_holder(text: str) -> date:
    """
    Date-holder text looks like, for example:
      'Wednesday, November 27, 2025 Updates'
      'November 27, 2025 Rumors'
    We extract the 'Month DD, YYYY' part and parse it.
    """
    text = text.strip()
    m = re.search(r"([A-Za-z]+ \d{1,2}, \d{4})", text)
    if not m:
        raise ValueError(f"Could not find date in: {text!r}")
    date_str = m.group(1)
    dt = datetime.strptime(date_str, "%B %d, %Y")
    return dt.date()


def clean_snippet_html(p_tag) -> str:
    """
    Keep HoopsHype's inline formatting (quotes, bold, etc.) but
    strip onclick/target attributes to be safe for rendering.
    """
    if p_tag is None:
        return ""
    html = str(p_tag)
    html = re.sub(r'onclick="[^"]*"', "", html)
    html = re.sub(r'target="[^"]*"', "", html)
    return html


def is_player_tag_link(a) -> bool:
    """
    Decide whether a link is a player tag.
    On HoopsHype, player profile URLs contain '/player/'.
    """
    href = a.get("href") or ""
    return "/player/" in href


def extract_player_from_tag_link(a) -> Dict[str, str]:
    """
    Given a player tag link, return player name + slug.
    Example:
      <a href="/player/anthony-davis/">Anthony Davis</a>
    -> {'player': 'Anthony Davis', 'slug': 'anthony-davis'}
    """
    name = a.get_text(strip=True)
    href = a.get("href") or ""
    slug = href.rstrip("/").split("/")[-1]
    return {"player": name, "slug": slug}


def extract_article_url(rumor_div) -> str:
    """
    Get the external/source link for the rumor.
    Prefer the 'rumormedia' link if present, otherwise first non-player link.
    """
    media_link = rumor_div.find("a", class_="rumormedia", href=True)
    if media_link:
        return media_link["href"]

    # Fallback: first link that is NOT a player profile
    for a in rumor_div.find_all("a", href=True):
        if not is_player_tag_link(a):
            return a["href"]

    # If all else fails, just use first link
    first_link = rumor_div.find("a", href=True)
    return first_link["href"] if first_link else ""


def find_date_for_rumor(rumor_div) -> Optional[date]:
    """
    Walk backwards from this rumor_div to find the nearest preceding
    div.date-holder and read the date from it.
    """
    sibling = rumor_div
    while True:
        sibling = sibling.find_previous_sibling()
        if sibling is None:
            return None
        classes = sibling.get("class", [])
        if "date-holder" in classes:
            date_text = sibling.get_text(" ", strip=True)
            try:
                return parse_date_from_holder(date_text)
            except Exception as e:  # noqa: BLE001
                print(f"Failed to parse date-holder '{date_text}': {e}")
                return None


def scrape_single_page(url: str, auth: HTTPBasicAuth) -> List[Dict]:
    """
    Scrape one page of trade rumors:
      - Find all div.rumor blocks.
      - For each, find nearest previous date-holder.
      - Within each rumor, find ALL player tag links (/player/...).
      - Emit one row per player-rumor.
    """
    print(f"Fetching {url}")
    resp = requests.get(url, auth=auth, timeout=20)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    all_rumors = soup.select("div.rumor")
    print("Total div.rumor found:", len(all_rumors))

    rows: List[Dict] = []

    for rumor in all_rumors:
        rumor_date = find_date_for_rumor(rumor)
        if rumor_date is None:
            continue

        # snippet
        # HoopsHype typically uses a <p> with some class; we fall back to "first <p>"
        p = rumor.find("p")
        snippet_html = clean_snippet_html(p)
        article_url = extract_article_url(rumor)

        # player tags: any <a> with /player/ in href anywhere in the rumor block
        player_links = [
            a for a in rumor.find_all("a", href=True) if is_player_tag_link(a)
        ]
        if not player_links:
            continue

        for a in player_links:
            pl = extract_player_from_tag_link(a)
            rows.append(
                {
                    "player": pl["player"],
                    "slug": pl["slug"],
                    "date": rumor_date.isoformat(),
                    "title": snippet_html,
                    "url": article_url,
                }
            )

    print(f"Collected {len(rows)} rows from this page.")
    return rows


def scrape():
    auth = get_auth()
    all_rows: List[Dict] = []

    for page in range(1, MAX_PAGES + 1):
        if page == 1:
            url = BASE_URL
        else:
            url = f"{BASE_URL}?page={page}"

        try:
            page_rows = scrape_single_page(url, auth)
        except Exception as e:  # noqa: BLE001
            print(f"Error fetching page {page}: {e}")
            break

        if not page_rows:
            print(f"No rows on page {page}, stopping pagination.")
            break

        all_rows.extend(page_rows)

    # Deduplicate rows
    unique: Dict[tuple, Dict] = {}
    for row in all_rows:
        key = (row["player"], row["slug"], row["date"], row["url"], row["title"])
        unique[key] = row
    rows = list(unique.values())

    # Sort by date, then player
    rows.sort(key=lambda r: (r["date"], r["player"]))

    print(f"Total unique rows to write: {len(rows)}")

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["player", "slug", "date", "title", "url"]
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} rows to {OUTPUT_CSV}")


if __name__ == "__main__":
    scrape()
