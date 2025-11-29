import streamlit as st
import pandas as pd
from datetime import timedelta
import re
import html

CSV_PATH = "trade_rumors.csv"
WINDOW_DAYS = 28  # show last 28 days

# Manual name fixes
NAME_FIXES = {
    "Lebron James": "LeBron James",
    "Karl-anthony Towns": "Karl-Anthony Towns",
}


# ---------- Utilities ----------

def slugify(name: str) -> str:
    name = name.strip().lower()
    name = re.sub(r"[^a-z0-9]+", "-", name)
    return name.strip("-")


def load_rumors():
    df = pd.read_csv(CSV_PATH, parse_dates=["date"])
    # Fix name capitalization issues just in case
    df["player"] = df["player"].replace(NAME_FIXES)
    # Keep only rows that actually have a player name
    df = df[df["player"].notna() & (df["player"].str.strip() != "")]
    return df


def restrict_to_window(df):
    if df.empty:
        return df, None, None
    max_date = df["date"].max().normalize()
    window_end = max_date
    window_start = max_date - timedelta(days=WINDOW_DAYS - 1)
    mask = (df["date"] >= window_start) & (df["date"] <= window_end)
    return df.loc[mask].copy(), window_start, window_end


def compute_scores(df_window):
    if df_window.empty:
        return pd.DataFrame()

    today = df_window["date"].max().normalize()
    df = df_window.copy()
    df["age_days"] = (today - df["date"].dt.normalize()).dt.days

    recent = df[df["age_days"] <= 6]
    mid = df[df["age_days"].between(7, 13)]
    old = df[df["age_days"].between(14, 27)]

    recent_counts = recent.groupby("player").size().rename("mentions_0_7")
    mid_counts = mid.groupby("player").size().rename("mentions_8_14")
    old_counts = old.groupby("player").size().rename("mentions_15_28")

    scores = (
        pd.concat([recent_counts, mid_counts, old_counts], axis=1)
        .fillna(0)
        .reset_index()
    )

    scores["score"] = (
        scores["mentions_0_7"]
        + 0.5 * scores["mentions_8_14"]
        + 0.25 * scores["mentions_15_28"]
    )

    scores = scores.sort_values(
        ["score", "mentions_0_7", "mentions_8_14", "mentions_15_28", "player"],
        ascending=[False, False, False, False, True],
    ).reset_index(drop=True)

    scores["rank"] = scores.index + 1
    scores["slug"] = scores["player"].apply(slugify)

    return scores


def format_date_range(start, end):
    if not start or not end:
        return "N/A"
    if start.month == end.month:
        return f"{start:%b} {start.day} – {end.day}"
    return f"{start:%b} {start.day} – {end:%b} {end.day}"


# ---------- HTML helpers ----------

def build_rankings_table(df_scores):
    if df_scores.empty:
        return "<p>No data available.</p>"

    headers = [
        "Rank",
        "Player",
        "Score",
        "Mentions (0–7d)",
        "Mentions (8–14d)",
        "Mentions (15–28d)",
    ]

    header_cells = "".join(f"<th>{html.escape(h)}</th>" for h in headers)

    rows_html = []
    for _, row in df_scores.iterrows():
        player_name = row["player"]
        slug = row["slug"]

        # IMPORTANT: Use relative URL and target="_self" so it does NOT open a new window
        player_link = (
            f'<a href="?player={slug}" target="_self">'
            f"{html.escape(player_name)}</a>"
        )

        cells = [
            str(int(row["rank"])),
            player_link,
            f"{row['score']:.2f}",
            str(int(row["mentions_0_7"])),
            str(int(row["mentions_8_14"])),
            str(int(row["mentions_15_28"])),
        ]
        row_html = "<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>"
        rows_html.append(row_html)

    table_html = f"""
    <table style="border-collapse: collapse; width: 100%;">
        <thead>
            <tr>{header_cells}</tr>
        </thead>
        <tbody>
            {''.join(rows_html)}
        </tbody>
    </table>
    """
    return table_html


def build_rumor_snippet_html(snippet: str, url: str, source: str | float):
    """
    Only hyperlink the quoted / highlighted part of the snippet (if present),
    plus the media outlet name. Everything else is plain text.
    """

    if not isinstance(snippet, str):
        snippet = ""
    if not isinstance(url, str):
        url = ""
    if not isinstance(source, str):
        source = ""

    text = snippet

    # Heuristic: if there are curly quotes, make the text inside them the clickable part
    start = end = None
    if "“" in text and "”" in text:
        start = text.index("“")
        end = text.rfind("”") + 1
    elif '"' in text:
        # Fallback: straight quotes
        first = text.find('"')
        last = text.rfind('"')
        if first != -1 and last > first:
            start = first
            end = last + 1

    if start is not None and end is not None:
        prefix = text[:start]
        highlight = text[start:end]
        suffix = text[end:]
    else:
        # If we can't find a highlighted region, just treat the whole
        # snippet as the highlight (same behaviour as before)
        prefix = ""
        highlight = text
        suffix = ""

    prefix_html = html.escape(prefix)
    highlight_html = html.escape(highlight)
    suffix_html = html.escape(suffix)

    if url:
        highlight_html = (
            f'<a href="{html.escape(url)}" target="_self" rel="nofollow">'
            f"{highlight_html}</a>"
        )

    result = prefix_html + highlight_html + suffix_html

    if source:
        source_html = html.escape(source)
        if url:
            source_html = (
                f'<a href="{html.escape(url)}" target="_self" rel="nofollow">'
                f"{source_html}</a>"
            )
        result += f" <strong>{source_html}</strong>"

    return result


