import csv
import os
import re
from datetime import datetime, date
from typing import List, Dict

import requests
from bs4 import BeautifulSoup
from requests.auth import HTTPBasicAuth

BASE_URL = "http://preview.hoopshype.com/rumors/tag/trade"
OUTPUT_CSV = "trade_rumors.csv"
MAX_PAGES = 10  # safety limit; we can adjust later if needed


def get_auth() -> HTTPBasicAuth:
    """
    Get preview credentials from environment variables.
    These are set as secrets in the GitHub Action:
    HH_PREVIEW_USER / HH_PREVIEW_PASS
    """
    user = os.getenv("HH_PREVIEW_USER")
    pwd = os.getenv("HH_PREVIEW_PASS")
    if not user or not pwd:
        raise RuntimeError("Missing HH_PREVIEW_USER or HH_PREVIEW_PASS.")
    return HTTPBasicAuth(user, pwd)


def parse_date_from_holder(text: str) -> date:
    """
    Date-holder text can look like:
        'Wednesday, November 19, 2025 Updates'
        'November 19, 2025 Rumors'
    We extract 'Month DD, YYYY' and parse it.
    """
    text = text.strip()
    m = re.search(r"([A-Za-z]+ \d{1,2}, \d{4})", text)
    if not m:
        raise ValueError(f"Could not find date in: {text!r}")
    date_str = m.group(1)
    dt = datetime.strptime(date_str, "%B %d, %Y")
    return dt.date()


def is_player_tag_link(a) -> bool:
    """
    Player tags on HoopsHype use URLs that contain '/player/'.
    """
    href = a.get("href") or ""
    return "/player/" in href


def extract_player_from_tag_link(a) -> Dict[str, str]:
    """
    Given a player tag link, return player name and slug.
    Example:
      <a href="/player/anthony-davis/">Anthony Davis</a>
    -> {'player': 'Anthony Davis', 'slug': 'anthony-davis'}
    """
    name = a.get_text(strip=True)
    href = a.get("href") or ""
    slug = href.rstrip("/").split("/")[-1]
    return {"player": name, "slug": slug}


def clean_snippet_html(p_tag) -> str:
    """
    Keep HoopsHype snippet HTML (bold/quotes) but remove onclick/target.
    This is what we’ll render in the Streamlit app.
    """
    html = str(p_tag)
    html = re.sub(r'onclick="[^"]*"', "", html)
    html = re.sub(r'target="[^"]*"', "", html)
    return html


def extract_article_url(rumor_div) -> str:
    """
    Rumor blocks usually have a 'media' link (x.com, YouTube, ESPN, etc.).
    Grab that href, or first link inside the snippet as fallback.
    """
    media_link = rumor_div.find("a", class_="rumormedia")
    if media_link and media_link.get("href"):
        return media_link["href"]
    first_link = rumor_div.find("a", href=True)
    return first_link["href"] if first_link else ""


def scrape_single_page(url: str, auth: HTTPBasicAuth) -> List[Dict]:
    """
    Scrape a single page of trade rumors.
    We do NOT filter by date here; we just extract all player-tagged rumors.
    The app will handle 28-day windows.
    """
    print(f"Fetching {url}")
    resp = requests.get(url, auth=auth, timeout=20)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    # Combined sequence of date headers + rumor blocks, in order
    blocks = soup.select("div.date-holder, div.rumor")
    print(f"Found {len(blocks)} date-holder/rumor blocks on this page.")

    rows: List[Dict] = []
    current_date: date | None = None

    for block in blocks:
        classes = block.get("class", [])
        if "date-holder" in classes:
            # New date section
            date_text = block.get_text(" ", strip=True)
            try:
                current_date = parse_date_from_holder(date_text)
                print(f"Current date section set to: {current_date}")
            except Exception as e:  # noqa: BLE001
                print(f"Could not parse date from '{date_text}': {e}")
                current_date = None
        elif "rumor" in classes:
            # Rumor item; needs a current_date from the last date-holder
            if current_date is None:
                continue

            # Text snippet
            p = block.find("p", class_="rumortext")
            if not p:
                continue
            snippet_html = clean_snippet_html(p)
            article_url = extract_article_url(block)

            # Tags container
            tag_div = block.find("div", class_="tag")
            if not tag_div:
                continue

            player_links = [
                a for a in tag_div.find_all("a", href=True) if is_player_tag_link(a)
            ]
            if not player_links:
                continue

            for a in player_links:
                pl = extract_player_from_tag_link(a)
                rows.append(
                    {
                        "player": pl["player"],
                        "slug": pl["slug"],
                        "date": current_date.isoformat(),
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
            # If a whole page yields nothing, we assume pagination ended
            print(f"No rows on page {page}, stopping pagination.")
            break

        all_rows.extend(page_rows)

    # Deduplicate
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
