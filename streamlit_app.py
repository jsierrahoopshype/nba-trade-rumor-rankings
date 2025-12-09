"""
NBA Trade Rumor Rankings Dashboard
Shows players ranked by trade rumor mentions with weighted scoring.
"""

import streamlit as st
import pandas as pd
import altair as alt
import json
from datetime import datetime, timedelta

# Page config
st.set_page_config(
    page_title="NBA Trade Rumor Rankings",
    page_icon="🔥",
    layout="wide"
)

# Custom CSS
st.markdown("""
<style>
    .main-title {
        font-size: 2.2rem;
        font-weight: 700;
        color: #1a1a2e;
        margin-bottom: 0.2rem;
    }
    .subtitle {
        color: #666;
        font-size: 0.95rem;
        margin-bottom: 1.5rem;
    }
    .score-badge {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        padding: 0.3rem 0.8rem;
        border-radius: 20px;
        font-weight: 700;
        font-size: 1.1rem;
    }
    .rank-num {
        font-size: 1.8rem;
        font-weight: 700;
        color: #667eea;
    }
    .player-name {
        font-size: 1.2rem;
        font-weight: 600;
        color: #1a1a2e;
    }
    .metric-label {
        font-size: 0.75rem;
        color: #888;
        text-transform: uppercase;
    }
    .rumor-card {
        background: #f8f9fa;
        border-left: 3px solid #667eea;
        padding: 1rem;
        margin-bottom: 0.75rem;
        border-radius: 0 8px 8px 0;
    }
    .back-link {
        color: #667eea;
        text-decoration: none;
        font-weight: 500;
    }
    .scoring-info {
        background: #f0f4ff;
        padding: 0.75rem 1rem;
        border-radius: 8px;
        font-size: 0.85rem;
        color: #444;
    }
</style>
""", unsafe_allow_html=True)


# Load data
@st.cache_data
def load_data():
    try:
        with open("trade_rumor_data.json", "r") as f:
            data = json.load(f)
        return data
    except FileNotFoundError:
        return None


def create_player_slug(name: str) -> str:
    """Create URL-safe slug from player name."""
    return name.lower().replace(" ", "-").replace("'", "").replace(".", "")


def find_player_by_slug(rankings: list, slug: str) -> dict:
    """Find player data by slug."""
    for player in rankings:
        if create_player_slug(player["player"]) == slug:
            return player
    return None


def render_player_detail(data: dict, player_slug: str):
    """Render individual player detail page."""
    player_info = find_player_by_slug(data["rankings"], player_slug)
    
    if not player_info:
        st.error("Player not found")
        return
    
    player_name = player_info["player"]
    
    # Back button
    st.markdown(f"[← Back to Rankings](?)", unsafe_allow_html=True)
    st.markdown("")
    
    # Header
    col1, col2 = st.columns([3, 1])
    with col1:
        st.markdown(f"## #{player_info['rank']} {player_name}")
    with col2:
        st.markdown(f"<div style='text-align:right'><span class='score-badge'>{player_info['score']} pts</span></div>", unsafe_allow_html=True)
    
    # Stats row
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        st.metric("Total Mentions", player_info["total_mentions"])
    with c2:
        st.metric("Last 7 Days", player_info["mentions_week1"], help="1.0 pts each")
    with c3:
        st.metric("Days 8-14", player_info["mentions_week2"], help="0.5 pts each")
    with c4:
        st.metric("Days 15-28", player_info["mentions_weeks3_4"], help="0.25 pts each")
    with c5:
        last_mention = player_info.get("last_mention", "N/A")
        if last_mention and last_mention != "N/A":
            days_ago = (datetime.now().date() - datetime.fromisoformat(last_mention).date()).days
            st.metric("Last Mention", f"{days_ago}d ago" if days_ago > 0 else "Today")
        else:
            st.metric("Last Mention", "N/A")
    
    st.markdown("---")
    
    # Timeline chart
    st.markdown("### 📈 Daily Mentions")
    
    if player_name in data.get("daily_counts", {}):
        daily_data = data["daily_counts"][player_name]
        
        # Fill in missing dates with 0
        if daily_data:
            dates = sorted(daily_data.keys())
            start_date = datetime.fromisoformat(dates[0]).date()
            end_date = datetime.now().date()
            
            chart_data = []
            current = start_date
            while current <= end_date:
                date_str = current.isoformat()
                chart_data.append({
                    "date": date_str,
                    "mentions": daily_data.get(date_str, 0)
                })
                current += timedelta(days=1)
            
            df = pd.DataFrame(chart_data)
            df["date"] = pd.to_datetime(df["date"])
            
            chart = alt.Chart(df).mark_bar(
                color="#667eea",
                cornerRadiusTopLeft=3,
                cornerRadiusTopRight=3
            ).encode(
                x=alt.X("date:T", title="Date", axis=alt.Axis(format="%b %d")),
                y=alt.Y("mentions:Q", title="Mentions"),
                tooltip=[
                    alt.Tooltip("date:T", title="Date", format="%B %d, %Y"),
                    alt.Tooltip("mentions:Q", title="Mentions")
                ]
            ).properties(height=200)
            
            st.altair_chart(chart, use_container_width=True)
    else:
        st.info("No timeline data available")
    
    # Recent rumors
    st.markdown("### 📰 Trade Rumors")
    
    player_rumors = data.get("player_rumors", {}).get(player_name, [])
    
    if player_rumors:
        for rumor in player_rumors[:20]:  # Show last 20
            date_str = datetime.fromisoformat(rumor["date"]).strftime("%B %d, %Y")
            outlet = rumor.get("outlet", "Unknown")
            
            with st.expander(f"📅 {date_str} — {outlet}"):
                st.markdown(rumor.get("text", ""))
                if rumor.get("source_url"):
                    st.markdown(f"[Read source →]({rumor['source_url']})")
    else:
        st.info("No rumors found for this player")