# ---------- Views ----------

def show_header(df_window, window_start, window_end):
    st.markdown(
        "<h1 style='font-size: 2.5rem;'>NBA "
        "<span style='background: yellow;'>Trade</span> "
        "<span style='background: yellow;'>Rumor</span> Rankings</h1>",
        unsafe_allow_html=True,
    )

    date_range_str = format_date_range(window_start, window_end)
    last_updated = df_window["date"].max().strftime("%b %d, %Y") if not df_window.empty else "N/A"

    st.markdown(
        f"Based on <span style='background: yellow;'>trade rumors</span> "
        f"from the last {WINDOW_DAYS} days ({date_range_str}).",
        unsafe_allow_html=True,
    )
    st.caption(f"Data last updated: {last_updated}.")


def show_rankings(df_scores, df_window, window_start, window_end):
    show_header(df_window, window_start, window_end)

    # Jump-to-player select
    all_players = df_scores["player"].tolist()
    st.markdown("Jump to a player page (type a name):")
    selected = st.selectbox(
        "",
        [""] + all_players,
        index=0,
        label_visibility="collapsed",
    )
    if selected:
        slug = df_scores.loc[df_scores["player"] == selected, "slug"].iloc[0]
        st.experimental_set_query_params(player=slug)
        st.experimental_rerun()

    st.markdown(
        "<h2>Top <span style='background: yellow;'>trade-rumor</span> "
        f"targets (last {WINDOW_DAYS} days)</h2>",
        unsafe_allow_html=True,
    )

    table_html = build_rankings_table(df_scores)
    st.markdown(table_html, unsafe_allow_html=True)


def show_player_view(player_slug, df_window, df_scores, window_start, window_end):
    # Find player name from slug
    row = df_scores[df_scores["slug"] == player_slug]
    if row.empty:
        st.error("Unknown player.")
        return
    player_name = row["player"].iloc[0]

    # Back link
    if st.button("← Back to rankings"):
        st.experimental_set_query_params()
        st.experimental_rerun()

    st.markdown(
        f"<h2>{html.escape(player_name)} – Trade Rumor Activity</h2>",
        unsafe_allow_html=True,
    )

    # Filter rumors for this player
    player_rumors = df_window[df_window["player"] == player_name].copy()
    if player_rumors.empty:
        st.info("No trade rumors for this player in the last 28 days.")
        return

    # Mentions per day chart (only last 28 days)
    date_range = pd.date_range(window_start, window_end, freq="D")
    counts = (
        player_rumors.groupby(player_rumors["date"].dt.normalize)
        .size()
        .reindex(date_range, fill_value=0)
    )
    daily_df = counts.reset_index()
    daily_df.columns = ["day", "mentions"]

    st.subheader("Mentions per day")
    daily_df_chart = daily_df.set_index("day")
    st.line_chart(daily_df_chart)

    # Most recent rumors (limit)
    st.subheader("Most recent trade rumors")
    player_rumors = player_rumors.sort_values("date", ascending=False)

    items_html = []
    for _, r in player_rumors.head(40).iterrows():
        date_str = r["date"].strftime("%b %d")
        snippet_html = build_rumor_snippet_html(
            r.get("snippet", ""),
            r.get("url", ""),
            r.get("source", ""),
        )
        item_html = (
            f"<li><strong>{date_str}</strong> – {snippet_html}</li>"
        )
        items_html.append(item_html)

    list_html = "<ul>" + "".join(items_html) + "</ul>"
    st.markdown(list_html, unsafe_allow_html=True)


# ---------- Main ----------

def main():
    st.set_page_config(page_title="NBA Trade Rumor Rankings", layout="wide")

    df = load_rumors()
    df_window, window_start, window_end = restrict_to_window(df)
    df_scores = compute_scores(df_window)

    query_params = st.experimental_get_query_params()
    player_slug = None
    if "player" in query_params:
        vals = query_params.get("player")
        if isinstance(vals, list):
            player_slug = vals[0]
        else:
            player_slug = vals

    if player_slug:
        show_player_view(player_slug, df_window, df_scores, window_start, window_end)
    else:
        show_rankings(df_scores, df_window, window_start, window_end)


if __name__ == "__main__":
    main()
