import streamlit as st
import pandas as pd
import altair as alt
from datetime import timedelta
from urllib.parse import quote

# ---------- Page config ----------
st.set_page_config(
    page_title="NBA Trade Rumor Rankings",
    layout="wide",
)

WINDOW_DAYS = 28

# Optional: mapping hooks for logos (safe no-op by default)
# Fill these if/when you have team + logo information.
PLAYER_TO_TEAM = {
    # "LeBron James": "LAL",
    # "Nikola Jokic": "DEN",
}

TEAM_TO_LOGO_URL = {
    # "LAL": "https://your-cdn.com/logos/lal.png",
    # "DEN": "https://your-cdn.com/logos/den.png",
}


# ---------- Helpers ----------

def _normalize_player_name(name: str) -> str:
    """Fix known capitalization issues etc."""
    if not isinstance(name, str):
        return ""
    name = name.strip()
    fixups = {
        "Lebron James": "LeBron James",
        "Karl-anthony Towns": "Karl-Anthony Towns",
    }
    return fixups.get(name, name)


@st.cache_data(show_spinner=False)
def load_rumors() -> pd.DataFrame:
    df = pd.read_csv("trade_rumors.csv")

    # Standardize column names
    df.columns = [c.strip() for c in df.columns]

    # --- Date column ---
    date_col = "date"
    if date_col not in df.columns:
        # fall back to first column if somehow named differently
        date_col = df.columns[0]

    df[date_col] = pd.to_datetime(df[date_col], errors="coerce").dt.normalize()
    df = df[df[date_col].notna()].copy()
    df.rename(columns={date_col: "date"}, inplace=True)

    # --- Player column ---
    if "player" not in df.columns:
        for cand in ["player_name", "name"]:
            if cand in df.columns:
                df.rename(columns={cand: "player"}, inplace=True)
                break

    if "player" not in df.columns:
        df["player"] = ""

    df["player"] = df["player"].fillna("").map(_normalize_player_name)

    # Make sure we have some basic text fields
    # (we'll be defensive when rendering)
    return df.sort_values("date").reset_index(drop=True)


def compute_player_scores(df: pd.DataFrame, window_end: pd.Timestamp) -> pd.DataFrame:
    """Compute weighted scores for players over the last WINDOW_DAYS."""
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()

    window_start = window_end - timedelta(days=WINDOW_DAYS - 1)

    recent_cutoff = window_end - timedelta(days=7)
    mid_cutoff = window_end - timedelta(days=14)
    old_cutoff = window_end - timedelta(days=28)

    # Only keep window + a tiny buffer (just in case)
    df = df[df["date"] >= old_cutoff].copy()

    def weight_for_day(d: pd.Timestamp) -> float:
        if d > recent_cutoff:
            return 1.0
        elif d > mid_cutoff:
            return 0.5
        elif d >= old_cutoff:
            return 0.25
        return 0.0

    df["weight"] = df["date"].map(weight_for_day)

    grouped = (
        df.groupby("player", dropna=True)
        .agg(
            score=("weight", "sum"),
            mentions_0_7=("date", lambda s: ((s > recent_cutoff) & (s <= window_end)).sum()),
            mentions_8_14=("date", lambda s: ((s > mid_cutoff) & (s <= recent_cutoff)).sum()),
            mentions_15_28=("date", lambda s: ((s >= old_cutoff) & (s <= mid_cutoff)).sum()),
        )
        .reset_index()
    )

    grouped = grouped[grouped["score"] > 0].copy()
    grouped.sort_values("score", ascending=False, inplace=True)
    grouped.insert(0, "Rank", range(1, len(grouped) + 1))

    # Nice column labels for display
    grouped.rename(
        columns={
            "player": "Player",
            "score": "Score",
            "mentions_0_7": "Mentions (0–7d)",
            "mentions_8_14": "Mentions (8–14d)",
            "mentions_15_28": "Mentions (15–28d)",
        },
        inplace=True,
    )
    return grouped.reset_index(drop=True)


def get_logo_html(player_name: str) -> str:
    """Return an <img> tag for the player's team logo, or empty string."""
    team = PLAYER_TO_TEAM.get(player_name)
    if not team:
        return ""
    logo_url = TEAM_TO_LOGO_URL.get(team)
    if not logo_url:
        return ""
    return f'<img src="{logo_url}" alt="{team}" class="team-logo" />'


def format_date_range(start: pd.Timestamp, end: pd.Timestamp) -> str:
    return f"{start.strftime('%b %d')} – {end.strftime('%b %d')}"


def get_text_column(df: pd.DataFrame) -> str:
    """Pick the best available column to display rumor text."""
    for cand in ["headline", "title", "snippet", "text", "body"]:
        if cand in df.columns:
            return cand
    return None


def get_highlight_column(df: pd.DataFrame) -> str:
    for cand in ["highlight", "highlight_text"]:
        if cand in df.columns:
            return cand
    return None


def get_media_column(df: pd.DataFrame) -> str:
    for cand in ["media", "source"]:
        if cand in df.columns:
            return cand
    return None


