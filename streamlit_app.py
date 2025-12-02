import streamlit as st
import pandas as pd
import altair as alt
from datetime import datetime, timedelta
import re

# Page config
st.set_page_config(
    page_title="NBA Trade Rumor Rankings",
    page_icon="📈",
    layout="wide"
)

# Load data
@st.cache_data
def load_data():
    df = pd.read_csv('trade_rumors.csv')
    df['date'] = pd.to_datetime(df['date'])
    return df

df = load_data()

# Get query parameters
query_params = st.query_params
selected_player = query_params.get('player', None)

# Title
st.title("NBA Trade Rumor Rankings")
st.markdown("*Rankings based on frequency of trade rumors and speculation*")

# Aggregate by player
player_stats = df.groupby('player').agg({
    'date': ['min', 'max', 'count'],
    'team': lambda x: ', '.join(sorted(set(x)))
}).reset_index()

player_stats.columns = ['player', 'first_mention', 'last_mention', 'total_mentions', 'teams']
player_stats['days_active'] = (player_stats['last_mention'] - player_stats['first_mention']).dt.days + 1
player_stats['mentions_per_day'] = player_stats['total_mentions'] / player_stats['days_active']
player_stats = player_stats.sort_values('total_mentions', ascending=False)

# Create player slug for URL
def create_slug(name):
    return name.lower().replace(' ', '-').replace("'", '')

player_stats['slug'] = player_stats['player'].apply(create_slug)

# Main rankings table
st.subheader("Top Trade Rumor Targets")

# Create clickable table with links
table_data = player_stats[['player', 'total_mentions', 'teams', 'last_mention']].copy()
table_data['last_mention'] = table_data['last_mention'].dt.strftime('%Y-%m-%d')
table_data = table_data.rename(columns={
    'player': 'Player',
    'total_mentions': 'Total Mentions',
    'teams': 'Teams Mentioned',
    'last_mention': 'Last Mention'
})

# Add rank column
table_data.insert(0, 'Rank', range(1, len(table_data) + 1))

# Create HTML table with links
html_table = "<table style='width:100%; border-collapse: collapse;'>"
html_table += "<tr style='background-color: #f0f0f0; font-weight: bold;'>"
html_table += "<th style='padding: 10px; border: 1px solid #ddd;'>Rank</th>"
html_table += "<th style='padding: 10px; border: 1px solid #ddd;'>Player</th>"
html_table += "<th style='padding: 10px; border: 1px solid #ddd;'>Total Mentions</th>"
html_table += "<th style='padding: 10px; border: 1px solid #ddd;'>Teams Mentioned</th>"
html_table += "<th style='padding: 10px; border: 1px solid #ddd;'>Last Mention</th>"
html_table += "</tr>"

for idx, row in player_stats.iterrows():
    slug = row['slug']
    html_table += f"<tr style='border: 1px solid #ddd;'>"
    html_table += f"<td style='padding: 10px; border: 1px solid #ddd;'>{row.name + 1}</td>"
    html_table += f"<td style='padding: 10px; border: 1px solid #ddd;'><a href='?player={slug}' style='color: #0066cc; text-decoration: none;'>{row['player']}</a></td>"
    html_table += f"<td style='padding: 10px; border: 1px solid #ddd;'>{row['total_mentions']}</td>"
    html_table += f"<td style='padding: 10px; border: 1px solid #ddd;'>{row['teams']}</td>"
    html_table += f"<td style='padding: 10px; border: 1px solid #ddd;'>{row['last_mention'].strftime('%Y-%m-%d')}</td>"
    html_table += "</tr>"

html_table += "</table>"

st.markdown(html_table, unsafe_allow_html=True)

