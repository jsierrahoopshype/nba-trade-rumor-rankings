import math
from datetime import datetime, timedelta
from typing import Tuple, Optional

import pandas as pd
import streamlit as st
import altair as alt
import html


# -----------------------
# Config & constants
# -----------------------

st.set_page_config(
    page_title="NBA Trade Rumor Rankings",
    page_icon="📈",
    layout="wide",
)

WINDOW_DAYS = 28
RECENT_DAYS_1 = 7
RECENT_DAYS_2 = 14

# Manual name corrections for display
NAME_FIXES = {
    "Lebron James": "LeBron James",
    "Karl-anthony Towns": "Karl-Anthony Towns",
    "Lamelo Ball": "LaMelo Ball",
    "Demar Derozan": "DeMar DeRozan",
}

# Map fragments of team names to 3-letter ESPN codes
TEAM_KEYWORDS = {
    # East
    "hawks": "atl",
    "celtics": "bos",
    "nets": "bkn",
    "hornets": "cha",
    "bulls": "chi",
    "cavaliers": "cle",
    "cavs": "cle",
    "pistons": "det",
    "pacers": "ind",
    "heat": "mia",
    "bucks": "mil",
    "knicks": "nyk",
    "magic": "orl",
    "76ers": "phi",
    "sixers": "phi",
    "raptors": "tor",
    "wizards": "was",
    # West
    "mavericks": "dal",
    "mavs": "dal",
    "nuggets": "den",
    "warriors": "gsw",
    "rockets": "hou",
    "clippers": "lac",
    "lakers": "lal",
    "grizzlies": "mem",
    "timberwolves": "min",
    "wolves": "min",
    "pelicans": "nop",
    "thunder": "okc",
    "suns": "phx",
    "trail blazers": "por",
    "blazers": "por",
    "kings": "sac",
    "spurs": "sas",
    "jazz": "uta",
}

# Direct mapping if CSV already has abbreviations like "LAL"
TEAM_ABBREV_DIRECT = {
    "atl": "atl",
    "bos": "bos",
    "bkn": "bkn",
    "cha": "cha",
    "chi": "chi",
    "cle": "cle",
    "dal": "dal",
    "den": "den",
    "det": "det",
    "gsw": "gsw",
    "hou": "hou",
    "ind": "ind",
    "lac": "lac",
    "lal": "lal",
    "mem": "mem",
    "mia": "mia",
    "mil": "mil",
    "min": "min",
    "nop": "nop",
    "nyk": "nyk",
    "okc": "okc",
    "orl": "orl",
    "phi": "phi",
    "phx": "phx",
    "por": "por",
    "sac": "sac",
    "sas": "sas",
    "tor": "tor",
    "uta": "uta",
    "was": "was",
}


# -----------------------
# Utility functions
# -----------------------

def slugify(name: str) -> str:
    """Create a URL-friendly slug from a player name."""
    if not isinstance(name, str):
        return ""
    s = name.strip().lower()
    out = []
    for ch in s:
        if ch.isalnum():
            out.append(ch)
        elif ch in (" ", "-", "_"):
            out.append("-")
    slug = "".join(out)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-")


def get_team_code(team_name: str) -> Optional[str]:
    """Best-effort mapping from free-form team string to 3-letter ESPN code."""
    if not isinstance(team_name, str):
        return None
    s = team_name.strip().lower()
    if not s:
        return None

    # Already an abbreviation?
    if s in TEAM_ABBREV_DIRECT:
        return TEAM_ABBREV_DIRECT[s]

    # Match on keywords
    for key, code in TEAM_KEYWORDS.items():
        if key in s:
            return code

    return None


def get_team_logo_url(team_name: str) -> str:
    """Return a logo URL for the given team, or empty string if unknown."""
    code = get_team_code(team_name)
    if not code:
        return ""
    # ESPN scoreboard-style logo (500px; will be displayed small via CSS)
    return f"https://a.espncdn.com/i/teamlogos/nba/500/scoreboard/{code}.png"


