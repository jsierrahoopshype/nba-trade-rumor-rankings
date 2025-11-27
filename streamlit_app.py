import os
import re
from datetime import date, datetime, timedelta

import altair as alt
import pandas as pd
import streamlit as st

# ---------------------------------------------------------
# Page config
# ---------------------------------------------------------
st.set_page_config(
    page_title="NBA Trade Rumor Heat Index",
    layout="wide",
)

DATA_CANDIDATES = [
    "trade_rumors.csv",
    "/app/trade_rumors.csv",
    "/app/src/trade_rumors.csv",
]

# ---------------------------------------------------------
# Loading & cleaning
# ---------------------------------------------------------
def load_rumor_data() -> pd.DataFrame:
    """Load trade_rumors.csv from one of several possible locations."""
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

    # Normalize date -> date objects (no time / tz)
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    df = df.dropna(subset=["player", "slug", "date"])

    return df


# ---------------------------------------------------------
# Scoring: 0–7, 8–14, 15–28 days (relative to *today*)
# ---------------------------------------------------------
def compute_player_scores(df: pd.DataFrame) -> pd.DataFrame:
    """
    Count trade rumors per player in the last 28 days and compute
    weighted scores:

    - 1 pt per mention in last 7 days
    - 0.5 pts per mention 8–14 days ago
    - 0.25 pts per mention 15–28 days ago
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

    today = date.today()

    df = df.copy()
    df["days_ago"] = df["date"].apply(lambda d: (today - d).days)

    # Only keep rumors in the last 28 days
    df_28 = df[(df["days_ago"] >= 0) & (df["days_ago"] <= 28)].copy()
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

    mask_0_7 = df_28["days_ago"] <= 7
    mask_8_14 = (df_28["days_ago"] > 7) & (df_28["days_ago"] <= 14)
    mask_15_28 = (df_28["days_ago"] > 14) & (df_28["days_ago"] <= 28)

    by_slug_name = df_28[["slug", "player"]].drop_duplicates()
    name_by_slug = by_slug_name.set_index("slug")["player"].to_dict()

    counts_0_7 = (
        df_28[mask_0_7].groupby("slug").size().rename("mentions_0_7")
    )
    counts_8_14 = (
        df_28[mask_8_14].groupby("slug").size().rename("mentions_8_14")
    )
    counts_15_28 = (
        df_28[mask_15_28].groupby("slug").size().rename("mentions_15_28")
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


# ---------------------------------------------------------
# Utilities
# ---------------------------------------------------------
def clean_rumor_html(raw: str) -> str:
    """
    Clean up the snippet HTML from the CSV:

    - keep HoopsHype's highlighting / quoting
    - remove onclick / target so links open normally in the same tab
    """
    if not isinstance(raw, str):
        return ""

    html = raw
    html = re.sub(r'onclick="[^"]*"', "", html)
    html = re.sub(r'target="[^"]*"', "", html)
    return html


def render_rankings_table_html(df_display: pd.DataFrame) -> str:
    """Build an HTML table for the rankings (no tabulate needed)."""
    cols = [
        "Rank",
        "player",
        "slug",
        "Score",
        "Mentions_0_7",
        "Mentions_8_14",
        "Mentions_15_28",
    ]

    df_local = df_display[cols].copy()

    html = [
        '<table style="border-collapse: collapse; width: 100%;">',
        "<thead>",
        "<tr>",
        "<th style='text-align:left;'>Rank</th>",
        "<th style='text-align:left;'>Player</th>",
        "<th style='text-align:right;'>Score</th>",
        "<th style='text-align:right;'>Mentions (0–7d)</th>",
        "<th style='text-align:right;'>Mentions (8–14d)</th>",
        "<th style='text-align:right;'>Mentions (15–28d)</th>",
        "</tr>",
        "</thead>",
        "<tbody>",
    ]

    for _, row in df_local.iterrows():
        rank = int(row["Rank"])
        player = row["player"]
        slug = row["slug"]
        score = row["Score"]
        m_0_7 = row["Mentions_0_7"]
        m_8_14 = row["Mentions_8_14"]
        m_15_28 = row["Mentions_15_28"]

        html.append("<tr>")
        html.append(f"<td>{rank}</td>")
        html.append(
            "<td>"
            f"<a href='?player={slug}' target='_self'>{player}</a>"
            "</td>"
        )
        html.append(f"<td style='text-align:right;'>{score}</td>")
        html.append(f"<td style='text-align:right;'>{m_0_7}</td>")
        html.append(f"<td style='text-align:right;'>{m_8_14}</td>")
        html.append(f"<td style='text-align:right;'>{m_15_28}</td>")
        html.append("</tr>")

    html.append("</tbody></table>")
    return "\n".join(html)


def go_back_to_rankings():
    st.query_params.clear()
    st.rerun()


def format_day(d: date) -> str:
    return datetime(d.year, d.month, d.day).strftime("%b %-d")


# ---------------------------------------------------------
# Views
# ---------------------------------------------------------
def show_rankings(df_scores: pd.DataFrame):
    st.title("NBA Trade Rumor Heat Index")

    st.write(
        "Rankings based on how often players appear in trade rumors over the last "
        "28 days, with recent mentions weighted more heavily."
    )
    st.markdown(
        """
