import math
from datetime import datetime, timedelta
from typing import Tuple, Optional

import pandas as pd
import streamlit as st
import altair as alt
import html
import re
import streamlit.components.v1 as components

# -------------------------
# Config & constants
# -------------------------

st.set_page_config(
    page_title="NBA Trade Rumor Rankings",
    page_icon="🏀",
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


# -------------------------
# Utility functions
# -------------------------


def slugify(name: str) -> str:
    """
    Turn 'Anthony Davis' -> 'anthony-davis' etc.
    """
    if not isinstance(name, str):
        return ""
    name = name.strip()
    # Remove apostrophes and periods, replace non-alphanum with hyphen
    name = re.sub(r"[’']", "", name)
    name = re.sub(r"\.", "", name)
    name = re.sub(r"[^a-zA-Z0-9]+", "-", name)
    name = re.sub(r"-{2,}", "-", name)
    return name.strip("-").lower()


def apply_name_fixes(name: str) -> str:
    if not isinstance(name, str):
        return ""
    name = name.strip()
    return NAME_FIXES.get(name, name)


def get_window_bounds(df: pd.DataFrame) -> Tuple[datetime, datetime]:
    """
    Return (window_start, window_end) based on last date in the dataset.
    """
    if df.empty:
        today = datetime.utcnow().date()
        end = datetime(today.year, today.month, today.day)
    else:
        end = pd.to_datetime(df["date"]).max().normalize()
    start = end - timedelta(days=WINDOW_DAYS - 1)
    return start, end


def format_window_label(start: datetime, end: datetime) -> str:
    if start.year == end.year and start.month == end.month:
        return f"{start.strftime('%b %d')} – {end.strftime('%b %d')}"
    if start.year == end.year:
        return f"{start.strftime('%b %d')} – {end.strftime('%b %d')}"
    return f"{start.strftime('%b %d, %Y')} – {end.strftime('%b %d, %Y')}"


# -------------------------
# Data loading & cleaning
# -------------------------


@st.cache_data(show_spinner=False)
def load_data() -> pd.DataFrame:
    """
    Load trade_rumors.csv and normalize columns.
    Expected columns (best effort):
      - date
      - player
      - slug (optional)
      - source (optional)
      - url or link_url
      - headline/text/snippet/link_text (best effort)
    """
    df = pd.read_csv("trade_rumors.csv")

    if "date" not in df.columns:
        raise RuntimeError("trade_rumors.csv is missing a 'date' column.")

    # Normalize date to midnight timestamps
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()

    # Player column
    if "player" not in df.columns:
        for cand in ["name", "player_name"]:
            if cand in df.columns:
                df["player"] = df[cand]
                break
        else:
            df["player"] = ""

    df["player"] = df["player"].astype(str).str.strip()
    df["player"] = df["player"].replace(NAME_FIXES)

    # Filter out rows with empty or bogus players
    bad_vals = {"", "player", "nan", "none"}
    df = df[~df["player"].str.lower().isin(bad_vals)].copy()

    # Slug column
    if "slug" not in df.columns:
        df["slug"] = df["player"].map(slugify)
    else:
        df["slug"] = df["slug"].fillna("").astype(str)
        mask_empty = df["slug"].str.strip() == ""
        df.loc[mask_empty, "slug"] = df.loc[mask_empty, "player"].map(slugify)
        df["slug"] = df["slug"].str.lower()

    # Sort by date
    df = df.sort_values("date").reset_index(drop=True)
    return df


# -------------------------
# Scoring logic
# -------------------------


def compute_player_scores(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute weighted 'heat index' scores for each player over the last WINDOW_DAYS.
    Recent days are weighted more heavily:
      - 1.0 point per mention in the last 7 days
      - 0.5 points per mention 8–14 days ago
      - 0.25 points per mention 15–28 days ago
    """

    if df.empty:
        return pd.DataFrame(
            columns=[
                "player",
                "slug",
                "score",
                "mentions_recent",
                "mentions_mid",
                "mentions_old",
                "first_mention",
                "last_mention",
            ]
        )

    df = df.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()

    window_start, window_end = get_window_bounds(df)

    # Filter to rows in our rolling window
    df_window = df[(df["date"] >= window_start) & (df["date"] <= window_end)].copy()

    if df_window.empty:
        return pd.DataFrame(
            columns=[
                "player",
                "slug",
                "score",
                "mentions_recent",
                "mentions_mid",
                "mentions_old",
                "first_mention",
                "last_mention",
            ]
        )

    # How many days ago (0 = window_end, 1 = yesterday, etc.)
    df_window["days_ago"] = (window_end - df_window["date"]).dt.days

    # Buckets
    recent_mask = df_window["days_ago"] <= RECENT_DAYS_1 - 1
    mid_mask = (df_window["days_ago"] >= RECENT_DAYS_1) & (
        df_window["days_ago"] <= RECENT_DAYS_2 - 1
    )
    old_mask = (df_window["days_ago"] >= RECENT_DAYS_2) & (
        df_window["days_ago"] < WINDOW_DAYS
    )

    # Count mentions per player per bucket
    grp = df_window.groupby(["player", "slug"], dropna=False)

    recent_counts = grp.apply(lambda g: recent_mask[g.index].sum()).rename(
        "mentions_recent"
    )
    mid_counts = grp.apply(lambda g: mid_mask[g.index].sum()).rename("mentions_mid")
    old_counts = grp.apply(lambda g: old_mask[g.index].sum()).rename("mentions_old")

    mentions = pd.concat([recent_counts, mid_counts, old_counts], axis=1)

    # Weighted score
    mentions["score"] = (
        mentions["mentions_recent"] * 1.0
        + mentions["mentions_mid"] * 0.5
        + mentions["mentions_old"] * 0.25
    )

    # First / last mention dates within the window
    first_last = grp["date"].agg(["min", "max"]).rename(
        columns={"min": "first_mention", "max": "last_mention"}
    )

    out = mentions.join(first_last)

    # Sort by score desc, then last_mention desc, then name
    out = out.reset_index().sort_values(
        by=["score", "last_mention", "player"], ascending=[False, False, True]
    )

    # Some convenience columns
    out["mentions_total"] = (
        out["mentions_recent"] + out["mentions_mid"] + out["mentions_old"]
    )

    # Apply pretty name fixes for display
    out["player"] = out["player"].map(apply_name_fixes)

    return out


# -------------------------
# UI helpers
# -------------------------


def render_header(df: pd.DataFrame, window_start: datetime, window_end: datetime) -> None:
    st.markdown(
        "<h1 style='margin-bottom:0.25rem'>NBA "
        "<span style='background:#fff3b0'>Trade Rumor</span> Rankings</h1>",
        unsafe_allow_html=True,
    )
    window_label = format_window_label(window_start, window_end)

    last_date = df["date"].max().strftime("%b %d, %Y") if not df.empty else "N/A"

    st.markdown(
        f"<p style='color:#6b7280;margin:0.25rem 0 0.75rem 0;'>"
        f"Based on <strong>trade rumors</strong> from the last {WINDOW_DAYS} days "
        f"({window_label})."
        f"</p>",
        unsafe_allow_html=True,
    )
    st.markdown(
        f"<p style='color:#9ca3af;font-size:0.85rem;margin-bottom:1.25rem;'>"
        f"Data last updated: <strong>{last_date}</strong> • "
        f"Window: {window_label}"
        f"</p>",
        unsafe_allow_html=True,
    )


def show_rankings(df: pd.DataFrame, df_scores: pd.DataFrame) -> None:
    st.subheader(f"Top trade-rumor targets (last {WINDOW_DAYS} days)")

    if df_scores.empty:
        st.info("No trade rumors found in the current window.")
        return

    df_scores = df_scores.reset_index(drop=True)
    df_scores["rank"] = df_scores.index + 1

    rows_html = []
    for _, row in df_scores.iterrows():
        rank = int(row["rank"])
        player = html.escape(str(row["player"]))
        slug = html.escape(str(row["slug"]))
        score = row["score"]
        mentions = int(row["mentions_total"])

        rows_html.append(
            f"""
            <tr>
              <td class="rank">{rank}</td>
              <td class="player">
                <a href="#" class="hh-player-link" data-slug="{slug}">{player}</a>
              </td>
              <td class="score">{score:.2f}</td>
              <td class="mentions">{mentions}</td>
            </tr>
            """
        )

    table_html = f"""
    <html>
    <head>
      <style>
      body {{
        margin: 0;
        padding: 0;
        font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      }}
      .hh-table-wrapper {{
        margin-top: 8px;
        border-radius: 10px;
        overflow: hidden;
        box-shadow: 0 0 0 1px #e3e6ea;
        font-size: 14px;
      }}
      table.hh-table {{
        width: 100%;
        border-collapse: collapse;
      }}
      .hh-table thead {{
        background: #f8fafc;
      }}
      .hh-table th,
      .hh-table td {{
        padding: 9px 12px;
        text-align: left;
        border-bottom: 1px solid #e3e6ea;
      }}
      .hh-table tbody tr:nth-child(even) {{
        background: #fbfdff;
      }}
      .hh-table tbody tr:hover {{
        background: #eef5ff;
      }}
      .hh-table th.rank,
      .hh-table td.rank {{
        width: 32px;
        text-align: right;
        color: #6b7280;
        font-weight: 500;
      }}
      .hh-table th.score,
      .hh-table td.score,
      .hh-table th.mentions,
      .hh-table td.mentions {{
        text-align: right;
        white-space: nowrap;
      }}
      .hh-table td.player a {{
        color: #0059c9;
        text-decoration: none;
        font-weight: 500;
      }}
      .hh-table td.player a:hover {{
        text-decoration: underline;
      }}
      </style>
    </head>
    <body>
      <div class="hh-table-wrapper">
        <table class="hh-table">
          <thead>
            <tr>
              <th class="rank">#</th>
              <th>Player</th>
              <th class="score">RAT</th>
              <th class="mentions">Mentions (28d)</th>
            </tr>
          </thead>
          <tbody>
            {''.join(rows_html)}
          </tbody>
        </table>
      </div>

      <script>
      (function() {{
        const links = document.querySelectorAll('.hh-player-link');
        links.forEach(function(link) {{
          link.addEventListener('click', function(e) {{
            e.preventDefault();
            const slug = this.getAttribute('data-slug');
            if (!slug) return;

            // Update iframe URL (Streamlit query param)
            const qp = new URLSearchParams(window.location.search);
            qp.set('player', slug);
            window.location.search = qp.toString();

            // Inform parent page (Presto) for URL update / analytics
            try {{
              window.parent.postMessage({{
                type: 'hh_trade_player',
                playerSlug: slug
              }}, '*');
            }} catch (err) {{
              console.error('postMessage failed', err);
            }}
          }});
        }});
      }})();
      </script>
    </body>
    </html>
    """

    # Render full HTML + JS as a component so it isn't sanitized
    components.html(table_html, height=650, scrolling=True)


def get_player_timeseries(
    df: pd.DataFrame,
    slug: str,
    window_start: datetime,
    window_end: datetime,
) -> pd.DataFrame:
    df_p = df[
        (df["slug"] == slug)
        & (df["date"] >= window_start)
        & (df["date"] <= window_end)
    ].copy()
    if df_p.empty:
        dates = pd.date_range(window_start, window_end, freq="D")
        return pd.DataFrame({"date": dates, "mentions": [0] * len(dates)})

    counts = df_p.groupby("date").size()
    dates = pd.date_range(window_start, window_end, freq="D")
    counts = counts.reindex(dates, fill_value=0)
    out = pd.DataFrame({"date": dates, "mentions": counts.values})
    return out


def render_player_rumors(
    df: pd.DataFrame, slug: str, window_start: datetime, window_end: datetime
) -> None:
    df_p = df[
        (df["slug"] == slug)
        & (df["date"] >= window_start)
        & (df["date"] <= window_end)
    ].copy()
    if df_p.empty:
        st.info("No trade rumors for this player in the last 28 days.")
        return

    # Best-effort column choices
    url_col = (
        "link_url"
        if "link_url" in df_p.columns
        else "url"
        if "url" in df_p.columns
        else None
    )
    link_text_col = "link_text" if "link_text" in df_p.columns else None

    # Prefer "headline", then "text", then "snippet"
    text_col = None
    for cand in ["headline", "text", "snippet"]:
        if cand in df_p.columns:
            text_col = cand
            break
    if text_col is None:
        text_col = url_col  # fallback

    source_col = "source" if "source" in df_p.columns else None

    df_p = df_p.sort_values("date", ascending=False)

    for _, row in df_p.iterrows():
        d: datetime = row["date"]
        date_str = d.strftime("%b %d")
        src = f"{row[source_col]} " if source_col and pd.notna(row[source_col]) else ""
        body = (
            str(row[text_col]) if text_col and pd.notna(row[text_col]) else ""
        )
        link_url = row[url_col] if url_col and pd.notna(row[url_col]) else None
        link_text = (
            row[link_text_col] if link_text_col and pd.notna(row[link_text_col]) else ""
        )

        snippet_html = html.escape(body)

        if link_url:
            safe_url = html.escape(str(link_url))
            if link_text and link_text in body:
                escaped_link_text = html.escape(link_text)
                snippet_html = html.escape(body).replace(
                    escaped_link_text,
                    f'<a href="{safe_url}" target="_blank" rel="noopener noreferrer">{escaped_link_text}</a>',
                    1,
                )
            else:
                snippet_html = (
                    f'<a href="{safe_url}" target="_blank" '
                    f'rel="noopener noreferrer">{snippet_html}</a>'
                )

        st.markdown(
            f"<p style='margin-bottom:0.4rem;'><span style='font-weight:600;'>{date_str}</span>"
            f" · <span style='color:#6b7280;'>{html.escape(src)}</span><br>{snippet_html}</p>",
            unsafe_allow_html=True,
        )


def show_player_view(
    df: pd.DataFrame,
    df_scores: pd.DataFrame,
    player_slug: str,
    window_start: datetime,
    window_end: datetime,
) -> None:
    # Normalize slug comparison
    slug_lower = player_slug.lower()
    row = df_scores[df_scores["slug"].str.lower() == slug_lower]
    if row.empty:
        st.error("Unknown player.")
        return
    row = row.iloc[0]

    player_name = row["player"]
    score = row["score"]
    recent = int(row["mentions_recent"])
    mid = int(row["mentions_mid"])
    old = int(row["mentions_old"])
    total = int(row["mentions_total"])

    # Back button (same window)
    if st.button("← Back to rankings"):
        st.experimental_set_query_params()  # clear query string
        st.experimental_rerun()

    st.markdown(f"## {player_name}")

    # Metrics row
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Trade-rumor rating", f"{score:.2f}")
    col2.metric("Mentions (last 7 days)", recent)
    col3.metric("Mentions (8–14 days)", mid)
    col4.metric("Mentions (15–28 days)", old)

    st.markdown("---")

    # Chart
    ts = get_player_timeseries(df, row["slug"], window_start, window_end)
    chart = (
        alt.Chart(ts)
        .mark_area(line={"color": "#2563eb"}, opacity=0.18)
        .encode(
            x=alt.X("date:T", axis=alt.Axis(title=None)),
            y=alt.Y("mentions:Q", axis=alt.Axis(title="Rumor mentions")),
            tooltip=[
                alt.Tooltip("date:T", title="Date"),
                alt.Tooltip("mentions:Q", title="Mentions"),
            ],
        )
        .properties(height=260)
    )
    st.altair_chart(chart, use_container_width=True)

    st.markdown("### Recent trade rumors")
    render_player_rumors(df, row["slug"], window_start, window_end)


# -------------------------
# Main app
# -------------------------


def main() -> None:
    df = load_data()
    df_scores = compute_player_scores(df)
    window_start, window_end = get_window_bounds(df)

    render_header(df, window_start, window_end)

    if df_scores.empty:
        st.info("No trade rumors available yet.")
        return

    # ---- Player search / jump box (works in both views) ----
    player_options = df_scores["player"].tolist()
    slug_lookup = dict(zip(df_scores["player"], df_scores["slug"]))

    # Determine current selected slug from URL, if any
    params = st.query_params
    player_slug_param: Optional[str] = None
    if "player" in params:
        val = params["player"]
        if isinstance(val, list):
            player_slug_param = val[0]
        else:
            player_slug_param = val

    st.write("")  # spacing
    selected_name = st.selectbox(
        "Jump to a player page (type a name):",
        [""] + player_options,
        index=0,
    )

    if selected_name:
        slug = slug_lookup.get(selected_name)
        if slug:
            st.experimental_set_query_params(player=slug)
            show_player_view(df, df_scores, slug, window_start, window_end)
            return

    # If URL already has ?player=...
    if player_slug_param:
        slug = player_slug_param
        show_player_view(df, df_scores, slug, window_start, window_end)
        return

    # Otherwise show rankings
    show_rankings(df, df_scores)


if __name__ == "__main__":
    main()
