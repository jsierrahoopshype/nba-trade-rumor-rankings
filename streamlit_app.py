import math
import re
from datetime import datetime, timedelta
from typing import Tuple, Optional

import pandas as pd
import streamlit as st
import altair as alt
import html

# ------------------------
# Config & constants
# ------------------------

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


def make_slug(name: str) -> str:
    """
    Turn 'LeBron James' -> 'lebron-james'
    Used for URLs and data-hh-player-slug attributes.
    """
    if not isinstance(name, str):
        return ""

    # Apply manual fixes first for consistency
    fixed = NAME_FIXES.get(name, name)

    s = fixed.strip().lower()
    # remove apostrophes
    s = s.replace("’", "").replace("'", "")
    # replace non alphanumerics with dashes
    s = re.sub(r"[^a-z0-9]+", "-", s)
    # collapse multiple dashes and trim
    s = re.sub(r"-+", "-", s).strip("-")
    return s


# ------------------------
# Utility functions
# ------------------------


@st.cache_data(show_spinner=False)
def load_rumors_csv(path: str = "trade_rumors.csv") -> pd.DataFrame:
    try:
        df = pd.read_csv(path)
    except FileNotFoundError:
        return pd.DataFrame()

    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce", utc=True)
    else:
        df["date"] = pd.NaT

    df = df.dropna(subset=["date"])

    if "player" not in df.columns:
        df["player"] = ""

    # Ensure string type
    df["player"] = df["player"].astype(str)

    return df


def compute_window_bounds(today: datetime.date) -> Tuple[datetime.date, datetime.date]:
    start = today - timedelta(days=WINDOW_DAYS - 1)
    return start, today


def compute_player_scores(df: pd.DataFrame) -> pd.DataFrame:
    """
    From raw rumor rows -> per-player scores and counts in each time bucket.
    Assumes df has a 'date' column (datetime) and 'player' column (string).
    """
    if df.empty:
        return pd.DataFrame(
            columns=[
                "player",
                "score",
                "mentions_0_7",
                "mentions_8_14",
                "mentions_15_28",
                "slug",
            ]
        )

    today = datetime.utcnow().date()
    window_start, window_end = compute_window_bounds(today)

    mask = (df["date"].dt.date >= window_start) & (df["date"].dt.date <= window_end)
    df_window = df.loc[mask].copy()

    if df_window.empty:
        return pd.DataFrame(
            columns=[
                "player",
                "score",
                "mentions_0_7",
                "mentions_8_14",
                "mentions_15_28",
                "slug",
            ]
        )

    # How many days ago each rumor was
    df_window["days_ago"] = (window_end - df_window["date"].dt.date).astype("int64")

    # Bucket flags
    df_window["in_0_7"] = df_window["days_ago"] <= (RECENT_DAYS_1 - 1)
    df_window["in_8_14"] = (df_window["days_ago"] >= RECENT_DAYS_1) & (
        df_window["days_ago"] <= (RECENT_DAYS_2 - 1)
    )
    df_window["in_15_28"] = (df_window["days_ago"] >= RECENT_DAYS_2) & (
        df_window["days_ago"] <= (WINDOW_DAYS - 1)
    )

    # Weights per rumor
    def weight_for_row(row):
        if row["in_0_7"]:
            return 1.0
        if row["in_8_14"]:
            return 0.5
        if row["in_15_28"]:
            return 0.25
        return 0.0

    df_window["weight"] = df_window.apply(weight_for_row, axis=1)

    grouped = (
        df_window.groupby("player")
        .agg(
            score=("weight", "sum"),
            mentions_0_7=("in_0_7", "sum"),
            mentions_8_14=("in_8_14", "sum"),
            mentions_15_28=("in_15_28", "sum"),
        )
        .reset_index()
    )

    # Apply display name fixes
    grouped["player"] = grouped["player"].replace(NAME_FIXES)

    # Slugs for every player – used in links & URLs
    grouped["slug"] = grouped["player"].apply(make_slug)

    # Sort by score desc, then name asc
    grouped = grouped.sort_values(
        ["score", "player"], ascending=[False, True]
    ).reset_index(drop=True)

    grouped["score"] = grouped["score"].round(2)

    return grouped


def get_player_from_query_params() -> Optional[str]:
    """
    Read ?player= from the URL, robust to old/new Streamlit APIs.
    Returns the slug (e.g. 'anthony-davis') or None.
    """
    qp = None
    try:
        qp = st.query_params  # new API in recent Streamlit
    except Exception:
        try:
            qp = st.experimental_get_query_params()
        except Exception:
            return None

    if not qp:
        return None

    value = qp.get("player")
    if value is None:
        return None

    # Could be list or str depending on API version
    if isinstance(value, list):
        return value[0] if value else None
    return value