* **1 point** per mention in the last **7 days**
* **0.5 points** per mention **8–14 days** ago
* **0.25 points** per mention **15–28 days** ago
        """
    )

    # Search box
    search = st.text_input("Search for a player", "").strip().lower()

    # Jump directly to a player page
    if not df_scores.empty:
        jump_name = st.selectbox(
            "Jump to a player page",
            [""] + sorted(df_scores["player"].tolist()),
            index=0,
        )
        if jump_name:
            slug = df_scores.loc[
                df_scores["player"] == jump_name, "slug"
            ].iloc[0]
            st.query_params["player"] = slug
            st.rerun()

    if df_scores.empty:
        st.info("No trade-rumor data in the last 28 days.")
        return

    df_display = df_scores.copy()
    if search:
        df_display = df_display[
            df_display["player"].str.lower().str.contains(search)
        ]

    df_display = df_display.rename(
        columns={
            "score": "Score",
            "mentions_0_7": "Mentions_0_7",
            "mentions_8_14": "Mentions_8_14",
            "mentions_15_28": "Mentions_15_28",
        }
    )

    html_table = render_rankings_table_html(df_display)
    st.markdown(html_table, unsafe_allow_html=True)


def show_player_view(df: pd.DataFrame, player_slug: str):
    df_player = df[df["slug"] == player_slug].copy()

    if df_player.empty:
        st.warning("No rumors found for this player.")
        if st.button("← Back to rankings", key="back_empty"):
            go_back_to_rankings()
        return

    player_name = df_player["player"].iloc[0]

    # Back button at top
    col_back, _ = st.columns([1, 4])
    with col_back:
        if st.button("← Back to rankings", key="back_top"):
            go_back_to_rankings()

    st.header(f"{player_name} – Trade Rumor Activity")

    # ---- Chart: last 28 days only ----
    latest_date: date = max(df["date"].max(), df_player["date"].max())
    start_date = latest_date - timedelta(days=28)

    df_player_recent = df_player[df_player["date"] >= start_date].copy()

    # Daily counts, with explicit 0s
    full_index = pd.date_range(start_date, latest_date, freq="D")
    daily_counts = (
        df_player_recent.groupby("date")
        .size()
        .reindex([d.date() for d in full_index], fill_value=0)
    )

    chart_df = pd.DataFrame(
        {
            "day": full_index,
            "mentions": daily_counts.values,
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
                    format="%b %d",  # Month + number
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

    # ---- Most recent rumors (clean HTML) ----
    st.subheader("Most recent trade rumors")

    df_player_sorted = df_player.sort_values(
        "date", ascending=False
    ).head(25)

    for _, row in df_player_sorted.iterrows():
        rumor_date: date = row["date"]
        date_str = format_day(rumor_date)
        cleaned = clean_rumor_html(row.get("title", ""))
        st.markdown(
            f"- **{date_str}** – {cleaned}",
            unsafe_allow_html=True,
        )

    if st.button("← Back to rankings", key="back_bottom"):
        go_back_to_rankings()


# ---------------------------------------------------------
# Main
# ---------------------------------------------------------
def main():
    df_rumors = load_rumor_data()

    # st.query_params may return a list; normalize to a single string
    params = st.query_params
    player_param = params.get("player")
    if isinstance(player_param, list):
        player_param = player_param[0]

    if player_param:
        show_player_view(df_rumors, player_param)
    else:
        df_scores = compute_player_scores(df_rumors)
        show_rankings(df_scores)


if __name__ == "__main__":
    main()
