import re
from urllib.parse import urlparse

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st


# ---------- Helpers ----------


def slugify(name: str) -> str:
    """Turn 'Anthony Davis' into 'anthony-davis'."""
    if not isinstance(name, str):
        return ""
    slug = name.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug


def clean_snippet(text: str) -> str:
    """Trim HH extra tags from the snippet for a cleaner quote."""
    if not isinstance(text, str):
        return ""
    text = text.strip()

    # Drop trailing " x.com Team , Trade , Player" junk if present
    if " x.com " in text:
        text = text.split(" x.com ")[0].strip()

    # Remove trailing team/tag lists if they sneak in
    text = re.sub(r"\s+[A-Z][a-zA-Z ]*,\s*Trade.*$", "", text)

    return text.strip()


def infer_source(row: pd.Series) -> str:
    """Use the 'source' column if present, otherwise infer from URL."""
    src = str(row.get("source", "") or "").strip()
    if src:
        return src

    url = str(row.get("url", "") or "").strip()
    if not url:
        return ""

    try:
        domain = urlparse(url).netloc
    except Exception:
        return ""
    domain = domain.replace("www.", "")
    return domain


@st.cache_data(show_spinner=False)
def load_rumors() -> pd.DataFrame:
    """Load and clean trade_rumors.csv."""
    df = pd.read_csv("trade_rumors.csv")

    required = {"date", "player", "url"}
    missing = required - set(df.columns)
    if missing:
        st.error(
            f"trade_rumors.csv is missing required columns: {', '.join(sorted(missing))}"
        )
        return pd.DataFrame()

    # Parse dates
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.normalize()
    df = df.dropna(subset=["date"])

    # Clean player names
    df["player"] = df["player"].fillna("").astype(str).str.strip()
    df = df[df["player"] != ""]
    df = df[df["player"].str.upper() != "PLAYER"]

    # Fix known name issues
    NAME_FIXES = {
        "Lebron James": "LeBron James",
        "LEBRON JAMES": "LeBron James",
        "Karl-anthony Towns": "Karl-Anthony Towns",
        "Karl-Anthony towns": "Karl-Anthony Towns",
        "Karl Anthony Towns": "Karl-Anthony Towns",
    }
    df["player"] = df["player"].replace(NAME_FIXES)

    # Ensure text columns exist and are strings
    for col in ["team", "source", "snippet", "title", "url"]:
        if col not in df.columns:
            df[col] = ""
        df[col] = df[col].fillna("").astype(str).str.strip()

    # Sort oldest → newest
    df = df.sort_values("date").reset_index(drop=True)
    return df


