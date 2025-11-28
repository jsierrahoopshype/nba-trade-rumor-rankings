import math
from datetime import datetime, timedelta
from urllib.parse import quote

import altair as alt
import pandas as pd
import streamlit as st


DATA_CSV = "trade_rumors.csv"
WINDOW_DAYS = 28  # how far back we look for both rankings & player page


# -------------- Data loading & cleaning -------------- #

@st.cache_data
def load_data(csv_path: str) -> pd.DataFrame:
    df = pd.read_csv(csv_path)

    # Basic column sanity check (NO slug required)
    expected = {"date", "player", "team", "source", "snippet", "url", "title"}
    missing = expected - set(df.columns)
    if missing:
        st.error(f"The CSV is missing some expected columns: {', '.join(sorted(missing))}")
        st.stop()

    # Parse date as date (not datetime)
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date

    # Drop invalid dates
    df = df.dropna(subset=["date"])

    # Clean player field
    df["player"] = df["player"].astype(str)

    # Treat "nan", "NaN", empty, etc. as missing
    df["player"] = df["player"].apply(lambda x: x.strip() if isinstance(x, str) else x)
    df.loc[df["player"].str.lower().isin(["nan", "none", ""]), "player"] = None

    # Drop rows with no real player or placeholder "PLAYER"
    df = df.dropna(subset=["player"])
    df = df[df["player"].str.upper() != "PLAYER"]

    # Clean team/source just in case
    df["team"] = df["team"].fillna("").astype(str)
    df["source"] = df["source"].fillna("").astype(str)

    return df


# -------------- Scoring logic -------------- #

def compute_player_scores(df: pd.DataFrame, window_days: int = WINDOW_DAYS) -> pd.DataFrame:
    """Compute weighted scores per player for the last `window_days` days."""
    if df.empty:
        return pd.DataFrame()

    today = datetime.today().date()
    cutoff = today - timedelta(days=window_days - 1)

    df_recent = df[df["date"] >= cutoff].copy()
    if df_recent.empty:
        return pd.DataFrame()

    # Days ago
    df_recent["days_ago"] = df_recent["date"].apply(lambda d: (today - d).days)

    # Weight buckets:
    # 0–7 days: 1.0
    # 8–14 days: 0.5
    # 15–28 days: 0.25
    def weight_for_days(days: int) -> float:
        if days <= 7:
            return 1.0
        elif days <= 14:
            return 0.5
        elif days <= 28:
            return 0.25
        return 0.0

    df_recent["weight"] = df_recent["days_ago"].apply(weight_for_days)
    df_recent["w_7"] = (df_recent["days_ago"] <= 7).astype(float)
    df_recent["w_8_14"] = (
        (df_recent["days_ago"] >= 8) & (df_recent["days_ago"] <= 14)
    ).astype(float)
    df_recent["w_15_28"] = (
        (df_recent["days_ago"] >= 15) & (df_recent["days_ago"] <= 28)
    ).astype(float)

    # Aggregate per player
    agg = df_recent.groupby("player").agg(
        score_7=("w_7", "sum"),
        score_8_14=("w_8_14", "sum"),
        score_15_28=("w_15_28", "sum"),
        mentions=("player", "size"),
    )

    agg["weighted_score"] = (
        agg["score_7"] * 1.0 + agg["score_8_14"] * 0.5 + agg["score_15_28"] * 0.25
    )

    # Attach a primary team (most frequent team in window)
    def primary_team(series: pd.Series) -> str:
        series = series[series != ""]
        if series.empty:
            return ""
        mode = series.mode()
        return mode.iloc[0] if not mode.empty else series.iloc[0]

    teams = df_recent.groupby("player")["team"].agg(primary_team)

    result = agg.join(teams.rename("team")).reset_index()
    result = result.sort_values(
        ["weighted_score", "mentions", "player"], ascending=[False, False, True]
    )

    # Round scores for display
    result["weighted_score"] = result["weighted_score"].round(2)
    return result


# -------------- UI helpers -------------- #

def make_player_link(name: str) -> str:
    """Markdown link that keeps navigation inside the app via ?player=..."""
    return f'<a href="?player={quote(name)}">{name}</a>'


def format_date(d: datetime.date) -> str:
    return d.strftime("%b %-d") if hasattr(d, "strftime") else str(d)


# -------------- Rankings view -------------- #

