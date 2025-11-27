import streamlit as st
import pandas as pd
import altair as alt
from datetime import datetime
from urllib.parse import urlparse

# ------------------------------------------------------------
# Global "today" (naive, normalised to midnight)
# ------------------------------------------------------------
TODAY = pd.Timestamp.today().normalize()


# ------------------------------------------------------------
# Data loading
# ------------------------------------------------------------
@st.cache_data
def load_trade_rumors() -> pd.DataFrame:
    """
    Load trade_rumors.csv from a few possible locations.
    Normalises the date column to pandas Timestamps (naive).
    """
    candidates = [
        "trade_rumors.csv",
        "/app/trade_rumors.csv",
        "/app/src/trade_rumors.csv",
    ]

    last_err = None
    for path in candidates:
        try:
            df = pd.read_csv(path)
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
            df = df.dropna(subset=["date"])
            # Ensure date is naive (no timezone)
            if df["date"].dt.tz is not None:
                df["date"] = df["date"].dt.tz_convert(None)
            return df
        except FileNotFoundError as e:
            last_err = e
            continue

    st.error(
        "No trade-rumor data found yet. "
        "Could not locate **trade_rumors.csv** in this Space."
    )
    if last_err is not None:
        st.text(str(last_err))
    st.stop()


# ------------------------------------------------------------
# Scoring / rankings
# ------------------------------------------------------------
def compute_player_scores(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute the weighted trade-rumor score per player.

    Windows:
    - 0–7 days ago   -> 1.0 point per mention
    - 8–14 days ago  -> 0.5 points per mention
    - 15–28 days ago -> 0.25 points per mention
    """
    # Work on a copy and normalise dates again to be extra safe
    df2 = df.copy()
    df2["date"] = pd.to_datetime(df2["date"], errors="coerce")
    df2 = df2.dropna(subset=["date"])

    if df2["date"].dt.tz is not None:
        df2["date"] = df2["date"].dt.tz_convert(None)

    df2["date_norm"] = df2["date"].dt.normalize()

    # How many days ago each rumor was (0 = today)
    today = TODAY  # naive Timestamp
    df2["days_ago"] = (today - df2["date_norm"]).dt.days

    # Keep only last 28 days
    df_recent = df2[(df2["days_ago"] >= 0) & (df2["days_ago"] < 28)].copy()

    # Weight per mention
    df_recent["weight"] = 0.0
    df_recent.loc[df_recent["days_ago"] <= 6, "weight"] = 1.0
    df_recent.loc[df_recent["days_ago"].between(7, 13), "weight"] = 0.5
    df_recent.loc[df_recent["days_ago"].between(14, 27), "weight"] = 0.25

    def count_in_range(s: pd.Series, lo: int, hi: int) -> int:
        return s.between(lo, hi).sum()

    grouped = (
        df_recent.groupby(["player", "slug"], as_index=False)
        .agg(
            score=("weight", "sum"),
            mentions_0_7=("days_ago", lambda s: count_in_range(s, 0, 6)),
            mentions_8_14=("days_ago", lambda s: count_in_range(s, 7, 13)),
            mentions_15_28=("days_ago", lambda s: count_in_range(s, 14, 27)),
        )
    )

    # Sort by score, then most recent mentions, then name
    grouped = grouped.sort_values(
        ["score", "mentions_0_7", "mentions_8_14", "player"],
        ascending=[False, False, False, True],
        ignore_index=True,
    )

    grouped["score"] = grouped["score"].round(2)

    return grouped


# ------------------------------------------------------------
# Helpers for query params
# ------------------------------------------------------------
def get_player_param() -> str | None:
    """
    Read the ?player= query param in a way that works with both
    st.experimental_get_query_params and st.query_params.
    """
    try:
        # New API (Streamlit >= 1.30)
        params = st.query_params
        val = params.get("player", None)
        if isinstance(val, list):
            return val[0] if val else None
        return val
    except Exception:
        # Fallback to old experimental API
        params = st.experimental_get_query_params()
        vals = params.get("player", [])
        return vals[0] if vals else None


def set_player_param(slug: str | None) -> None:
    """
    Set or clear the ?player= query param.
    """
    try:
        qp = st.query_params
        if slug:
            qp["player"] = slug
        else:
            qp.clear()
    except Exception:
        if slug:
            st.experimental_set_query_params(player=slug)
        else:
            st.experimental_set_query_params()


# ------------------------------------------------------------
# UI – main rankings view
# ------------------------------------------------------------
def show_rankings(df_scores: pd.DataFrame) -> None:
    st.title("NBA Trade Rumor Heat Index")

    st.write(
        "Rankings based on how often players appear in trade rumors over the last "
        "28 days, with recent mentions weighted more heavily."
    )

    st.markdown(
        """
- **1 point** per mention in the last **7 days**
- **0.5 points** per mention **8–14 days** ago
- **0.25 points** per mention **15–28 days** ago
"""
    )

    # --- Search box ---
    search = st.text_input("Search for a player")
    df_display = df_scores.copy()
    if search:
        df_display = df_display[
            df_display["player"].str.contains(search, case=False, na=False)
        ]

    # --- Jump-to select ---
    st.markdown("#### Jump to a player page")
    player_options = [""] + df_scores["player"].tolist()
    selected = st.selectbox(
        "", options=player_options, index=0, label_visibility="collapsed"
    )

    if selected:
        slug = df_scores.loc[df_scores["player"] == selected, "slug"].iloc[0]
        set_player_param(slug)
        st.rerun()

    # --- Clickable player links ---
    df_display = df_display.copy()
    df_display["Player"] = df_display.apply(
        lambda r: f"[{r['player']}](/?player={r['slug']})", axis=1
    )

    df_display = df_display[
        ["Player", "score", "mentions_0_7", "mentions_8_14", "mentions_15_28"]
    ]

    df_display.index = range(1, len(df_display) + 1)
    df_display.index.name = "Rank"

    df_display = df_display.rename(
        columns={
            "score": "Score",
            "mentions_0_7": "Mentions (0–7d)",
            "mentions_8_14": "Mentions (8–14d)",
            "mentions_15_28": "Mentions (15–28d)",
        }
    )

    st.markdown("### Rankings")
    st.dataframe(df_display, use_container_width=True)


# ------------------------------------------------------------
# Helpers for player page formatting
# ------------------------------------------------------------
def nice_date(dt: pd.Timestamp) -> str:
    # e.g. "Nov 26"
    return dt.strftime("%b %d").lstrip("0")


def outlet_from_url(url: str) -> str:
    try:
        host = urlparse(url).netloc
        if host.startswith("www."):
            host = host[4:]
        return host or url
    except Exception:
        return url


def split_quote(text: str) -> tuple[str, str | None, str]:
    """
    Try to split the text into (before, quote, after) where 'quote'
    is the text between fancy quotes “...”.
    If none found, quote is None and the full text goes into 'before'.
    """
    if not isinstance(text, str):
        return "", None, ""

    start = text.find("“")
    end = text.rfind("”")
    if 0 <= start < end:
        before = text[: start].strip()
        quote = text[start + 1 : end].strip()
        after = text[end + 1 :].strip()
        return before, quote, after
    else:
        return text.strip(), None, ""


# ------------------------------------------------------------
# UI – per-player view
# ------------------------------------------------------------
def show_player_view(df: pd.DataFrame, player_slug: str) -> None:
    df_player = df[df["slug"] == player_slug].copy()
    if df_player.empty:
        st.error("No rumors found for this player in the dataset.")
        if st.button("⬅ Back to rankings"):
            set_player_param(None)
            st.rerun()
        return

    df_player = df_player.sort_values("date", ascending=False)
    player_name = df_player["player"].iloc[0]

    # Back button at top
    if st.button("⬅ Back to rankings", key="back_top"):
        set_player_param(None)
        st.rerun()

    st.title(f"{player_name} – Trade Rumor Activity")

    # --------------------------------------------------------
    # Mentions per day line chart (last 12 months)
    # --------------------------------------------------------
    st.subheader("Mentions per day")

    end_day = TODAY
    start_day = end_day - pd.Timedelta(days=365)

    df_player_period = df_player[
        (df_player["date"] >= start_day) & (df_player["date"] <= end_day)
    ].copy()

    df_player_period["day"] = df_player_period["date"].dt.normalize()

    daily = (
        df_player_period.groupby("day", as_index=False)
        .size()
        .rename(columns={"size": "mentions"})
    )

    all_days = pd.DataFrame(
        {
            "day": pd.date_range(
                start=start_day.normalize(), end=end_day.normalize(), freq="D"
            )
        }
    )

    daily_full = (
        all_days.merge(daily, on="day", how="left")
        .fillna({"mentions": 0})
        .astype({"mentions": "int64"})
    )

    chart = (
        alt.Chart(daily_full)
        .mark_line(point=True)
        .encode(
            x=alt.X(
                "day:T",
                axis=alt.Axis(format="%b %d", title="Date"),
            ),
            y=alt.Y(
                "mentions:Q",
                title="Mentions per day",
                scale=alt.Scale(domainMin=0),
            ),
            tooltip=[
                alt.Tooltip("day:T", title="Date", format="%b %d, %Y"),
                alt.Tooltip("mentions:Q", title="Mentions"),
            ],
        )
        .properties(height=300)
    )

    st.altair_chart(chart, use_container_width=True)

    # --------------------------------------------------------
    # Most recent rumors
    # --------------------------------------------------------
    st.subheader("Most recent trade rumors")

    # Take the most recent 30 rumors for this player
    recent = df_player.head(30)

    for _, row in recent.iterrows():
        date_str = nice_date(row["date"])
        title = row.get("title", "")
        url = row.get("url", "")
        outlet = outlet_from_url(url)

        before, quote, after = split_quote(title)

        if quote:
            text_html = f"{before} <strong>{quote}</strong>"
            if after:
                text_html += " " + after
        else:
            text_html = before  # whole title

        bullet = (
            f"- **{date_str} – {text_html}** "
            f"[{outlet}]({url})"
        )

        st.markdown(bullet, unsafe_allow_html=True)

    # Back button at bottom
    if st.button("⬅ Back to rankings", key="back_bottom"):
        set_player_param(None)
        st.rerun()


# ------------------------------------------------------------
# Main entry point
# ------------------------------------------------------------
def main() -> None:
    df_rumors = load_trade_rumors()
    df_scores = compute_player_scores(df_rumors)

    player_param = get_player_param()

    if player_param:
        show_player_view(df_rumors, player_param)
    else:
        show_rankings(df_scores)


if __name__ == "__main__":
    main()