# ---------- Views ----------

def show_rankings(df_scores: pd.DataFrame, window_start, window_end):
    st.markdown(
        """
        <style>
        .headline {
            font-size: 2.4rem;
            font-weight: 800;
            margin-bottom: 0.25rem;
        }
        .subheadline {
            color: #475569;
            margin-bottom: 0.25rem;
        }
        .meta-text {
            color: #6b7280;
            font-size: 0.9rem;
            margin-bottom: 1.5rem;
        }
        .search-row {
            margin: 0.5rem 0 1.5rem 0;
        }
        .rank-table {
            width: 100%;
            border-collapse: separate;
            border-spacing: 0;
            font-size: 0.95rem;
        }
        .rank-table thead tr {
            background: #f3f4f6;
        }
        .rank-table th {
            text-align: left;
            padding: 0.65rem 0.9rem;
            font-weight: 600;
            border-bottom: 1px solid #e5e7eb;
            color: #4b5563;
            font-size: 0.8rem;
            text-transform: uppercase;
        }
        .rank-table tbody tr:nth-child(even) {
            background: #f9fafb;
        }
        .rank-table tbody tr:nth-child(odd) {
            background: #ffffff;
        }
        .rank-table td {
            padding: 0.65rem 0.9rem;
            border-bottom: 1px solid #e5e7eb;
            vertical-align: middle;
        }
        .rank-table td.rank-cell {
            width: 40px;
            color: #6b7280;
        }
        .rank-table a.player-link {
            text-decoration: none;
            color: #1d4ed8;
            font-weight: 500;
        }
        .rank-table a.player-link:hover {
            text-decoration: underline;
        }
        .team-logo {
            width: 22px;
            height: 22px;
            border-radius: 999px;
            margin-right: 0.45rem;
            vertical-align: middle;
            object-fit: contain;
        }
        .player-cell {
            display: flex;
            align-items: center;
            gap: 0.35rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.markdown('<div class="headline">NBA <span style="background: #fef08a;">Trade</span> <span style="background: #fef08a;">Rumor</span> Rankings</div>', unsafe_allow_html=True)

    st.markdown(
        f'<div class="subheadline">Based on <span style="background:#fef3c7;">trade rumors</span> from the last {WINDOW_DAYS} days.</div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        f'<div class="meta-text">Data last updated: {df_scores.index.max() if len(df_scores)==0 else df_scores.index.min():}</div>',
        unsafe_allow_html=True,
    )

    # Use the max date from the underlying data as "last updated"
    # (this is more accurate than "today" if there are no rumors today)
    last_date = window_end.strftime("%b %d, %Y")
    window_label = format_date_range(window_start, window_end)
    st.markdown(
        f'<div class="meta-text">Data last updated: {last_date} • Window: {window_label}</div>',
        unsafe_allow_html=True,
    )

    # --- Player jump box ---
    st.markdown("**Jump to a player page (type a name):**")
    options = [""] + df_scores["Player"].tolist()
    selected = st.selectbox(
        "Jump to player page",
        options=options,
        index=0,
        label_visibility="collapsed",
    )
    if selected:
        # Same-window navigation: update query params only
        st.query_params["player"] = selected
        st.rerun()

    # --- Rankings table ---
    headers = ["Rank", "Player", "Score", "Mentions (0–7d)", "Mentions (8–14d)", "Mentions (15–28d)"]

    rows_html = []
    for _, row in df_scores.iterrows():
        player = row["Player"]
        href = f"?player={quote(player)}"
        logo_html = get_logo_html(player)

        player_cell = (
            f'<div class="player-cell">'
            f'{logo_html}'
            f'<a class="player-link" href="{href}">{player}</a>'
            f'</div>'
        )

        rows_html.append(
            "<tr>"
            f'<td class="rank-cell">{int(row["Rank"])}</td>'
            f"<td>{player_cell}</td>"
            f"<td>{row['Score']:.2f}</td>"
            f"<td>{int(row['Mentions (0–7d)'])}</td>"
            f"<td>{int(row['Mentions (8–14d)'])}</td>"
            f"<td>{int(row['Mentions (15–28d)'])}</td>"
            "</tr>"
        )

    table_html = (
        "<table class='rank-table'>"
        "<thead><tr>"
        + "".join(f"<th>{h}</th>" for h in headers)
        + "</tr></thead><tbody>"
        + "".join(rows_html)
        + "</tbody></table>"
    )

    st.markdown("### Top trade-rumor targets (last 28 days)")
    st.markdown(table_html, unsafe_allow_html=True)


def show_player_view(df_all: pd.DataFrame, player: str, window_start, window_end):
    text_col = get_text_column(df_all)
    highlight_col = get_highlight_column(df_all)
    media_col = get_media_column(df_all)

    st.markdown(
        """
        <style>
        .back-link {
            display: inline-flex;
            align-items: center;
            gap: 0.25rem;
            padding: 0.35rem 0.7rem;
            border-radius: 999px;
            border: 1px solid #e5e7eb;
            background: #f9fafb;
            font-size: 0.9rem;
            color: #374151 !important;
            text-decoration: none;
            margin-bottom: 1rem;
        }
        .back-link:hover {
            background: #e5e7eb;
        }
        .chart-wrapper {
            background: #f9fafb;
            border-radius: 0.75rem;
            padding: 1.25rem 1.5rem 0.75rem 1.5rem;
            border: 1px solid #e5e7eb;
            margin-bottom: 1.5rem;
        }
        .chart-title {
            font-weight: 600;
            margin-bottom: 0.25rem;
        }
        .chart-subtitle {
            font-size: 0.85rem;
            color: #6b7280;
            margin-bottom: 0.75rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # Back link – plain href, no target="_blank" so it stays in the same window
    st.markdown(
        '<a class="back-link" href="/">&#8592; Back to rankings</a>',
        unsafe_allow_html=True,
    )

    st.markdown(f"## {player} – Trade Rumor Activity")

    df_player = df_all[df_all["player"] == player].copy()
    if df_player.empty:
        st.info("No trade rumors for this player in the current window.")
        return

    # Only last WINDOW_DAYS for the chart
    df_player_window = df_player[(df_player["date"] >= window_start) & (df_player["date"] <= window_end)].copy()

    days = pd.date_range(window_start, window_end, freq="D")
    daily_counts = (
        df_player_window
        .groupby(df_player_window["date"].dt.normalize())
        .size()
        .reindex(days, fill_value=0)
        .rename("mentions")
        .reset_index()
    )
    daily_counts.rename(columns={"index": "day", "date": "day"}, inplace=True)
    daily_counts["day"] = days

    max_y = max(3, daily_counts["mentions"].max() + 1)

    chart = (
        alt.Chart(daily_counts)
        .mark_area(line={"size": 2}, opacity=0.25)
        .encode(
            x=alt.X(
                "day:T",
                axis=alt.Axis(title=None, format="%b %d"),
            ),
            y=alt.Y(
                "mentions:Q",
                axis=alt.Axis(title="Mentions per day", tickMinStep=1),
                scale=alt.Scale(domain=[0, max_y]),
            ),
            tooltip=["day:T", "mentions:Q"],
        )
        .properties(height=260)
        .interactive()
    )

    st.markdown(
        f"""
        <div class="chart-wrapper">
          <div class="chart-title">Mentions per day</div>
          <div class="chart-subtitle">Last {WINDOW_DAYS} days ({format_date_range(window_start, window_end)})</div>
        """,
        unsafe_allow_html=True,
    )
    st.altair_chart(chart, use_container_width=True)
    st.markdown("</div>", unsafe_allow_html=True)

    # --- Recent rumors list ---
    st.markdown("### Most recent trade rumors")

    if df_player_window.empty:
        st.write("No trade rumors for this player in the last 28 days.")
        return

    df_player_window = df_player_window.sort_values("date", ascending=False).head(60)

    bullet_items = []
    for _, row in df_player_window.iterrows():
        date_str = row["date"].strftime("%b %d")
        media = row[media_col] if media_col and media_col in row.index and pd.notna(row[media_col]) else ""
        media_html = f"<strong>{media}</strong>" if media else ""

        url = row["url"] if "url" in row.index and pd.notna(row["url"]) else None

        # Choose base text
        text = ""
        if text_col and text_col in row.index and pd.notna(row[text_col]):
            text = str(row[text_col]).strip()

        # Choose highlight text
        highlight = ""
        if highlight_col and highlight_col in row.index and pd.notna(row[highlight_col]):
            highlight = str(row[highlight_col]).strip()

        if url and highlight and highlight in text:
            # Wrap ONLY the highlighted portion in a link
            linked = text.replace(
                highlight,
                f'<a href="{url}" rel="nofollow" target="_blank">{highlight}</a>',
                1,
            )
            text_html = linked
        elif url and text:
            # Fallback: link the media outlet only
            text_html = f'{text} <a href="{url}" rel="nofollow" target="_blank">{media or "Link"}</a>'
        else:
            text_html = text

        bullet_html = f"<li><span style='font-weight:600;'>{date_str}</span> – {media_html} {text_html}</li>"
        bullet_items.append(bullet_html)

    st.markdown("<ul>" + "".join(bullet_items) + "</ul>", unsafe_allow_html=True)

    # Back link at bottom as well, same-window
    st.markdown(
        '<a class="back-link" href="/">&#8592; Back to rankings</a>',
        unsafe_allow_html=True,
    )


# ---------- Main ----------

def main():
    df = load_rumors()
    if df.empty:
        st.error("No trade rumor data available yet.")
        return

    window_end = df["date"].max()
    window_start = window_end - timedelta(days=WINDOW_DAYS - 1)
    df_scores = compute_player_scores(df, window_end)

    params = st.query_params
    player_param = params.get("player", None)
    if isinstance(player_param, list):
        player_param = player_param[0]

    if player_param:
        show_player_view(df, player_param, window_start, window_end)
    else:
        show_rankings(df_scores, window_start, window_end)


if __name__ == "__main__":
    main()
