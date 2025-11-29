import datetime as dt

import altair as alt
import pandas as pd
import streamlit as st


# -----------------------------
# Basic config & styling
# -----------------------------


WINDOW_DAYS = 28  # rolling window for rankings


def style_app() -> None:
    """Inject CSS to style the app + rankings table."""
    st.markdown(
        """
        <style>
        /* Overall layout */
        .main > div {
            padding-top: 1.5rem;
        }

        /* Rankings table wrapper */
        .table-wrapper {
            margin-top: 1rem;
            border-radius: 8px;
            overflow: hidden;
            border: 1px solid #e5e7eb;
            box-shadow: 0 4px 10px rgba(15, 23, 42, 0.04);
        }

        table.ranking-table {
            width: 100%;
            border-collapse: collapse;
            font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI",
                         sans-serif;
            font-size: 0.9rem;
            background: #ffffff;
        }

        table.ranking-table thead tr {
            background: #f9fafb;
        }

        table.ranking-table th {
            text-align: left;
            font-weight: 600;
            padding: 0.75rem 0.9rem;
            border-bottom: 1px solid #e5e7eb;
            color: #4b5563;
            font-size: 0.8rem;
            text-transform: uppercase;
            letter-spacing: 0.03em;
        }

        table.ranking-table td {
            padding: 0.65rem 0.9rem;
            border-bottom: 1px solid #f1f5f9;
            color: #111827;
            vertical-align: middle;
        }

        table.ranking-table tr:nth-child(even) {
            background: #fafafa;
        }

        table.ranking-table tr:hover {
            background: #f3f4ff;
        }

        td.rank-cell {
            width: 44px;
            text-align: right;
            font-weight: 600;
            color: #6b7280;
        }

        td.logo-cell {
            width: 42px;
        }

        .logo-img {
            height: 26px;
            width: 26px;
            object-fit: contain;
            border-radius: 50%;
            display: block;
        }

        td.player-cell {
            font-weight: 500;
            color: #1f2933;
            white-space: nowrap;
        }

        td.score-cell {
            font-weight: 600;
        }

        .metric-sub {
            font-size: 0.8rem;
            color: #6b7280;
        }

        /* "Back to rankings" button */
        .back-btn {
            margin-bottom: 0.75rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


# -----------------------------
# Team logo mapping
# -----------------------------
# NOTE:
# - You can extend or change this dict at any time.
# - Keys are *player names exactly as they appear in the CSV*.
# - Values are logo URLs (these use ESPN's generic scoreboard logos).
# - If a player is missing here, the app will simply show an empty logo cell.

TEAM_LOGOS = {
    "Nikola Jokic": "https://a.espncdn.com/i/teamlogos/nba/500/scoreboard/den.png",
    "LeBron James": "https://a.espncdn.com/i/teamlogos/nba/500/scoreboard/lal.png",
    "Anthony Davis": "https://a.espncdn.com/i/teamlogos/nba/500/scoreboard/lal.png",
    "Shai Gilgeous-Alexander": "https://a.espncdn.com/i/teamlogos/nba/500/scoreboard/okc.png",
    "Luka Doncic": "https://a.espncdn.com/i/teamlogos/nba/500/scoreboard/dal.png",
    "Tyrese Maxey": "https://a.espncdn.com/i/teamlogos/nba/500/scoreboard/phi.png",
    "Austin Reaves": "https://a.espncdn.com/i/teamlogos/nba/500/scoreboard/lal.png",
    "Donovan Mitchell": "https://a.espncdn.com/i/teamlogos/nba/500/scoreboard/cle.png",
    "Cade Cunningham": "https://a.espncdn.com/i/teamlogos/nba/500/scoreboard/det.png",
    "Giannis Antetokounmpo": "https://a.espncdn.com/i/teamlogos/nba/500/scoreboard/mil.png",
    "Jaylen Brown": "https://a.espncdn.com/i/teamlogos/nba/500/scoreboard/bos.png",
    "Julius Randle": "https://a.espncdn.com/i/teamlogos/nba/500/scoreboard/ny.png",
    "Karl-Anthony Towns": "https://a.espncdn.com/i/teamlogos/nba/500/scoreboard/min.png",
    "Jalen Brunson": "https://a.espncdn.com/i/teamlogos/nba/500/scoreboard/ny.png",
    "James Harden": "https://a.espncdn.com/i/teamlogos/nba/500/scoreboard/lac.png",
    "Jamal Murray": "https://a.espncdn.com/i/teamlogos/nba/500/scoreboard/den.png",
    "Scottie Barnes": "https://a.espncdn.com/i/teamlogos/nba/500/scoreboard/tor.png",
    "Franz Wagner": "https://a.espncdn.com/i/teamlogos/nba/500/scoreboard/orl.png",
    "Devin Booker": "https://a.espncdn.com/i/teamlogos/nba/500/scoreboard/phx.png",
    # Add more players here as needed...
}


# -----------------------------
# Data loading & scoring
# -----------------------------


def load_rumors() -> pd.DataFrame:
    df = pd.read_csv("trade_rumors.csv")

    # Normalise column names if needed
    df.columns = [c.strip().lower() for c in df.columns]

    # Basic required columns
    required_cols = {"date", "player"}
    missing = required_cols - set(df.columns)
    if missing:
        raise ValueError(f"CSV is missing required columns: {', '.join(sorted(missing))}")

    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    df["player"] = df["player"].astype(str).str.strip()

    # Optional columns (fall back safely if missing)
    for col in ["media", "highlight_html", "quote_html"]:
        if col not in df.columns:
            df[col] = ""

    # Normalise a couple of well-known player-name edge cases
    df["player"] = (
        df["player"]
        .replace(
            {
                "Lebron James": "LeBron James",
                "Karl-anthony Towns": "Karl-Anthony Towns",
            }
        )
        .str.strip()
    )

    return df


def compute_player_scores(df: pd.DataFrame, window_days: int = WINDOW_DAYS):
    """Return (scores_df, df_window, window_start, window_end)."""

    if df.empty:
        return (
            pd.DataFrame(
                columns=[
                    "Rank",
                    "Player",
                    "Score",
                    "Mentions (0–7d)",
                    "Mentions (8–14d)",
                    "Mentions (15–28d)",
                ]
            ),
            df.copy(),
            None,
            None,
        )

    # Use most recent rumor date as window end
    window_end = df["date"].max().normalize()
    window_start = window_end - dt.timedelta(days=window_days - 1)

    df_window = df[(df["date"] >= window_start) & (df["date"] <= window_end)].copy()

    # Age in days relative to window_end
    df_window["age_days"] = (window_end - df_window["date"]).dt.days

    recent_mask = df_window["age_days"] <= 6          # last 7 days
    mid_mask = (df_window["age_days"] >= 7) & (df_window["age_days"] <= 13)
    old_mask = (df_window["age_days"] >= 14) & (df_window["age_days"] <= 27)

    recent_counts = (
        df_window[recent_mask].groupby("player").size().rename("Mentions (0–7d)")
    )
    mid_counts = (
        df_window[mid_mask].groupby("player").size().rename("Mentions (8–14d)")
    )
    old_counts = (
        df_window[old_mask].groupby("player").size().rename("Mentions (15–28d)")
    )

    scores = (
        pd.concat([recent_counts, mid_counts, old_counts], axis=1)
        .fillna(0)
        .reset_index()
    )

    scores["Score"] = (
        scores["Mentions (0–7d)"]
        + 0.5 * scores["Mentions (8–14d)"]
        + 0.25 * scores["Mentions (15–28d)"]
    )

    # Sort and add rank
    scores = scores.sort_values(["Score", "Mentions (0–7d)", "player"], ascending=[False, False, True])  # type: ignore[arg-type]
    scores["Rank"] = range(1, len(scores) + 1)

    # Reorder columns for display
    scores = scores[
        [
            "Rank",
            "player",
            "Score",
            "Mentions (0–7d)",
            "Mentions (8–14d)",
            "Mentions (15–28d)",
        ]
    ].rename(columns={"player": "Player"})

    return scores, df_window, window_start, window_end


# -----------------------------
# UI pieces
# -----------------------------


def show_rankings(df_scores: pd.DataFrame) -> None:
    st.subheader("Top trade-rumor targets (last 28 days)")

    if df_scores.empty:
        st.info("No trade-rumor data available for the current window.")
        return

    # Search + jump
    col_search, col_jump = st.columns([2, 2])

    with col_search:
        search = st.text_input("Search for a player", "")

    if search:
        filtered = df_scores[
            df_scores["Player"].str.contains(search, case=False, na=False)
        ]
    else:
        filtered = df_scores

    with col_jump:
        player_list = ["(select a player)"] + filtered["Player"].tolist()
        choice = st.selectbox("Jump to a player page", player_list, index=0)
        if choice != "(select a player)":
            st.session_state["mode"] = "player"
            st.session_state["player"] = choice
            st.experimental_rerun()

    # Build HTML table with logo column
    headers = [
        "Rank",
        "",  # logo
        "Player",
        "Score",
        "Mentions (0–7d)",
        "Mentions (8–14d)",
        "Mentions (15–28d)",
    ]

    rows_html = []
    for row in filtered.itertuples(index=False):
        rank = row.Rank
        player = row.Player
        score = row.Score
        m0 = row._4  # Mentions (0–7d)
        m1 = row._5  # Mentions (8–14d)
        m2 = row._6  # Mentions (15–28d)

        logo_url = TEAM_LOGOS.get(player, "")
        if logo_url:
            logo_html = f'<img src="{logo_url}" class="logo-img" alt="">'
        else:
            logo_html = ""

        rows_html.append(
            f"""
            <tr>
                <td class="rank-cell">{rank}</td>
                <td class="logo-cell">{logo_html}</td>
                <td class="player-cell">{player}</td>
                <td class="score-cell">{score:.2f}</td>
                <td>{int(m0)}</td>
                <td>{int(m1)}</td>
                <td>{int(m2)}</td>
            </tr>
            """
        )

    table_html = f"""
        <div class="table-wrapper">
        <table class="ranking-table">
            <thead>
                <tr>
                    <th>{headers[0]}</th>
                    <th>{headers[1]}</th>
                    <th>{headers[2]}</th>
                    <th>{headers[3]}</th>
                    <th>{headers[4]}</th>
                    <th>{headers[5]}</th>
                    <th>{headers[6]}</th>
                </tr>
            </thead>
            <tbody>
                {''.join(rows_html)}
            </tbody>
        </table>
        </div>
    """
    st.markdown(table_html, unsafe_allow_html=True)


def show_player_view(
    df_window: pd.DataFrame,
    player: str,
    window_start: dt.date,
    window_end: dt.date,
) -> None:
    """Per-player page: sparkline + list of recent rumors."""

    # Back button – stays in same window
    if st.button("← Back to rankings", key="back_btn"):
        st.session_state["mode"] = "rankings"
        st.session_state["player"] = None
        st.experimental_rerun()

    st.markdown(f"## {player} – Trade Rumor Activity")

    if df_window.empty:
        st.info("No trade-rumor data for this player in the current window.")
        return

    df_p = df_window[df_window["player"] == player].copy()
    if df_p.empty:
        st.info("No trade-rumor data for this player in the current window.")
        return

    # Daily mentions chart (only within 28-day window)
    all_days = pd.date_range(window_start, window_end, freq="D")
    daily = (
        df_p.groupby("date")
        .size()
        .reindex(all_days, fill_value=0)
        .reset_index()
        .rename(columns={"index": "day", 0: "mentions"})
    )
    daily.columns = ["day", "mentions"]

    chart = (
        alt.Chart(daily)
        .mark_line(point=True, interpolate="monotone")
        .encode(
            x=alt.X("day:T", title="Date"),
            y=alt.Y("mentions:Q", title="Mentions per day", scale=alt.Scale(nice=True)),
            tooltip=["day:T", "mentions:Q"],
        )
        .properties(height=260)
    )

    st.altair_chart(chart, use_container_width=True)

    # Recent rumors list
    st.markdown("### Most recent trade rumors")

    df_p = df_p.sort_values("date", ascending=False)

    for _, row in df_p.iterrows():
        date_str = row["date"].strftime("%b %-d")
        outlet = str(row.get("media") or "").strip()

        # Prefer highlighted_html, then quote_html, then empty
        body_html = str(row.get("highlight_html") or "").strip()
        if not body_html:
            body_html = str(row.get("quote_html") or "").strip()

        if not body_html:
            # Nothing meaningful to show; skip
            continue

        bullet = f"**{date_str} – {outlet}** – {body_html}"
        st.markdown(f"- {bullet}", unsafe_allow_html=True)


# -----------------------------
# Main
# -----------------------------


def main():
    st.set_page_config(
        page_title="NBA Trade Rumor Rankings",
        layout="wide",
    )
    style_app()

    # Simple state machine for rankings vs player page
    if "mode" not in st.session_state:
        st.session_state["mode"] = "rankings"
        st.session_state["player"] = None

    df = load_rumors()
    df_scores, df_window, window_start, window_end = compute_player_scores(df)

    st.markdown(
        "<span style='font-size:2.1rem; font-weight:700;'>NBA "
        "<span style='background: #fef08a; padding:0 0.2rem;'>Trade</span> "
        "<span style='background: #fef08a; padding:0 0.2rem;'>Rumor</span> "
        "Rankings</span>",
        unsafe_allow_html=True,
    )

    if window_start is not None and window_end is not None:
        last_date = df["date"].max()
        st.caption(
            f"Based on trade rumors from the last {WINDOW_DAYS} days "
            f"({window_start:%b %-d} – {window_end:%b %-d}).  \n"
            f"Data last updated: {last_date:%b %-d, %Y} • "
            f"Window: {window_start:%b %-d} – {window_end:%b %-d}"
        )
    else:
        st.caption("No trade-rumor data available yet.")

    mode = st.session_state.get("mode", "rankings")

    if mode == "player" and st.session_state.get("player"):
        show_player_view(
            df_window,
            st.session_state["player"],
            window_start,
            window_end,
        )
    else:
        st.session_state["mode"] = "rankings"
        show_rankings(df_scores)


if __name__ == "__main__":
    main()