def load_rumors(csv_path: str = "trade_rumors.csv") -> pd.DataFrame:
    df = pd.read_csv(csv_path)

    if "date" not in df.columns:
        raise RuntimeError("CSV is missing required 'date' column")

    # Parse dates
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"])

    # Ensure expected columns exist
    expected_cols = ["player", "title", "snippet", "source", "url"]
    for col in expected_cols:
        if col not in df.columns:
            df[col] = ""

    # Team column is optional but helpful for logos
    if "team" not in df.columns:
        df["team"] = ""
    else:
        df["team"] = df["team"].fillna("")

    # Fix player names and drop non-real players
    df["player"] = df["player"].fillna("")
    df["player"] = df["player"].replace(NAME_FIXES)
    df = df[df["player"].str.strip().ne("")]
    df = df[df["player"] != "Player"]

    # Slug column
    if "slug" not in df.columns:
        df["slug"] = df["player"].map(slugify)
    else:
        df["slug"] = df["slug"].fillna(df["player"].map(slugify))
        df.loc[df["slug"].eq(""), "slug"] = df.loc[df["slug"].eq(""), "player"].map(slugify)

    # Deduplicate
    df = df.drop_duplicates(
        subset=["date", "player", "snippet", "source", "url"],
        keep="first",
    )

    # Sort by date descending
    df = df.sort_values("date", ascending=False).reset_index(drop=True)
    return df


def compute_player_scores(df: pd.DataFrame) -> Tuple[pd.DataFrame, Tuple[pd.Timestamp, pd.Timestamp]]:
    """Compute 28-day window scores and per-bucket counts for each player."""
    if df.empty:
        return pd.DataFrame(), (pd.Timestamp.today(), pd.Timestamp.today())

    max_date = df["date"].max().normalize()
    window_end = max_date
    window_start = window_end - pd.Timedelta(days=WINDOW_DAYS - 1)

    df_window = df[(df["date"] >= window_start) & (df["date"] <= window_end)].copy()
    if df_window.empty:
        return pd.DataFrame(), (window_start, window_end)

    df_window["days_ago"] = (window_end - df_window["date"]).dt.days

    def bucket_score(days_ago: int) -> float:
        if 0 <= days_ago <= RECENT_DAYS_1 - 1:
            return 1.0
        elif RECENT_DAYS_1 <= days_ago <= RECENT_DAYS_2 - 1:
            return 0.5
        elif RECENT_DAYS_2 <= days_ago <= WINDOW_DAYS - 1:
            return 0.25
        else:
            return 0.0

    df_window["score"] = df_window["days_ago"].map(bucket_score)

    # Mentions per bucket
    def in_bucket(low: int, high: int) -> pd.Series:
        return df_window["days_ago"].between(low, high)

    bucket_0_7 = df_window[in_bucket(0, RECENT_DAYS_1 - 1)].groupby("player").size()
    bucket_8_14 = df_window[in_bucket(RECENT_DAYS_1, RECENT_DAYS_2 - 1)].groupby("player").size()
    bucket_15_28 = df_window[in_bucket(RECENT_DAYS_2, WINDOW_DAYS - 1)].groupby("player").size()

    scores = df_window.groupby("player")["score"].sum().to_frame("Score")

    scores["Mentions (0–7d)"] = bucket_0_7
    scores["Mentions (8–14d)"] = bucket_8_14
    scores["Mentions (15–28d)"] = bucket_15_28

    scores = scores.fillna(0).reset_index()

    # Attach slug
    slug_map = df_window.groupby("player")["slug"].first()
    scores["slug"] = scores["player"].map(slug_map)

    # Attach team (most frequent non-empty team for that player in window)
    team_series = (
        df_window[df_window["team"].str.strip().ne("")]
        .groupby("player")["team"]
        .agg(lambda s: s.value_counts().index[0])
    )
    scores["team"] = scores["player"].map(team_series).fillna("")

    # Sort & rank
    scores = scores.sort_values(
        by=["Score", "Mentions (0–7d)", "Mentions (8–14d)", "Mentions (15–28d)", "player"],
        ascending=[False, False, False, False, True],
    ).reset_index(drop=True)
    scores["Rank"] = scores.index + 1

    for col in ["Mentions (0–7d)", "Mentions (8–14d)", "Mentions (15–28d)"]:
        scores[col] = scores[col].astype(int)

    return scores, (window_start, window_end)


def render_html_table(df: pd.DataFrame) -> str:
    """
    Render a styled HTML table from DataFrame.

    Assumes the "Player" column already contains HTML, and gives that column
    a special class so we can align logo + name.
    """
    headers = df.columns.tolist()
    rows_html = []

    for _, row in df.iterrows():
        cells = []
        for col in headers:
            val = row[col]
            if col == "Player":
                cells.append(f'<td class="player-col">{val}</td>')
            else:
                cells.append(f"<td>{html.escape(str(val))}</td>")
        rows_html.append("<tr>" + "".join(cells) + "</tr>")

    header_cells = []
    for h in headers:
        if h == "Player":
            header_cells.append('<th class="player-col">Player</th>')
        else:
            header_cells.append(f"<th>{html.escape(h)}</th>")

    table_html = """
<div class="heat-table-wrapper">
<table class="heat-table">
  <thead>
    <tr>{header_cells}</tr>
  </thead>
  <tbody>
    {rows}
  </tbody>
</table>
</div>
""".replace("{header_cells}", "".join(header_cells)).replace(
        "{rows}", "\n".join(rows_html)
    )

    return table_html


