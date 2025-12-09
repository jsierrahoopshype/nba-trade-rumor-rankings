import streamlit as st
import pandas as pd
import altair as alt
from datetime import datetime, timedelta

# Page config
st.set_page_config(
    page_title="NBA Trade Rumor Rankings",
    page_icon="🔥",
    layout="wide"
)

# Custom CSS for cleaner look
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: 700;
        color: #1a1a2e;
        margin-bottom: 0;
    }
    .sub-header {
        font-size: 1rem;
        color: #666;
        margin-top: 0;
        margin-bottom: 2rem;
    }
    .metric-card {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 1.5rem;
        border-radius: 12px;
        color: white;
        text-align: center;
    }
    .metric-value {
        font-size: 2.5rem;
        font-weight: 700;
    }
    .metric-label {
        font-size: 0.9rem;
        opacity: 0.9;
    }
    .player-card {
        background: #f8f9fa;
        border-left: 4px solid #667eea;
        padding: 1rem;
        margin-bottom: 0.5rem;
        border-radius: 0 8px 8px 0;
    }
    .rank-badge {
        background: #667eea;
        color: white;
        padding: 0.25rem 0.75rem;
        border-radius: 20px;
        font-weight: 600;
        font-size: 0.85rem;
    }
    .heat-high { color: #dc3545; font-weight: 700; }
    .heat-medium { color: #fd7e14; font-weight: 600; }
    .heat-low { color: #28a745; }
    div[data-testid="stExpander"] {
        background: #f8f9fa;
        border-radius: 8px;
        margin-bottom: 0.5rem;
    }
</style>
""", unsafe_allow_html=True)

# Load data
@st.cache_data
def load_data():
    df = pd.read_csv('trade_rumors.csv')
    df['date'] = pd.to_datetime(df['date'])
    
    # Filter out invalid player names (nan, empty, etc.)
    df = df[df['player'].notna()]
    df = df[df['player'].str.strip() != '']
    df = df[df['player'].str.lower() != 'nan']
    
    return df

try:
    df = load_data()
except FileNotFoundError:
    st.error("trade_rumors.csv not found. Please run the scraper first.")
    st.stop()

# Get query parameters
query_params = st.query_params
selected_player = query_params.get('player', None)

# Title
st.markdown('<h1 class="main-header">🔥 NBA Trade Rumor Rankings</h1>', unsafe_allow_html=True)
st.markdown('<p class="sub-header">Rankings based on trade rumor frequency over the past 28 days</p>', unsafe_allow_html=True)

# Summary metrics
col1, col2, col3, col4 = st.columns(4)

total_rumors = len(df)
unique_players = df['player'].nunique()
date_range = (df['date'].max() - df['date'].min()).days + 1
avg_per_day = total_rumors / max(date_range, 1)

with col1:
    st.metric("Total Rumors", f"{total_rumors:,}")
with col2:
    st.metric("Players Mentioned", unique_players)
with col3:
    st.metric("Days Tracked", date_range)
with col4:
    st.metric("Avg/Day", f"{avg_per_day:.1f}")

st.markdown("---")

# Aggregate by player
player_stats = df.groupby('player').agg({
    'date': ['min', 'max', 'count'],
    'source': lambda x: ', '.join(sorted(set(x.dropna().astype(str))))
}).reset_index()

player_stats.columns = ['player', 'first_mention', 'last_mention', 'total_mentions', 'sources']
player_stats['days_active'] = (player_stats['last_mention'] - player_stats['first_mention']).dt.days + 1
player_stats['mentions_per_day'] = player_stats['total_mentions'] / player_stats['days_active']

# Calculate "heat" score (weighted by recency)
today = pd.Timestamp.now().normalize()
player_stats['days_since_last'] = (today - player_stats['last_mention']).dt.days
player_stats['heat_score'] = player_stats['total_mentions'] * (1 / (player_stats['days_since_last'] + 1))
player_stats = player_stats.sort_values('total_mentions', ascending=False)

# Create player slug for URL
def create_slug(name):
    return name.lower().replace(' ', '-').replace("'", '').replace('.', '')

player_stats['slug'] = player_stats['player'].apply(create_slug)

# Add rank
player_stats = player_stats.reset_index(drop=True)
player_stats['rank'] = player_stats.index + 1

# If player selected, show details first
if selected_player:
    player_data = player_stats[player_stats['slug'] == selected_player]
    
    if not player_data.empty:
        player_name = player_data.iloc[0]['player']
        player_rank = int(player_data.iloc[0]['rank'])
        
        # Back button
        st.markdown(f"[← Back to Rankings](?)")
        
        st.markdown(f"## #{player_rank} {player_name}")
        
        # Filter rumors for this player
        player_rumors = df[df['player'] == player_name].sort_values('date', ascending=False)
        
        # Stats row
        pcol1, pcol2, pcol3, pcol4 = st.columns(4)
        with pcol1:
            st.metric("Total Mentions", int(player_data.iloc[0]['total_mentions']))
        with pcol2:
            st.metric("Days Active", int(player_data.iloc[0]['days_active']))
        with pcol3:
            st.metric("Avg per Day", f"{player_data.iloc[0]['mentions_per_day']:.2f}")
        with pcol4:
            days_ago = int(player_data.iloc[0]['days_since_last'])
            st.metric("Last Mention", f"{days_ago}d ago" if days_ago > 0 else "Today")
        
        # Timeline chart
        st.markdown("### 📈 Mention Timeline")
        
        daily_mentions = player_rumors.groupby(player_rumors['date'].dt.date).size().reset_index(name='mentions')
        daily_mentions.columns = ['date', 'mentions']
        daily_mentions['date'] = pd.to_datetime(daily_mentions['date'])
        
        if len(daily_mentions) > 1:
            chart = alt.Chart(daily_mentions).mark_bar(
                color='#667eea',
                cornerRadiusTopLeft=4,
                cornerRadiusTopRight=4
            ).encode(
                x=alt.X('date:T', title='Date', axis=alt.Axis(format='%b %d')),
                y=alt.Y('mentions:Q', title='Mentions'),
                tooltip=[
                    alt.Tooltip('date:T', title='Date', format='%B %d, %Y'),
                    alt.Tooltip('mentions:Q', title='Mentions')
                ]
            ).properties(height=250)
            
            st.altair_chart(chart, use_container_width=True)
        else:
            st.info("Not enough data points for timeline chart.")
        
        # Recent rumors
        st.markdown("### 📰 Recent Trade Rumors")
        
        for idx, rumor in player_rumors.head(15).iterrows():
            date_str = rumor['date'].strftime('%b %d, %Y')
            source = rumor.get('source', 'Unknown')
            # Use 'snippet' column (what scraper outputs) or 'title' as headline
            headline = rumor.get('title', rumor.get('snippet', ''))[:100]
            snippet = rumor.get('snippet', '')
            url = rumor.get('url', '')
            
            with st.expander(f"📅 {date_str} — {source}"):
                st.markdown(f"**{headline}**")
                if snippet:
                    st.markdown(snippet[:500] + "..." if len(snippet) > 500 else snippet)
                if url:
                    st.markdown(f"[Read Full Article →]({url})")
        
        st.markdown("---")
        st.markdown("### Full Rankings")

# Main rankings table
st.markdown("## 🏀 Top Trade Rumor Targets")

# Display format selector
view_mode = st.radio("View", ["Cards", "Table"], horizontal=True, label_visibility="collapsed")

if view_mode == "Cards":
    # Card-based view
    for idx, row in player_stats.head(30).iterrows():
        rank = int(row['rank'])
        mentions = int(row['total_mentions'])
        days_since = int(row['days_since_last'])
        slug = row['slug']
        
        # Heat indicator
        if days_since == 0:
            heat = "🔥🔥🔥"
            heat_class = "heat-high"
        elif days_since <= 2:
            heat = "🔥🔥"
            heat_class = "heat-medium"
        else:
            heat = "🔥"
            heat_class = "heat-low"
        
        col_rank, col_info, col_stats = st.columns([1, 4, 2])
        
        with col_rank:
            st.markdown(f"### #{rank}")
        
        with col_info:
            st.markdown(f"**[{row['player']}](?player={slug})**")
            sources_display = row['sources'][:60] + "..." if len(row['sources']) > 60 else row['sources']
            st.caption(f"Sources: {sources_display}")
        
        with col_stats:
            st.markdown(f"<span class='{heat_class}'>{heat} {mentions} mentions</span>", unsafe_allow_html=True)
            if days_since == 0:
                st.caption("Last: Today")
            else:
                st.caption(f"Last: {days_since}d ago")
        
        st.markdown("---")

else:
    # Table view
    table_df = player_stats[['rank', 'player', 'total_mentions', 'days_active', 'days_since_last', 'sources']].copy()
    table_df.columns = ['Rank', 'Player', 'Mentions', 'Days Active', 'Days Since Last', 'Sources']
    table_df['Sources'] = table_df['Sources'].apply(lambda x: x[:40] + "..." if len(x) > 40 else x)
    
    st.dataframe(
        table_df.head(50),
        use_container_width=True,
        hide_index=True,
        column_config={
            "Rank": st.column_config.NumberColumn(width="small"),
            "Player": st.column_config.TextColumn(width="medium"),
            "Mentions": st.column_config.NumberColumn(width="small"),
            "Days Active": st.column_config.NumberColumn(width="small"),
            "Days Since Last": st.column_config.NumberColumn(width="small"),
            "Sources": st.column_config.TextColumn(width="large"),
        }
    )

# Trends section
st.markdown("---")
st.markdown("## 📊 Daily Rumor Volume")

daily_total = df.groupby(df['date'].dt.date).size().reset_index(name='rumors')
daily_total.columns = ['date', 'rumors']
daily_total['date'] = pd.to_datetime(daily_total['date'])

trend_chart = alt.Chart(daily_total).mark_area(
    line={'color': '#667eea'},
    color=alt.Gradient(
        gradient='linear',
        stops=[alt.GradientStop(color='white', offset=0),
               alt.GradientStop(color='#667eea', offset=1)],
        x1=1, x2=1, y1=1, y2=0
    )
).encode(
    x=alt.X('date:T', title='Date', axis=alt.Axis(format='%b %d')),
    y=alt.Y('rumors:Q', title='Total Rumors'),
    tooltip=[
        alt.Tooltip('date:T', title='Date', format='%B %d, %Y'),
        alt.Tooltip('rumors:Q', title='Rumors')
    ]
).properties(height=200)

st.altair_chart(trend_chart, use_container_width=True)

# Footer
st.markdown("---")
st.caption(f"Data from HoopsHype trade rumors. Last updated: {df['date'].max().strftime('%B %d, %Y')}")