def compute_player_scores(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute weighted scores and bucketed counts for the last 28 days.

    Weights:
      - 1 point per mention in the last 7 days
      - 0.5 points per mention 8–14 days ago
      - 0.25 points per mention 15–28 days ago
    """
    if df.empty:
        return pd.DataFrame(
            columns=[
                "Rank",
                "player",
                "score",
                "mentions_0_7",
                "mentions_8_14",
                "mentions_15_28",
            ]
        )

    today = df["date"].max().normalize()
    cutoff_7 = today - pd.Timedelta(days=7)
    cutoff_14 = today - pd.Timedelta(days=14)
    cutoff_28 = today - pd.Timedelta(days=28)

    df_recent = df[df["date"] >= cutoff_28].copy()
    if df_recent.empty:
        return pd.DataFrame(
            columns=[
                "Rank",
                "player",
                "score",
                "mentions_0_7",
                "mentions_8_14",
                "mentions_15_28",
            ]
        )

    # Weights
    df_recent["weight"] = np.where(
        df_recent["date"] >= cutoff_7,
        1.0,
        np.where(df_recent["date"] >= cutoff_14, 0.5, 0.25),
    )

    grouped = df_recent.groupby("player", as_index=False)

    scores = grouped["weight"].sum().rename(columns={"weight": "score"})

    m0_7 = (
        df_recent[df_recent["date"] >= cutoff_7]
        .groupby("player")
        .size()
        .rename("mentions_0_7")
    )
    m8_14 = (
        df_recent[
            (df_recent["date"] < cutoff_7) & (df_recent["date"] >= cutoff_14)
        ]
        .groupby("player")
        .size()
        .rename("mentions_8_14")
    )
    m15_28 = (
        df_recent[
            (df_recent["date"] < cutoff_14) & (df_recent["date"] >= cutoff_28)
        ]
        .groupby("player")
        .size()
        .rename("mentions_15_28")
    )

    out = scores.set_index("player")
    out = out.join(m0_7, how="left")
    out = out.join(m8_14, how="left")
    out = out.join(m15_28, how="left")
    out = out.fillna(0)

    for col in ["mentions_0_7", "mentions_8_14", "mentions_15_28"]:
        out[col] = out[col].astype(int)

    out = out.reset_index()

    # Sort and rank
    out = out.sort_values(
        ["score", "mentions_0_7", "mentions_8_14", "mentions_15_28", "player"],
        ascending=[False, False, False, False, True],
    ).reset_index(drop=True)
    out.insert(0, "Rank", range(1, len(out) + 1))

    return out


def render_header(df_window: pd.DataFrame, window_start: pd.Timestamp, window_end: pd.Timestamp):
    """Title + description + last updated line."""
    st.markdown(
        """
        <style>
        .main-title {
            font-size: 40px;
            font-weight: 800;
            margin-bottom: 0.25rem;
        }
        .pill-highlight {
            background-color: #ffe66d;
            padding: 0 0.15em;
            border-radius: 0.25rem;
        }
        .subtle-text {
            color: #666666;
            font-size: 0.9rem;
            margin-bottom: 0.4rem;
        }
        .tiny-text {
            color: #888888;
            font-size: 0.8rem;
            margin-bottom: 1.2rem;
        }
        .ranking-table {
            border-collapse: collapse;
            width: 100%;
        }
        .ranking-table th, .ranking-table td {
            padding: 0.35rem 0.5rem;
            border-bottom: 1px solid #e2e2e2;
            font-size: 0.9rem;
            text-align: left;
        }
        .ranking-table th {
            font-weight: 700;
        }
        .ranking-table tr:hover td {
            background-color: #fafafa;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    start_str = window_start.strftime("%b %d")
    end_str = window_end.strftime("%b %d")
    last_updated = df_window["date"].max().strftime("%b %d, %Y")

    st.markdown(
        f"""
        <div class="main-title">
            NBA <span class="pill-highlight">Trade</span>
            <span class="pill-highlight">Rumor</span> Rankings
        </div>
        <div class="subtle-text">
            Based on <span class="pill-highlight">trade rumors</span>
            from the last 28 days ({start_str} – {end_str}).
        </div>
        <div class="tiny-text">
            Data last updated: {last_updated}.
        </div>
        """,
        unsafe_allow_html=True,
    )


def show_rankings(df_scores: pd.DataFrame, player_to_slug: dict):
    st.subheader("Top trade-rumor targets (last 28 days)")

    if df_scores.empty:
        st.info("No trade rumors found in the last 28 days.")
        return

    df_scores = df_scores.copy()
    df_scores["slug"] = df_scores["player"].map(player_to_slug)

    # Build clickable player links (same tab)
    df_scores["Player"] = df_scores.apply(
        lambda row: f'<a href="/?player={row["slug"]}">{row["player"]}</a>', axis=1
    )

    df_display = df_scores[
        ["Rank", "Player", "score", "mentions_0_7", "mentions_8_14", "mentions_15_28"]
    ].rename(
        columns={
            "score": "Score",
            "mentions_0_7": "Mentions (0–7d)",
            "mentions_8_14": "Mentions (8–14d)",
            "mentions_15_28": "Mentions (15–28d)",
        }
    )

    table_html = df_display.to_html(
        escape=False, index=False, classes="ranking-table"
    )
    st.markdown(table_html, unsafe_allow_html=True)


def show_player_view(
    df_window: pd.DataFrame,
    player_name: str,
    window_start: pd.Timestamp,
    window_end: pd.Timestamp,
):
    """Detail view for a single player (last 28 days only)."""
    player_df = df_window[df_window["player"] == player_name].copy()

    back_html = '<a href="/" style="text-decoration:none;">← Back to rankings</a>'
    st.markdown(back_html, unsafe_allow_html=True)

    st.markdown(
        f"## {player_name} – Trade Rumor Activity",
        unsafe_allow_html=False,
    )

    # --- Mentions per day chart (28 days) ---
    days = pd.date_range(start=window_start, end=window_end, freq="D")

    daily_series = (
        player_df.groupby("date")
        .size()
        .reindex(days, fill_value=0)
    )
    daily_series.index.name = "day"
    daily_counts = daily_series.reset_index(name="mentions")

    st.caption("Mentions per day (last 28 days)")

    if daily_counts["mentions"].sum() == 0:
        st.info("No trade rumors for this player in the last 28 days.")
    else:
        y_max = max(1, daily_counts["mentions"].max())
        chart = (
            alt.Chart(daily_counts)
            .mark_line(point=True)
            .encode(
                x=alt.X(
                    "day:T",
                    axis=alt.Axis(format="%b %d", labelAngle=-45, title=""),
                ),
                y=alt.Y(
                    "mentions:Q",
                    axis=alt.Axis(title="Mentions per day", tickMinStep=1),
                    scale=alt.Scale(domain=(0, y_max + 0.5)),
                ),
                tooltip=[
                    alt.Tooltip("day:T", title="Date", format="%b %d, %Y"),
                    alt.Tooltip("mentions:Q", title="Mentions"),
                ],
            )
            .properties(height=260)
        )
        st.altair_chart(chart, use_container_width=True)

    # --- Recent rumors list (28 days only) ---
    st.markdown("### Most recent trade rumors")

    recent_rumors = (
        player_df.sort_values("date", ascending=False)
        .reset_index(drop=True)
    )

    if recent_rumors.empty:
        st.info("No trade rumors for this player in the last 28 days.")
        return

    items = []
    for _, row in recent_rumors.iterrows():
        date_label = row["date"].strftime("%b %d")
        source = infer_source(row)
        quote = clean_snippet(row.get("snippet", ""))
        url = row.get("url", "")

        # Fallbacks
        if not quote:
            quote = row.get("title", "") or "(View rumor)"

        source_html = (
            f"<span style='font-weight:600;'>{source}</span>" if source else ""
        )

        item_html = (
            f"<li><strong>{date_label}</strong>"
            f"{' – ' + source_html if source_html else ''}: "
            f"<a href='{url}' rel='nofollow'>{quote}</a></li>"
        )
        items.append(item_html)

    st.markdown("<ul>" + "\n".join(items) + "</ul>", unsafe_allow_html=True)

    st.markdown(back_html, unsafe_allow_html=True)


# ---------- Main app ----------


def main():
    st.set_page_config(
        page_title="NBA Trade Rumor Rankings",
        page_icon="📈",
        layout="wide",
    )

    df = load_rumors()
    if df.empty:
        st.stop()

    # Define the 28-day window based on the newest date we have
    window_end = df["date"].max().normalize()
    window_start = window_end - pd.Timedelta(days=27)

    df_window = df[df["date"].between(window_start, window_end)].copy()

    # Map players <-> slugs using the windowed data
    unique_players = sorted(df_window["player"].unique())
    player_to_slug = {p: slugify(p) for p in unique_players}
    slug_to_player = {v: k for k, v in player_to_slug.items()}

    # Determine whether we are on rankings view or a player page
    try:
        player_slug = st.query_params.get("player", None)
    except Exception:
        player_slug = None

    if player_slug and player_slug in slug_to_player:
        # --- Player detail view ---
        render_header(df_window, window_start, window_end)
        show_player_view(
            df_window,
            slug_to_player[player_slug],
            window_start,
            window_end,
        )
        return

    # --- Rankings (main) view ---
    render_header(df_window, window_start, window_end)

    df_scores = compute_player_scores(df_window)

    # Search box that filters the rankings table
    search_query = st.text_input("Search for a player")
    if search_query.strip():
        mask = df_scores["player"].str.contains(
            search_query, case=False, na=False
        )
        filtered_scores = df_scores[mask].reset_index(drop=True)
        # Re-rank just the filtered view
        filtered_scores = filtered_scores.copy()
        filtered_scores["Rank"] = range(1, len(filtered_scores) + 1)
    else:
        filtered_scores = df_scores

    # Jump-to-player dropdown
    st.caption("Jump to a player page")
    jump_choice = st.selectbox(
        "Jump to a player page",
        options=[""] + unique_players,
        index=0,
        label_visibility="collapsed",
    )
    if jump_choice:
        slug = player_to_slug.get(jump_choice)
        if slug:
            st.query_params["player"] = slug
            st.rerun()

    show_rankings(filtered_scores, player_to_slug)


if __name__ == "__main__":
    main()