def inject_navigation_js():
    """
    JS inside the iframe:
    - clicking a player name sets ?player=<slug> on the iframe URL
    - sends postMessage to the parent page so HoopsHype can update its own URL
    - clicking "Back to rankings" clears player in both places
    """
    js = """
    <script>
    (function() {
      function setPlayerSlug(slug) {
        if (!slug) return;

        // Update the iframe URL's query param (?player=slug)
        var url = new URL(window.location.href);
        url.searchParams.set('player', slug);
        window.history.replaceState({}, '', url.toString());

        // Tell the parent page (HoopsHype) what player was selected
        try {
          window.parent.postMessage(
            { type: 'hh-trade-rumor-player', slug: slug },
            '*'
          );
        } catch (e) {
          console.warn('postMessage to parent failed', e);
        }
      }

      function clearPlayerSlug() {
        var url = new URL(window.location.href);
        url.searchParams.delete('player');
        window.history.replaceState({}, '', url.toString());

        try {
          window.parent.postMessage(
            { type: 'hh-trade-rumor-back' },
            '*'
          );
        } catch (e) {
          console.warn('postMessage to parent failed', e);
        }
      }

      document.addEventListener('click', function(e) {
        var link = e.target.closest('a[data-hh-player-slug]');
        if (link) {
          e.preventDefault();
          var slug = link.getAttribute('data-hh-player-slug');
          setPlayerSlug(slug);
          return;
        }

        if (e.target.closest('[data-hh-back-to-rankings]')) {
          e.preventDefault();
          clearPlayerSlug();
          return;
        }
      }, true);
    })();
    </script>
    """
    st.markdown(js, unsafe_allow_html=True)


# ------------------------
# UI helpers
# ------------------------


def show_header(df: pd.DataFrame, window_start: datetime.date, window_end: datetime.date):
    st.title("NBA Trade Rumor Rankings")

    if df.empty:
        st.write("No trade rumors available.")
        return

    last_date = df["date"].max().date()
    window_str = f"{window_start.strftime('%b %d')} – {window_end.strftime('%b %d')}"
    st.caption(
        f"Based on trade rumors from the last {WINDOW_DAYS} days "
        f"({window_str}).\n\n"
        f"Data last updated: {last_date.strftime('%b %d, %Y')}"
    )

    st.markdown(
        """
        Rankings based on how often players appear in trade rumors over the last 28 days, with recent mentions weighted more heavily.

        - **1 point** per mention in the last 7 days  
        - **0.5 points** per mention 8–14 days ago  
        - **0.25 points** per mention 15–28 days ago  
        """,
        unsafe_allow_html=True,
    )


def show_rankings(df_scores: pd.DataFrame) -> None:
    st.subheader("Rankings")

    if df_scores.empty:
        st.info("No trade rumors in the last 28 days.")
        return

    headers = [
        "Rank",
        "Player",
        "Score",
        "Mentions (0–7d)",
        "Mentions (8–14d)",
        "Mentions (15–28d)",
    ]

    rows_html = []
    for idx, row in df_scores.iterrows():
        rank = idx + 1
        player_html = (
            f'<a href="#" data-hh-player-slug="{html.escape(row["slug"])}">'
            f'{html.escape(row["player"])}</a>'
        )

        rows_html.append(
            f"<tr>"
            f"<td class='hh-rank'>{rank}</td>"
            f"<td class='hh-player'>{player_html}</td>"
            f"<td class='hh-score'>{row['score']:.2f}</td>"
            f"<td>{int(row['mentions_0_7'])}</td>"
            f"<td>{int(row['mentions_8_14'])}</td>"
            f"<td>{int(row['mentions_15_28'])}</td>"
            f"</tr>"
        )

    table_html = f"""
    <style>
      .hh-table {{
        width: 100%;
        border-collapse: collapse;
        font-size: 14px;
        font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      }}
      .hh-table thead tr {{
        background: #f8f9fa;
      }}
      .hh-table th {{
        text-align: left;
        padding: 10px 14px;
        border-bottom: 1px solid #dde2e7;
        font-weight: 600;
        color: #444;
        font-size: 13px;
        text-transform: uppercase;
        letter-spacing: 0.03em;
      }}
      .hh-table td {{
        padding: 10px 14px;
        border-bottom: 1px solid #f1f3f5;
        font-size: 14px;
      }}
      .hh-table tbody tr:nth-child(even) {{
        background: #fbfbfd;
      }}
      .hh-table tbody tr:hover {{
        background: #f1f7ff;
      }}
      .hh-table .hh-rank {{
        width: 48px;
        text-align: right;
        color: #6c757d;
        font-weight: 500;
      }}
      .hh-table .hh-player a {{
        color: #0066cc;
        text-decoration: none;
        font-weight: 500;
      }}
      .hh-table .hh-player a:hover {{
        text-decoration: underline;
      }}
      .hh-table .hh-score {{
        font-weight: 600;
      }}
    </style>

    <table class="hh-table">
      <thead>
        <tr>
          {''.join(f'<th>{h}</th>' for h in headers)}
        </tr>
      </thead>
      <tbody>
        {''.join(rows_html)}
      </tbody>
    </table>
    """

    st.markdown(table_html, unsafe_allow_html=True)