# If player selected, show details
if selected_player:
    player_data = player_stats[player_stats['slug'] == selected_player]
    
    if not player_data.empty:
        player_name = player_data.iloc[0]['player']
        
        st.markdown("---")
        st.subheader(f"{player_name} – Trade Rumor Timeline")
        
        # Filter rumors for this player
        player_rumors = df[df['player'] == player_name].sort_values('date', ascending=False)
        
        # Stats
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Total Mentions", int(player_data.iloc[0]['total_mentions']))
        with col2:
            st.metric("Days Active", int(player_data.iloc[0]['days_active']))
        with col3:
            st.metric("Avg per Day", f"{player_data.iloc[0]['mentions_per_day']:.2f}")
        
        # Timeline chart
        daily_mentions = player_rumors.groupby('date').size().reset_index(name='mentions')
        daily_mentions['day'] = (daily_mentions['date'] - daily_mentions['date'].min()).dt.days
        
        # Calculate moving average
        daily_mentions = daily_mentions.sort_values('date')
        daily_mentions['mentions_start'] = daily_mentions['mentions'].rolling(window=3, min_periods=1).mean()
        daily_mentions['mentions_end'] = daily_mentions['mentions'].rolling(window=3, min_periods=1).mean().shift(-1)
        
        chart = alt.Chart(daily_mentions).mark_line(point=True).encode(
            x=alt.X('date:T', title='Date'),
            y=alt.Y('mentions:Q', title='Mentions per Day'),
            tooltip=['date:T', 'mentions:Q']
        ).properties(
            height=300,
            title=f'Trade Rumor Mentions Over Time'
        )
        
        st.altair_chart(chart, use_container_width=True)
        
        # Recent rumors
        st.subheader("Most Recent Trade Rumors")
        
        for idx, rumor in player_rumors.head(10).iterrows():
            with st.expander(f"📅 {rumor['date'].strftime('%Y-%m-%d')} – {rumor['team']}"):
                st.markdown(f"**{rumor['headline']}**")
                st.markdown(rumor['excerpt'])
                st.markdown(f"[View Source]({rumor['source_url']})")

# Footer
st.markdown("---")
st.caption("Data compiled from various NBA news sources and social media. Updated regularly.")

if __name__ == "__main__":
    import streamlit.components.v1 as components
    
    components.html("""
    <script>
    (function() {
      console.log('Trade rumor iframe communication initialized');
      
      // Listen for navigation requests from parent
      window.addEventListener('message', function(event) {
        console.log('Streamlit received message:', event.data);
        
        if (event.data.type === 'navigate-to-player') {
          const playerSlug = event.data.playerSlug;
          console.log('Navigating to player slug:', playerSlug);
          
          setTimeout(function() {
            const links = document.querySelectorAll('a[href*="?player="]');
            links.forEach(function(link) {
              if (link.href.includes('player=' + playerSlug)) {
                link.click();
              }
            });
          }, 500);
        }
      });
      
      // Attach click handler with proper event prevention
      function attachClickHandler() {
        document.addEventListener('click', function(e) {
          // Check if click is on or inside a player link
          const link = e.target.closest('a[href*="?player="]');
          
          if (link && link.href) {
            console.log('Link clicked, processing...');
            
            // Prevent default navigation
            e.preventDefault();
            e.stopPropagation();
            
            const url = new URL(link.href);
            const playerSlug = url.searchParams.get('player');
            
            if (playerSlug) {
              console.log('Player link clicked, sending to parent:', playerSlug);
              
              // Send to parent
              window.parent.postMessage({
                type: 'player-selected',
                playerSlug: playerSlug
              }, '*');
              
              // Also navigate within iframe
              window.location.href = link.href;
            }
          }
        }, true);
        
        console.log('Click handler attached');
      }
      
      // Try multiple times to ensure Streamlit has loaded
      setTimeout(attachClickHandler, 1000);
      setTimeout(attachClickHandler, 2000);
      setTimeout(attachClickHandler, 3000);
      
      // Also attach on DOMContentLoaded
      if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', attachClickHandler);
      } else {
        attachClickHandler();
      }
      
    })();
    </script>
    """, height=0)
