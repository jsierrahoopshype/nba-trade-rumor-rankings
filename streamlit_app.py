import math
from datetime import date, timedelta

import altair as alt
import pandas as pd
import streamlit as st
from urllib.parse import quote_plus, unquote_plus

WINDOW_DAYS = 28
CSV_PATH = "trade_rumors.csv"


# ------------------------
# Data loading & cleaning
# ------------------------
@st.cache_data
def load_rumors(csv_path: str = CSV_PATH) -> pd.DataFrame:
    df = pd.read_csv(csv_path)

    # Parse date column safely and normalize to midnight
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.normalize()
    df = df.dropna(subset=["date"])

    # Clean player column
    if "player" not in df.columns:
        df["player"] = ""
    df["player"] = df["player"].fillna("").astype(str).str.strip()

    # Drop useless / placeholder players
    bad_players = {"PLAYER", "Player", "", "NaN", "nan", "None"}
    df = df[~df["player"].isin(bad_players)].copy()

    # Keep only last WINDOW_DAYS based on the max date in the file
    max_date = df["date"].max().date()
    cutoff = max_date - timedelta(days=WINDOW_DAYS - 1)
    df = df[df["date"].dt.date >= cutoff].copy()

    # Ensure core text columns exist
    for col in ["snippet", "title", "url"]:
        if col not in df.columns:
            df[col] = ""

    return df