def show_rankings(df: pd.DataFrame):
    st.title("NBA Trade Rumor Rankings")

    last_date = df["date"].max()
    today = datetime.today().date()
    cutoff = today - timedelta(days=WINDOW_DAYS - 1)

    st.caption(
        f"Based on trade rumors from the last **{WINDOW_DAYS} days** "
        f"({cutoff:%b %-d} – {today:%b %-d}).\n\n"
        f"Data last updated: **{last_date:%b %-d, %Y}**."
    )

    df_scores = compute_player_scores(df)
    if df_scores.empty:
        st.warning("No trade rumors available for the last 28 days.")
        return

    # Search box to jump to a player page
    all_players = sorted(df_scores["player"].unique())
    search = st.text_input("Jump to a player page (type a name):")

    if search:
        matches = [p for p in all_players if search.lower() in p.lower()]
        if matches:
            st.write("Matches:")
            for m in matches[:10]:
                st.markdown(f"- {make_player_link(m)}", unsafe_allow_html=True)
        else:
            st.write("No players found matching that search.")

    st.subheader("Top trade-rumor targets (last 28 days)")

    # Build an HTML table with clickable player names
    top = df_scores.copy()
    top["rank"] = range(1, len(top) + 1)

    # Reorder & rename columns for display
    display_cols = ["rank", "player", "team", "weighted_score", "mentions",
                    "score_7", "score_8_14", "score_15_28"]
    top = top[display_cols]

    # HTML table
    headers = [
        "Rank",
        "Player",
        "Team",
        "Score",
        "Mentions (28d)",
        "Last 7d",
        "Days 8–14",
        "Days 15–28",
    ]

    rows_html = []
    for _, row in top.iterrows():
        player_html = make_player_link(row["player"])
        rows_html.append(
            "<tr>"
            f"<td>{int(row['rank'])}</td>"
            f"<td>{player_html}</td>"
            f"<td>{row['team']}</td>"
            f"<td>{row['weighted_score']}</td>"
            f"<td>{int(row['mentions'])}</td>"
            f"<td>{int(row['score_7'])}</td>"
            f"<td>{int(row['score_8_14'])}</td>"
            f"<td>{int(row['score_15_28'])}</td>"
            "</tr>"
        )

    table_html = """
    <style>
    table.trade-table {
        border-collapse: collapse;
        width: 100%;
        font-size: 0.95rem;
    }
    table.trade-table th, table.trade-table td {
        border: 1px solid #ddd;
        padding: 0.4rem 0.6rem;
        text-align: left;
        white-space: nowrap;
    }
    table.trade-table th {
        background-color: #f5f5f5;
        font-weight: 600;
    }
    table.trade-table tr:nth-child(even) {
        background-color: #fafafa;
    }
    table.trade-table a {
        text-decoration: none;
        color: #0a6cff;
    }
    table.trade-table a:hover {
        text-decoration: underline;
    }
    </style>
    <table class="trade-table">
        <thead>
            <tr>{header_cells}</tr>
        </thead>
        <tbody>
            {rows}
        </tbody>
    </table>
    """.format(
        header_cells="".join(f"<th>{h}</th>" for h in headers),
        rows="".join(rows_html),
    )

    st.markdown(table_html, unsafe_allow_html=True)


# -------------- Player view -------------- #

def show_player_view(df: pd.DataFrame, player_name: str):
    today = datetime.today().date()
    cutoff = today - timedelta(days=WINDOW_DAYS - 1)

    df_player = df[df["player"] == player_name].copy()
    df_recent = df_player[df_player["date"] >= cutoff].copy()

    st.markdown("[← Back to rankings](./)")

    st.title(player_name)

    if df_recent.empty:
        st.info(
            f"No trade rumors for **{player_name}** in the last {WINDOW_DAYS} days."
        )
        return

    st.caption(
        f"Showing rumors for the last **{WINDOW_DAYS} days** "
        f"({cutoff:%b %-d} – {today:%b %-d})."
    )

    # Summary stats
    score_df = compute_player_scores(df)
    this_row = score_df[score_df["player"] == player_name]
    if not this_row.empty:
        row = this_row.iloc[0]
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Score (28d)", f"{row['weighted_score']:.2f}")
        with col2:
            st.metric("Mentions (28d)", int(row["mentions"]))
        with col3:
            st.metric(
                "Last 7 days",
                f"{int(row['score_7'])}",
                help="Number of rumors in the last 7 days (unweighted count).",
            )

    # Mentions per day chart (last 28 days, including zeros)
    date_range = pd.date_range(cutoff, today, freq="D").date
    counts = (
        df_recent.groupby("date")["url"]
        .count()
        .reindex(date_range, fill_value=0)
        .reset_index()
    )
    counts.columns = ["date", "mentions"]

    st.subheader("Mentions per day (last 28 days)")

    chart = (
        alt.Chart(pd.DataFrame(counts))
        .mark_line(point=True)
        .encode(
            x=alt.X("date:T", axis=alt.Axis(format="%b %d", title="Date")),
            y=alt.Y("mentions:Q", title="Rumors"),
            tooltip=["date:T", "mentions:Q"],
        )
        .properties(height=260)
    )

    st.altair_chart(chart, use_container_width=True)

    # Recent rumors list (ONLY snippet is linked)
    st.subheader("Most recent rumors")

    df_recent_sorted = df_recent.sort_values(["date"], ascending=False)

    for _, row in df_recent_sorted.iterrows():
        date_str = row["date"].strftime("%b %-d")
        source = row["source"] or "Unknown source"
        snippet = row["snippet"]
        url = row["url"]

        # Only the snippet text is hyperlinked
        line = f"**{date_str} – {source}**: "
        if isinstance(url, str) and url.strip():
            line += f"[{snippet}]({url})"
        else:
            line += snippet

        st.markdown(f"- {line}")

    st.markdown("[← Back to rankings](./)")


# -------------- Main app -------------- #

def main():
    st.set_page_config(
        page_title="NBA Trade Rumor Rankings",
        layout="wide",
    )

    df = load_data(DATA_CSV)

    # Look for ?player=Name in the URL
    qparams = st.query_params
    player_param = None
    if "player" in qparams:
        # Depending on Streamlit version, this might be a list or a string
        val = qparams["player"]
        if isinstance(val, list):
            player_param = val[0]
        else:
            player_param = val

    if player_param:
        show_player_view(df, player_param)
    else:
        show_rankings(df)


if __name__ == "__main__":
    main()
