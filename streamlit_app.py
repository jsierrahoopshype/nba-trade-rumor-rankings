import math
from datetime import datetime, timedelta
from typing import Tuple

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


def load_rumors(csv_path: str = "trade_rumors.csv") -> pd.DataFrame:
    df = pd.read_csv(csv_path)

    # Basic cleaning
    if "date" not in df.columns:
        raise RuntimeError("CSV is missing required 'date' column")

    # Parse dates
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"])

    # Normalize expected columns
    expected_cols = ["player", "title", "snippet", "source", "url"]
    for col in expected_cols:
        if col not in df.columns:
            df[col] = ""

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

    # Bucket the dates
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

    # Sort & rank
    scores = scores.sort_values(
        by=["Score", "Mentions (0–7d)", "Mentions (8–14d)", "Mentions (15–28d)", "player"],
        ascending=[False, False, False, False, True],
    ).reset_index(drop=True)
    scores["Rank"] = scores.index + 1

    # Make counts ints
    for col in ["Mentions (0–7d)", "Mentions (8–14d)", "Mentions (15–28d)"]:
        scores[col] = scores[col].astype(int)

    return scores, (window_start, window_end)


def render_html_table(df: pd.DataFrame) -> str:
    """Render a styled HTML table from DataFrame, with Player column already containing HTML."""
    headers = df.columns.tolist()
    rows_html = []
    for _, row in df.iterrows():
        cells = []
        for col in headers:
            val = row[col]
            if col == "Player":
                cells.append(f"<td>{val}</td>")
            else:
                cells.append(f"<td>{html.escape(str(val))}</td>")
        rows_html.append("<tr>" + "".join(cells) + "</tr>")

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
""".replace("{header_cells}", "".join(f"<th>{html.escape(h)}</th>" for h in headers)).replace(
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

    # Build table with standard links (same tab via target="_self")
    display_df = df_scores.copy()

    def player_link(row: pd.Series) -> str:
        slug = html.escape(row["slug"])
        name = html.escape(row["player"])
        return f'<a href="?player={slug}" target="_self">{name}</a>'

    display_df["Player"] = display_df.apply(player_link, axis=1)

    display_df = display_df[
        ["Rank", "Player", "Score", "Mentions (0–7d)", "Mentions (8–14d)", "Mentions (15–28d)"]
    ]

    html_table = render_html_table(display_df)
    st.markdown(html_table, unsafe_allow_html=True)


def show_player_view(
    df_window: pd.DataFrame,
    df_all: pd.DataFrame,
    player_name: str,
    window_start: pd.Timestamp,
    window_end: pd.Timestamp,
) -> None:
    st.markdown(TABLE_CSS, unsafe_allow_html=True)

    player_clean = NAME_FIXES.get(player_name, player_name)

    # Back button at top – uses Streamlit, so it won't open a new tab
    if st.button("← Back to rankings", key="back_top"):
        st.query_params.clear()
        st.rerun()

    st.title(f"{player_clean} – Trade Rumor Activity")

    # Filter rumors for this player within window
    df_player_window = df_window[df_window["player"] == player_name].copy()

    # Time series chart (last 28 days)
    st.subheader("Mentions per day")

    if not df_player_window.empty:
        days = pd.date_range(window_start, window_end, freq="D")
        daily = (
            df_player_window.groupby(df_player_window["date"].dt.normalize())
            .size()
            .reindex(days, fill_value=0)
            .reset_index()
        )
        daily.columns = ["day", "mentions"]

        base = (
            alt.Chart(daily)
            .encode(
                x=alt.X(
                    "day:T",
                    axis=alt.Axis(format="%b %-d", labelAngle=-45, title=None),
                ),
                y=alt.Y(
                    "mentions:Q",
                    title="Mentions per day",
                    axis=alt.Axis(grid=True),
                ),
                tooltip=[
                    alt.Tooltip("day:T", title="Date", format="%Y-%m-%d"),
                    alt.Tooltip("mentions:Q", title="Mentions"),
                ],
            )
        )

        area = base.mark_area(
            line={"color": "#0f766e", "strokeWidth": 2},
            color=alt.Gradient(
                gradient="linear",
                stops=[
                    alt.GradientStop(color="#0f766e", offset=0),
                    alt.GradientStop(color="#ecfdf3", offset=1),
                ],
                x1=0,
                x2=0,
                y1=0,
                y2=1,
            ),
        )

        points = base.mark_circle(size=55, color="#0f766e")

        chart = (area + points).properties(height=260)
        st.altair_chart(chart, use_container_width=True)
    else:
        st.write("No mentions for this player in the last 28 days.")

    # Most recent rumors (window-limited)
    st.subheader("Most recent trade rumors")

    df_player_recent = df_player_window.sort_values("date", ascending=False)
    if df_player_recent.empty:
        st.write("No trade rumors found for this player in the last 28 days.")
    else:
        items = []
        for _, row in df_player_recent.iterrows():
            items.append(f"<li>{build_snippet_html(row)}</li>")

        html_list = '<ul class="rumor-list">\n' + "\n".join(items) + "\n</ul>"
        st.markdown(html_list, unsafe_allow_html=True)

    # Back button at bottom
    if st.button("← Back to rankings", key="back_bottom"):
        st.query_params.clear()
        st.rerun()


# -----------------------
# Main app
# -----------------------

def main() -> None:
    st.title("NBA Trade Rumor Rankings")
    st.write(
        f"Based on **trade rumors** from the last {WINDOW_DAYS} days, with more recent mentions weighted more heavily."
    )

    df_all = load_rumors()
    df_scores, (window_start, window_end) = compute_player_scores(df_all)

    last_date = df_all["date"].max() if not df_all.empty else None
    last_date_str = last_date.strftime("%b %-d, %Y") if last_date is not None else "N/A"

    st.caption(
        f"Data last updated: {last_date_str}"
        f"  •  Window: {window_start.strftime('%b %-d')} – {window_end.strftime('%b %-d')}"
    )

    # Determine if we're on a player page
    params = st.query_params
    player_param = params.get("player")
    if isinstance(player_param, list):
        player_param = player_param[0]
    player_slug = player_param

    if player_slug:
        row = df_scores[df_scores["slug"] == player_slug]
        if not row.empty:
            player_name = row["player"].iloc[0]
            df_window = df_all[
                (df_all["date"] >= window_start) & (df_all["date"] <= window_end)
            ].copy()
            show_player_view(df_window, df_all, player_name, window_start, window_end)
            return

    show_rankings(df_scores)


if __name__ == "__main__":
    main()