# ------------------------
# Scoring
# ------------------------
def compute_player_scores(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(
            columns=["player", "score", "mentions", "last_mention", "rank"]
        )

    # Use the latest date in the dataset as "today" (safer than system date)
    today = df["date"].max().normalize()
    df = df.copy()
    df["age_days"] = (today - df["date"]).dt.days

    # Initialize weights
    df["weight"] = 0.0
    df.loc[df["age_days"].between(0, 6), "weight"] = 1.0
    df.loc[df["age_days"].between(7, 13), "weight"] = 0.5
    df.loc[df["age_days"].between(14, 27), "weight"] = 0.25

    df = df[df["weight"] > 0].copy()
    if df.empty:
        return pd.DataFrame(
            columns=["player", "score", "mentions", "last_mention", "rank"]
        )

    grouped = (
        df.groupby("player")
        .agg(
            score=("weight", "sum"),
            mentions=("weight", "size"),  # raw count of mentions
            last_mention=("date", "max"),
        )
        .reset_index()
    )

    grouped = grouped[grouped["score"] > 0].copy()
    if grouped.empty:
        return pd.DataFrame(
            columns=["player", "score", "mentions", "last_mention", "rank"]
        )

    grouped.sort_values(
        by=["score", "last_mention", "player"],
        ascending=[False, False, True],
        inplace=True,
    )
    grouped["rank"] = range(1, len(grouped) + 1)

    # Clean types for display
    grouped["score"] = grouped["score"].round(2)
    grouped["last_mention"] = grouped["last_mention"].dt.date

    return grouped[["rank", "player", "score", "mentions", "last_mention"]]


# ------------------------
# UI helpers
# ------------------------
def player_link(player_name: str) -> str:
    """Markdown link that stays in the same page using query params."""
    if not player_name:
        return ""
    encoded = quote_plus(player_name)
    return f"[{player_name}](?player={encoded})"


def build_rankings_markdown(df_scores: pd.DataFrame) -> str:
    if df_scores.empty:
        return "_No trade-rumor activity in the last 28 days._"

    header = "| Rank | Player | Score | Mentions | Last mention |\n"
    header += "|---:|---|---:|---:|---|\n"
    rows = []
    for _, row in df_scores.iterrows():
        rank = int(row["rank"])
        player = row["player"]
        score = row["score"]
        mentions = int(row["mentions"])
        last_date = row["last_mention"]
        if hasattr(last_date, "strftime"):
            last_str = last_date.strftime("%b %d")
        else:
            last_str = str(last_date)

        link = player_link(player)
        rows.append(
            f"| {rank} | {link} | {score:.2f} | {mentions} | {last_str} |"
        )
    return header + "\n".join(rows)


def get_player_param() -> str | None:
    params = st.query_params
    if "player" not in params:
        return None
    val = params.get("player")
    # st.query_params can give str or list
    if isinstance(val, list):
        return unquote_plus(val[0]) if val else None
    return unquote_plus(val)


def set_player_param(player: str | None):
    if player:
        st.query_params["player"] = quote_plus(player)
    else:
        # Clear all query params → back to rankings
        st.query_params.clear()


# ------------------------
# Player view
# ------------------------
def show_player_view(df_rumors: pd.DataFrame, player_name: str):
    st.title(f"{player_name} – Trade Rumor Heat Index")

    # Back button at the top
    if st.button("← Back to rankings", key="back_top"):
        set_player_param(None)
        st.rerun()

    df_p = df_rumors[df_rumors["player"] == player_name].copy()
    if df_p.empty:
        st.info("No trade rumors for this player in the last 28 days.")
        if st.button("← Back to rankings", key="back_bottom_empty"):
            set_player_param(None)
            st.rerun()
        return

    # Use latest date in dataset as "today"
    max_date = df_rumors["date"].max().normalize()
    start_date = max_date - timedelta(days=WINDOW_DAYS - 1)
    idx = pd.date_range(start_date, max_date, freq="D")

    # Daily counts
    counts = (
        df_p.groupby("date")
        .size()
        .reindex(idx, fill_value=0)
    )

    df_daily = pd.DataFrame(
        {
            "day": idx,
            "mentions": counts.values,
        }
    )
    # For nicer axis labels
    df_daily["day_label"] = df_daily["day"].dt.strftime("%b %d")

    st.subheader("Mentions per day (last 28 days)")

    line_chart = (
        alt.Chart(df_daily)
        .mark_line(point=True)
        .encode(
            x=alt.X(
                "day:T",
                axis=alt.Axis(format="%b %d", title="Date"),
            ),
            y=alt.Y(
                "mentions:Q",
                axis=alt.Axis(title="Mentions per day"),
                scale=alt.Scale(domain=[0, df_daily["mentions"].max() + 0.5]),
            ),
            tooltip=[
                alt.Tooltip("day:T", title="Date", format="%b %d, %Y"),
                alt.Tooltip("mentions:Q", title="Mentions"),
            ],
        )
        .properties(height=280)
    )

    area = (
        alt.Chart(df_daily)
        .mark_area(opacity=0.1)
        .encode(
            x="day:T",
            y="mentions:Q",
        )
    )

    st.altair_chart(area + line_chart, use_container_width=True)

    # Most recent rumors block
    st.subheader("Most recent rumors")

    df_recent = df_p.sort_values("date", ascending=False).head(15)

    for _, row in df_recent.iterrows():
        d = row["date"]
        if hasattr(d, "strftime"):
            d_str = d.strftime("%b %d, %Y")
        else:
            d_str = str(d)

        title = str(row.get("title", "") or "").strip()
        snippet = str(row.get("snippet", "") or "").strip()
        url = str(row.get("url", "") or "").strip()

        # If no dedicated highlight, fall back to snippet
        highlight = title or snippet
        rest = ""
        # If both exist and are different, show both
        if title and snippet and snippet != title:
            rest = " " + snippet

        # Only the highlight text is clickable
        if url:
            highlight_md = f"[{highlight}]({url})"
        else:
            highlight_md = highlight

        # We don't have a reliable media/source column in all rows,
        # so we just show the date + text.
        md = f"- **{d_str}** – {highlight_md}{rest}"
        st.markdown(md)

    # Back button at the bottom
    if st.button("← Back to rankings", key="back_bottom"):
        set_player_param(None)
        st.rerun()


# ------------------------
# Rankings view
# ------------------------
def show_rankings(df_scores: pd.DataFrame):
    st.title("NBA Trade Rumor Heat Index")

    st.markdown(
        """
        Rankings based on how often players appear in trade rumors over the last **28 days**,  
        with recent mentions weighted more heavily:

        - **1 point** per mention in the last **7 days**  
        - **0.5 points** per mention **8–14 days** ago  
        - **0.25 points** per mention **15–28 days** ago
        """
    )

    if df_scores.empty:
        st.info("No trade-rumor data available for the last 28 days.")
        return

    # Search & quick jump
    col1, col2 = st.columns([2, 2])

    with col1:
        search = st.text_input("Search for a player").strip()

    with col2:
        players_sorted = df_scores["player"].tolist()
        jump = st.selectbox(
            "Jump to a player page",
            options=[""] + players_sorted,
            index=0,
        )
        if jump:
            set_player_param(jump)
            st.rerun()

    # Filter by search
    df_display = df_scores.copy()
    if search:
        df_display = df_display[
            df_display["player"].str.contains(search, case=False, na=False)
        ]

    # Build markdown rankings table with clickable names
    rankings_md = build_rankings_markdown(df_display)
    st.markdown(rankings_md)


# ------------------------
# Main
# ------------------------
def main():
    st.set_page_config(
        page_title="NBA Trade Rumor Heat Index",
        layout="wide",
    )

    df_rumors = load_rumors()

    player_param = get_player_param()
    if player_param:
        show_player_view(df_rumors, player_param)
    else:
        df_scores = compute_player_scores(df_rumors)
        show_rankings(df_scores)


if __name__ == "__main__":
    main()