def render_rankings(data: dict):
    """Render main rankings page."""
    
    st.markdown('<h1 class="main-title">🔥 NBA Trade Rumor Rankings</h1>', unsafe_allow_html=True)
    st.markdown('<p class="subtitle">Players ranked by trade rumor frequency with recency weighting</p>', unsafe_allow_html=True)
    
    # Scoring explanation
    st.markdown("""
    <div class="scoring-info">
        <strong>Scoring:</strong> 1 pt per mention (last 7 days) • 0.5 pts (days 8-14) • 0.25 pts (days 15-28)
    </div>
    """, unsafe_allow_html=True)
    st.markdown("")
    
    # Summary metrics
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Rumors", data.get("total_rumors", 0))
    with col2:
        st.metric("Players Tracked", data.get("total_players", 0))
    with col3:
        st.metric("Days Analyzed", data.get("scrape_window_days", 28))
    with col4:
        generated = data.get("generated_at", "")
        if generated:
            gen_dt = datetime.fromisoformat(generated)
            st.metric("Last Updated", gen_dt.strftime("%b %d, %H:%M"))
        else:
            st.metric("Last Updated", "N/A")
    
    st.markdown("---")
    
    # Search box
    search = st.text_input("🔍 Search for a player", placeholder="e.g. Jimmy Butler")
    
    rankings = data.get("rankings", [])
    
    if search:
        search_lower = search.lower()
        rankings = [r for r in rankings if search_lower in r["player"].lower()]
        if not rankings:
            st.warning(f"No players found matching '{search}'")
            return
    
    # Display rankings
    st.markdown("### 🏀 Rankings")
    
    # View mode toggle
    view_mode = st.radio("View", ["Cards", "Table"], horizontal=True, label_visibility="collapsed")
    
    if view_mode == "Cards":
        for player in rankings[:50]:  # Top 50
            col_rank, col_info, col_stats = st.columns([1, 4, 2])
            
            with col_rank:
                st.markdown(f"<div class='rank-num'>#{player['rank']}</div>", unsafe_allow_html=True)
            
            with col_info:
                slug = create_player_slug(player["player"])
                st.markdown(f"**[{player['player']}](?player={slug})**")
                
                # Show mention breakdown
                breakdown = f"7d: {player['mentions_week1']} • 14d: {player['mentions_week2']} • 28d: {player['mentions_weeks3_4']}"
                st.caption(breakdown)
            
            with col_stats:
                st.markdown(f"<span class='score-badge'>{player['score']} pts</span>", unsafe_allow_html=True)
                
                # Days since last mention
                last = player.get("last_mention")
                if last:
                    days_ago = (datetime.now().date() - datetime.fromisoformat(last).date()).days
                    recency = "Today" if days_ago == 0 else f"{days_ago}d ago"
                    st.caption(f"Last: {recency}")
            
            st.markdown("---")
    
    else:
        # Table view
        df = pd.DataFrame(rankings[:100])
        df = df[["rank", "player", "score", "mentions_week1", "mentions_week2", "mentions_weeks3_4", "total_mentions"]]
        df.columns = ["Rank", "Player", "Score", "7 Days", "8-14 Days", "15-28 Days", "Total"]
        
        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Rank": st.column_config.NumberColumn(width="small"),
                "Player": st.column_config.TextColumn(width="medium"),
                "Score": st.column_config.NumberColumn(format="%.2f", width="small"),
            }
        )
    
    # Footer
    st.markdown("---")
    st.caption("Data from HoopsHype trade rumors. Updated multiple times daily.")


def main():
    # Load data
    data = load_data()
    
    if not data:
        st.error("❌ No data found. Please run the scraper first.")
        st.code("python scrape_trade_rankings.py", language="bash")
        return
    
    # Check for player parameter
    query_params = st.query_params
    player_slug = query_params.get("player", None)
    
    if player_slug:
        render_player_detail(data, player_slug)
    else:
        render_rankings(data)


if __name__ == "__main__":
    main()