def build_daily_chart(df_player: pd.DataFrame, window_start: datetime.date, window_end: datetime.date):
    if df_player.empty:
        return None

    df_player = df_player.copy()
    df_player["day"] = df_player["date"].dt.date

    all_days = pd.date_range(window_start, window_end, freq="D")
    daily = (
        df_player.groupby("day")
        .size()
        .reindex(all_days.date, fill_value=0)
        .reset_index()
    )
    daily.columns = ["day", "mentions"]

    chart = (
        alt.Chart(daily)
        .mark_area(line={"size": 2}, opacity=0.3)
        .encode(
            x=alt.X("day:T", title="Date"),
            y=alt.Y("mentions:Q", title="Mentions per day"),
            tooltip=[
                alt.Tooltip("day:T", title="Date"),
                alt.Tooltip("mentions:Q", title="Mentions"),
            ],
        )
        .properties(height=220)
    )

    return chart


def show_player_view(
    df_window: pd.DataFrame,
    player_name: str,
    window_start: datetime.date,
    window_end: datetime.date,
):
    st.markdown(
        f"### {html.escape(player_name)} – Trade Rumor Activity",
        unsafe_allow_html=True,
    )

    # Back link (same window; JS intercepts and clears player)
    st.markdown(
        '<a href="#" data-hh-back-to-rankings="1">← Back to rankings</a>',
        unsafe_allow_html=True,
    )

    df_player = df_window[df_window["player"] == player_name].copy()

    if df_player.empty:
        st.info("No trade rumors for this player in the last 28 days.")
        return

    chart = build_daily_chart(df_player, window_start, window_end)
    if chart is not None:
        st.subheader("Mentions per day")
        st.altair_chart(chart, use_container_width=True)

    st.subheader("Most recent trade rumors")

    # Rumor fields (be flexible about column names)
    outlet_col = None
    for cand in ["outlet", "source", "via"]:
        if cand in df_player.columns:
            outlet_col = cand
            break

    highlight_col = None
    for cand in ["highlight_html", "highlight", "headline_html", "headline"]:
        if cand in df_player.columns:
            highlight_col = cand
            break

    url_col = "url" if "url" in df_player.columns else None

    df_player = df_player.sort_values("date", ascending=False)

    items_html = []
    for _, row in df_player.iterrows():
        date_str = row["date"].strftime("%b %d")
        outlet = str(row[outlet_col]) if outlet_col and pd.notna(row[outlet_col]) else ""
        highlight = (
            str(row[highlight_col]) if highlight_col and pd.notna(row[highlight_col]) else ""
        )

        # If highlight text doesn't already include a link and we have a URL, wrap it
        if url_col and pd.notna(row.get(url_col)) and "href=" not in highlight:
            url = html.escape(row[url_col])
            highlight_text = html.escape(highlight)
            highlight = (
                f'<a href="{url}" target="_blank" rel="nofollow">{highlight_text}</a>'
            )

        outlet_part = f"{html.escape(outlet)}: " if outlet else ""
        item = f"<li><strong>{date_str}</strong> – {outlet_part}{highlight}</li>"
        items_html.append(item)

    st.markdown("<ul>" + "".join(items_html) + "</ul>", unsafe_allow_html=True)


# ------------------------
# Main
# ------------------------


def main():
    df = load_rumors_csv()
    if df.empty:
        st.error("trade_rumors.csv is empty or missing.")
        return

    # Use max date in data as "today" so historical snapshots still work
    today = df["date"].max().date()
    window_start, window_end = compute_window_bounds(today)

    # Filter window for player detail chart / list
    mask = (df["date"].dt.date >= window_start) & (df["date"].dt.date <= window_end)
    df_window = df.loc[mask].copy()

    df_scores = compute_player_scores(df)

    # Inject JS for navigation (player clicks + back link)
    inject_navigation_js()

    # Build slug -> player mapping
    slug_to_player = dict(zip(df_scores["slug"], df_scores["player"]))

    # Read ?player= from URL
    player_slug = get_player_from_query_params()
    player_name = slug_to_player.get(player_slug) if player_slug else None

    show_header(df, window_start, window_end)

    if player_name:
        # Individual player view
        show_player_view(df_window, player_name, window_start, window_end)
    else:
        # Rankings view + search
        search = st.text_input("Search for a player")
        df_to_show = df_scores
        if search:
            mask = df_scores["player"].str.contains(
                search, case=False, na=False
            )
            df_to_show = df_scores[mask].reset_index(drop=True)

        show_rankings(df_to_show)


if __name__ == "__main__":
    main()
