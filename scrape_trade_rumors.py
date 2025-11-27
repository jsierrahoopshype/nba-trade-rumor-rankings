import csv
import os
import re
from datetime import datetime, timedelta, date
from typing import List, Dict, Tuple

import requests
from bs4 import BeautifulSoup
from requests.auth import HTTPBasicAuth

BASE_URL = "http://preview.hoopshype.com/rumors/tag/trade"
OUTPUT_CSV = "trade_rumors.csv"

# How many days back we care about
WINDOW_DAYS = 28


def get_auth():
    """
    Preview username/password from env.
    These should be set in your GitHub Action as environment vars.
    """
    user = os.getenv("HH_PREVIEW_USER")
    pwd = os.getenv("HH_PREVIEW_PASS")
    if not user or not pwd:
        raise RuntimeError(
            "Missing HH_PREVIEW_USER or HH_PREVIEW_PASS env vars."
        )
    return HTTPBasicAuth(user, pwd)


def parse_date_from_holder(text: str) -> date:
    """
    Example holder text:
      'November 19, 2025 Updates'
    We strip 'Updates' and parse.
    """
    text = text.strip()
    text = text.replace("Updates", "").strip()
    # 'November 19, 2025'
    dt = datetime.strptime(text, "%B %d, %Y")
    return dt.date()


def is_player_tag_link(a) -> bool:
    """
    On HoopsHype, player tags use URLs that contain '/player/'.
    Team / topic tags are ignored.
    """
    href = a.get("href") or ""
    return "/player/" in href


def extract_player_from_tag_link(a) -> Dict[str, str]:
    """
    Given a player tag link, return {'player': 'Anthony Davis', 'slug': 'anthony-davis'}.
    """
    name = a.get_text(strip=True)
    href = a.get("href") or ""
    # href like '/player/anthony-davis/' or '/player/anthony-davis'
    slug = href.rstrip("/").split("/")[-1]
    return {"player": name, "slug": slug}


def clean_snippet_html(p_tag) -> str:
    """
    We keep HoopsHype's bold/quote markup but remove
    onclick/target so we can reuse safely in Streamlit.
    """
    html = str(p_tag)
    html = re.sub(r'onclick="[^"]*"', "", html)
    html = re.sub(r'target="[^"]*"', "", html)
    return html


def extract_article_url(rumor_div) -> str:
    """
    Rumor blocks have a 'media' link (e.g., x.com, YouTube, ESPN).
    We grab its href if present.
    """
    media_link = rumor_div.find("a", class_="rumormedia")
    if media_link and media_link.get("href"):
        return media_link["href"]
    # Fallback: first link inside the snippet
    first_link = rumor_div.find("a", href=True)
    return first_link["href"] if first_link else ""


def scrape_page(page: int, auth, cutoff_date: date) -> Tuple[List[Dict], bool]:
    """
    Scrape a single page.
    Returns (rows, should_stop) where should_stop == True
    means 'this page was entirely older than cutoff_date, so stop pagination'.
    """
    if page == 1:
        url = BASE_URL
    else:
        url = f"{BASE_URL}?page={page}"

    print(f"Fetching {url}")
    resp = requests.get(url, auth=auth, timeout=20)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    # All date-holders on the page
    date_holders = soup.select("div.date-holder")
    if not date_holders:
        print("No date-holders found on this page.")
        return [], True  # likely no more content

    # All rumor blocks
    rumor_divs = soup.select("div.rumor")
    if not rumor_divs:
        print("No div.rumor blocks found on this page.")
        return [], False  # maybe structure changed, but don't stop pagination yet

    rows: List[Dict] = []
    saw_recent = False  # track if we saw anything >= cutoff_date

    for r in rumor_divs:
        # Find the closest previous date-holder in the DOM
        dh = r.find_previous("div", class_="date-holder")
        if dh is None:
            continue

        date_text = dh.get_text(strip=True)
        try:
            rumor_date = parse_date_from_holder(date_text)
        except Exception as e:  # noqa: BLE001
            print(f"Could not parse date from '{date_text}': {e}")
            continue

        if rumor_date < cutoff_date:
            # Older than our window. Skip this rumor, but we don't
            # immediately stop the page; we check all rumors first.
            continue
        else:
            saw_recent = True

        # Rumor snippet
        p = r.find("p", class_="rumortext")
        if not p:
            continue

        snippet_html = clean_snippet_html(p)
        article_url = extract_article_url(r)

        # Tags container
        tag_div = r.find("div", class_="tag")
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
                    "date": rumor_date.isoformat(),
                    "title": snippet_html,
                    "url": article_url,
                }
            )

    # If the whole page had only old rumors (< cutoff_date), we can stop.
    should_stop = not saw_recent
    return rows, should_stop


def scrape():
    auth = get_auth()
    today = date.today()
    cutoff_date = today - timedelta(days=WINDOW_DAYS)

    all_rows: List[Dict] = []
    page = 1

    while True:
        rows, stop = scrape_page(page, auth, cutoff_date)
        all_rows.extend(rows)
        print(f"Page {page}: collected {len(rows)} rows.")
        if stop:
            print("This page had no recent rumors; stopping pagination.")
            break
        page += 1
        if page > 40:
            # Hard safety stop so we don't go wild if pagination changes
            print("Hit page limit (40), stopping.")
            break

    # Deduplicate: same player/date/title/url may appear if site glitches
    unique = {}
    for row in all_rows:
        key = (row["player"], row["slug"], row["date"], row["url"], row["title"])
        unique[key] = row
    rows = list(unique.values())

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
