import os
import re
from datetime import date, datetime, timedelta

import altair as alt
import pandas as pd
import streamlit as st

# -------------------------------------------------------------------
# Basic config
# -------------------------------------------------------------------
st.set_page_config(
    page_title="NBA Trade Rumor Heat Index",
    layout="wide",
)

DATA_CANDIDATES = [
    "trade_rumors.csv",           # root of repo / Space
    "/app/trade_rumors.csv",      # HF Space root
    "/app/src/trade_rumors.csv",  # inside src
]


# -------------------------------------------------------------------
# Data loading / cleaning
# -------------------------------------------------------------------
def load_rumor_data() -> pd.DataFrame:
    """Load trade_rumors.csv from one of the known locations and normalize."""
    last_err = None
    df = None

    for path in DATA_CANDIDATES:
        if os.path.exists(path):
            try:
                df = pd.read_csv(path)
                break
            except Exception as e:  # noqa: BLE001
                last_err = e

    if df is None:
        st.error(
            "No trade-rumor data found yet. The app could not locate "
            "`trade_rumors.csv` in the expected locations."
        )
        if last_err is not None:
            st.caption(f"Last error while trying to read a CSV: {last_err}")
        st.stop()

    expected_cols = {"player", "slug", "date", "title", "url"}
    missing = expected_cols - set(df.columns)
    if missing:
        st.error(
            "The CSV is missing some expected columns: "
            + ", ".join(sorted(missing))
        )
        st.stop()

    # Normalize date column to date objects (no timezone headaches)
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    df = df.dropna(subset=["player", "slug", "date"])

    return df