def build_snippet_html(row: pd.Series) -> str:
    """Build rumor bullet HTML: date – snippet with highlighted part linked + outlet link."""
    date_str = row["date"].strftime("%Y-%m-%d")
    snippet = row.get("snippet", "") or ""
    title = row.get("title", "") or ""
    source = row.get("source", "") or ""
    url = row.get("url", "") or ""

    safe_snippet = html.escape(snippet)
    safe_title = html.escape(title)

    # Link only the highlighted part (title) inside the snippet if possible
    if safe_title and safe_title in safe_snippet and url:
        linked = safe_snippet.replace(
            safe_title,
            f'<a class="quote" href="{html.escape(url)}" rel="nofollow">{safe_title}</a>',
            1,
        )
    else:
        linked = safe_snippet

    # Media outlet link at the very end
    if source and url:
        outlet = f' <a class="outlet" href="{html.escape(url)}" rel="nofollow">{html.escape(source)}</a>'
    elif source:
        outlet = " " + html.escape(source)
    else:
        outlet = ""

    return f"<strong>{html.escape(date_str)}</strong> – {linked}{outlet}"


# -----------------------
# UI pieces
# -----------------------

TABLE_CSS = """
<style>
.heat-table-wrapper {
  margin-top: 0.75rem;
  border-radius: 10px;
  overflow: hidden;
  border: 1px solid #e2e8f0;
  box-shadow: 0 1px 3px rgba(15,23,42,0.08);
}

.heat-table {
  width: 100%;
  border-collapse: collapse;
  font-family: system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
  background-color: #ffffff;
}

.heat-table th,
.heat-table td {
  padding: 0.55rem 0.9rem;
  font-size: 0.9rem;
}

.heat-table th {
  background: #f8fafc;
  color: #475569;
  font-weight: 600;
  border-bottom: 1px solid #e2e8f0;
  text-align: left;
}

.heat-table td {
  color: #0f172a;
  border-bottom: 1px solid #e2e8f0;
}

.heat-table tr:last-child td {
  border-bottom: none;
}

.heat-table tr:nth-child(even) {
  background-color: #fdfdfd;
}

.heat-table tr:hover {
  background-color: #f1f5f9;
}

.heat-table td:first-child {
  width: 32px;
  color: #64748b;
  font-weight: 500;
}

/* Player cell: logo + name inline */
.heat-table .player-col {
  min-width: 200px;
}

.player-cell {
  display: flex;
  align-items: center;
  gap: 0.4rem;
}

.player-cell .team-logo {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  object-fit: contain;
  background: #f8fafc;
}

.player-cell .player-name {
  white-space: nowrap;
}

.heat-table a {
  color: #0369a1;
  font-weight: 500;
  text-decoration: none;
}

.heat-table a:hover {
  text-decoration: underline;
}

/* Rumor list styling */
.rumor-list {
  list-style-type: disc;
  padding-left: 1.2rem;
}

.rumor-list li {
  margin-bottom: 0.6rem;
  line-height: 1.35;
}

.rumor-list .quote {
  font-weight: 600;
}

.rumor-list .outlet {
  font-weight: 600;
  margin-left: 0.15rem;
}
</style>
"""


def show_rankings(df_scores: pd.DataFrame) -> None:
    st.markdown(TABLE_CSS, unsafe_allow_html=True)

    st.subheader("Top trade-rumor targets (last 28 days)")

    if df_scores.empty:
        st.info("No trade rumors found in the last 28 days.")
        return

    # Player search
    all_players = df_scores["player"].tolist()
    search = st.text_input("Jump to a player page (type a name):")
    if search:
        matches = [p for p in all_players if search.lower() in p.lower()]
        if matches:
            chosen = matches[0]
            slug = df_scores.loc[df_scores["player"] == chosen, "slug"].iloc[0]
            st.query_params.update(player=slug)
            st.rerun()

    # Build table values
    display_df = df_scores.copy()

    def player_cell(row: pd.Series) -> str:
        name = html.escape(row["player"])
        slug = html.escape(row["slug"])
        team = row.get("team", "")
        logo_html = ""
        if isinstance(team, str) and team.strip():
            logo_url = get_team_logo_url(team)
            if logo_url:
                logo_html = (
                    f'<img src="{html.escape(logo_url)}" '
                    f'class="team-logo" alt="{html.escape(team)}" />'
                )
        return (
            f'<div class="player-cell">'
            f'{logo_html}'
            f'<a href="?player={slug}"