# -------------------------------------------------------------------
# Scoring helpers
# -------------------------------------------------------------------
def compute_player_scores(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute 0–7d, 8–14d, 15–28d buckets and weighted score per player (slug).
    """
    if df.empty:
        return pd.DataFrame(
            columns=[
                "slug",
                "player",
                "score",
                "mentions_0_7",
                "mentions_8_14",
                "mentions_15_28",
            ]
        )

    # Consider only the last 28 days relative to the *latest* date we have
    latest_date: date = df["date"].max()
    cutoff_28 = latest_date - timedelta(days=28)

    df_28 = df[df["date"] >= cutoff_28].copy()
    if df_28.empty:
        return pd.DataFrame(
            columns=[
                "slug",
                "player",
                "score",
                "mentions_0_7",
                "mentions_8_14",
                "mentions_15_28",
            ]
        )

    # days_ago = 0 means "today" (latest_date in the data)
    df_28["days_ago"] = df_28["date"].apply(
        lambda d: (latest_date - d).days
    )

    # Buckets
    mask_0_7 = df_28["days_ago"] <= 7
    mask_8_14 = (df_28["days_ago"] > 7) & (df_28["days_ago"] <= 14)
    mask_15_28 = (df_28["days_ago"] > 14) & (df_28["days_ago"] <= 28)

    by_slug_name = df_28[["slug", "player"]].drop_duplicates()
    name_by_slug = by_slug_name.set_index("slug")["player"].to_dict()

    counts_0_7 = (
        df_28[mask_0_7]
        .groupby("slug")
        .size()
        .rename("mentions_0_7")
    )
    counts_8_14 = (
        df_28[mask_8_14]
        .groupby("slug")
        .size()
        .rename("mentions_8_14")
    )
    counts_15_28 = (
        df_28[mask_15_28]
        .groupby("slug")
        .size()
        .rename("mentions_15_28")
    )

    all_slugs = counts_0_7.index.union(counts_8_14.index).union(
        counts_15_28.index
    )

    scores = pd.DataFrame(index=all_slugs)
    scores["mentions_0_7"] = counts_0_7.reindex(all_slugs, fill_value=0)
    scores["mentions_8_14"] = counts_8_14.reindex(all_slugs, fill_value=0)
    scores["mentions_15_28"] = counts_15_28.reindex(all_slugs, fill_value=0)

    scores["mentions_0_7"] = scores["mentions_0_7"].astype(int)
    scores["mentions_8_14"] = scores["mentions_8_14"].astype(int)
    scores["mentions_15_28"] = scores["mentions_15_28"].astype(int)

    scores["score"] = (
        scores["mentions_0_7"]
        + 0.5 * scores["mentions_8_14"]
        + 0.25 * scores["mentions_15_28"]
    )

    scores["player"] = scores.index.map(name_by_slug)
    scores = scores.reset_index().rename(columns={"index": "slug"})

    scores = scores.sort_values(
        ["score", "mentions_0_7", "mentions_8_14", "mentions_15_28"],
        ascending=False,
    ).reset_index(drop=True)

    scores.insert(0, "Rank", scores.index + 1)

    return scores


# -------------------------------------------------------------------
# Utility for cleaning the rumor HTML so it looks like the site
# -------------------------------------------------------------------
def clean_rumor_html(raw: str) -> str:
    """
    Remove onclick/target/etc so links behave normally (same tab, no JS).
    We keep the quote + outlet linking exactly like on HoopsHype.
    """
    if not isinstance(raw, str):
        return ""

    html = raw

    # Strip onclick handlers that force new windows
    html = re.sub(r'onclick="[^"]*"', "", html)
    # Strip target attributes
    html = re.sub(r'target="[^"]*"', "", html)

    # That's enough: Streamlit will render this, and only the embedded
    # <a class="quote"> and <a class="rumormedia"> bits will be links.
    return html


def format_day(d: date) -> str:
    """Month + day, e.g. 'Nov 26'."""
    return datetime(d.year, d.month, d.day).strftime("%b %-d")


# -------------------------------------------------------------------
# Views
# -------------------------------------------------------------------
def go_back_to_rankings():
    """Clear query params and re-run app."""
    st.query_params.clear()
    st.rerun()


def show_rankings(df_scores: pd.DataFrame):
    st.title("NBA Trade Rumor Heat Index")

    st.write(
        "Rankings based on how often players appear in trade rumors "
        "over the last 28 days, with recent mentions weighted more heavily."
    )

    st.markdown(
        """
* **1 point** per mention in the last **7 days**
* **0.5 points** per mention **8–14 days** ago
* **0.25 points** per mention **15–28 days** ago
        """
    )

    # Search box (filters table only)
    search_term = st.text_input("Search for a player", "").strip().lower()

    # Jump directly to a player page via dropdown
    if not df_scores.empty:
        jump_name = st.selectbox(
            "Jump to a player page",
            [""] + sorted(df_scores["player"].tolist()),
            index=0,
        )
        if jump_name:
            slug = (
                df_scores.loc[df_scores["player"] == jump_name, "slug"]
                .iloc[0]
            )
            st.query_params["player"] = slug
            st.rerun()

    # Prepare table for display with clickable player names
    if df_scores.empty:
        st.info("No trade-rumor data yet in the last 28 days.")
        return

    df_display = df_scores.copy()

    # Markdown links that keep you inside the same Space (no new tab)
    df_display["Player"] = df_display.apply(
        lambda row: f"[{row['player']}]"
        f"(?player={row['slug']})",
        axis=1,
    )

    if search_term:
        mask = df_display["player"].str.lower().str.contains(search_term)
        df_display = df_display[mask]

    df_display = df_display[
        ["Rank", "Player", "score", "mentions_0_7", "mentions_8_14", "mentions_15_28"]
    ].rename(
        columns={
            "score": "Score",
            "mentions_0_7": "Mentions (0–7d)",
            "mentions_8_14": "Mentions (8–14d)",
            "mentions_15_28": "Mentions (15–28d)",
        }
    )

    # Use pandas -> markdown so links work; requires tabulate
    table_md = df_display.to_markdown(index=False)
    st.markdown(table_md, unsafe_allow_html=True)


def show_player_view(df: pd.DataFrame, player_slug: str):
    df_player = df[df["slug"] == player_slug].copy()

    if df_player.empty:
        st.warning("No rumors found for this player.")
        if st.button("← Back to rankings", key="back_top_empty"):
            go_back_to_rankings()
        return

    player_name = df_player["player"].iloc[0]

    # Back button at the top
    col_back, _ = st.columns([1, 4])
    with col_back:
        if st.button("← Back to rankings", key="back_top"):
            go_back_to_rankings()

    st.header(f"{player_name} – Trade Rumor Activity")

    latest_date: date = df["date"].max()
    start_date = latest_date - timedelta(days=365)

    df_player_recent = df_player[df_player["date"] >= start_date].copy()

    # Daily counts, reindexed so missing days are shown as 0
    daily_counts = (
        df_player_recent.groupby("date")
        .size()
        .rename("mentions")
    )

    full_index = pd.date_range(start_date, latest_date, freq="D")
    full_counts = daily_counts.reindex(
        [d.date() for d in full_index], fill_value=0
    )

    chart_df = pd.DataFrame(
        {
            "day": full_index,
            "mentions": full_counts.values,
        }
    )

    max_y = max(chart_df["mentions"].max(), 1)

    chart = (
        alt.Chart(chart_df)
        .mark_line(point=True)
        .encode(
            x=alt.X(
                "day:T",
                axis=alt.Axis(
                    title=None,
                    format="%b %d",  # Month + number (e.g. Nov 26)
                    labelAngle=-45,
                ),
            ),
            y=alt.Y(
                "mentions:Q",
                axis=alt.Axis(title="Mentions per day"),
                scale=alt.Scale(domain=(0, max_y + 0.5)),
            ),
            tooltip=[
                alt.Tooltip("day:T", title="Date", format="%b %d, %Y"),
                alt.Tooltip("mentions:Q", title="Mentions"),
            ],
        )
        .properties(width=800, height=300)
    )

    st.subheader("Mentions per day")
    st.altair_chart(chart, use_container_width=True)

    # Most recent rumors list (cleaned HTML)
    st.subheader("Most recent trade rumors")

    df_player_sorted = df_player.sort_values(
        "date", ascending=False
    ).head(25)

    for _, row in df_player_sorted.iterrows():
        rumor_date: date = row["date"]
        date_str = format_day(rumor_date)

        cleaned = clean_rumor_html(row.get("title", ""))

        # If the "title" column is HTML from the site, this will render
        # the quote and outlet nicely, with only those pieces hyperlinked.
        st.markdown(
            f"- **{date_str}** – {cleaned}",
            unsafe_allow_html=True,
        )

    # Back button at the bottom as well
    if st.button("← Back to rankings", key="back_bottom"):
        go_back_to_rankings()


# -------------------------------------------------------------------
# Main
# -------------------------------------------------------------------
def main():
    df_rumors = load_rumor_data()

    # NOTE: use the non-experimental API so that yellow warning disappears
    player_slug = st.query_params.get("player", None)

    if player_slug:
        show_player_view(df_rumors, player_slug)
    else:
        df_scores = compute_player_scores(df_rumors)
        show_rankings(df_scores)


if __name__ == "__main__":
    main()
