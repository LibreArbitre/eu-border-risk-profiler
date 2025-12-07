"""
EU Border Risk Profiler Dashboard
Professional dashboard for analysts monitoring asylum trends and risk predictions
"""
import streamlit as st
import requests
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import os
from datetime import datetime

# Configuration
API_URL = os.getenv("API_URL", "http://localhost:8000")

# Page config - must be first Streamlit command
st.set_page_config(
    page_title="EU Border Risk Profiler",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="collapsed",
    menu_items={
        'Get Help': None,
        'Report a bug': None,
        'About': None
    }
)

# Custom CSS for professional look
st.markdown("""
<style>
    /* Hide Streamlit branding and deploy button */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    .stDeployButton {display: none;}
    
    /* Main container styling */
    .main .block-container {
        padding-top: 0 !important;
        padding-bottom: 2rem;
        max-width: 1400px;
    }
    
    /* Header styling */
    .dashboard-header {
        background: linear-gradient(135deg, #1e3a5f 0%, #2c5282 100%);
        padding: 1.5rem 2rem;
        border-radius: 0 0 12px 12px;
        margin: -1rem -1rem 2rem -1rem;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
    }
    
    .dashboard-title {
        color: #ffffff !important;
        font-size: 2rem !important;
        font-weight: 700 !important;
        margin: 0 !important;
        letter-spacing: -0.5px;
    }
    
    .dashboard-subtitle {
        color: #a0c4e8 !important;
        font-size: 1rem !important;
        margin-top: 0.5rem !important;
        font-weight: 400;
    }
    
    /* Metric cards */
    .metric-card {
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 10px;
        padding: 1.25rem;
        box-shadow: 0 1px 3px rgba(0,0,0,0.08);
        transition: box-shadow 0.2s ease;
    }
    
    .metric-card:hover {
        box-shadow: 0 4px 12px rgba(0,0,0,0.12);
    }
    
    .metric-label {
        color: #64748b;
        font-size: 0.85rem;
        font-weight: 500;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        margin-bottom: 0.5rem;
    }
    
    .metric-value {
        color: #1e293b;
        font-size: 1.75rem;
        font-weight: 700;
    }
    
    .metric-delta-positive {
        color: #dc2626;
        font-size: 0.875rem;
    }
    
    .metric-delta-negative {
        color: #16a34a;
        font-size: 0.875rem;
    }
    
    /* Section headers */
    .section-header {
        color: #1e293b;
        font-size: 1.25rem;
        font-weight: 600;
        padding-bottom: 0.75rem;
        border-bottom: 2px solid #e2e8f0;
        margin-bottom: 1rem;
    }
    
    /* Data tables */
    .stDataFrame {
        border-radius: 8px;
        overflow: hidden;
    }
    
    /* Plotly charts container */
    .chart-container {
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 12px;
        padding: 1rem;
        box-shadow: 0 1px 3px rgba(0,0,0,0.08);
    }
    
    /* Info/Warning boxes */
    .stAlert {
        border-radius: 8px;
    }
    
    /* Selectbox styling */
    .stSelectbox > div > div {
        border-radius: 8px;
    }
    
    /* Remove default padding from columns */
    div[data-testid="column"] {
        padding: 0.5rem;
    }
</style>
""", unsafe_allow_html=True)

# --- Data Fetching Functions ---
@st.cache_data(ttl=3600)
def get_predictions():
    """Fetch risk predictions from API"""
    try:
        r = requests.get(f"{API_URL}/api/v1/risk/predict", timeout=10)
        if r.status_code == 200:
            return pd.DataFrame(r.json())
        return pd.DataFrame()
    except Exception as e:
        return pd.DataFrame()

@st.cache_data(ttl=3600)
def get_latest():
    """Fetch latest risk data from API"""
    try:
        r = requests.get(f"{API_URL}/api/v1/risk/latest", timeout=10)
        if r.status_code == 200:
            return pd.DataFrame(r.json())
        return pd.DataFrame()
    except:
        return pd.DataFrame()

def get_history(geo_code: str):
    """Fetch historical data for a country"""
    try:
        r = requests.get(f"{API_URL}/api/v1/data/history/{geo_code}", timeout=10)
        if r.status_code == 200:
            return pd.DataFrame(r.json())
        return pd.DataFrame()
    except:
        return pd.DataFrame()

# Country name mapping
COUNTRY_NAMES = {
    'AT': 'Austria', 'BE': 'Belgium', 'BG': 'Bulgaria', 'CY': 'Cyprus',
    'CZ': 'Czechia', 'DE': 'Germany', 'DK': 'Denmark', 'EE': 'Estonia',
    'ES': 'Spain', 'FI': 'Finland', 'FR': 'France', 'GR': 'Greece',
    'EL': 'Greece', 'HR': 'Croatia', 'HU': 'Hungary', 'IE': 'Ireland',
    'IT': 'Italy', 'LT': 'Lithuania', 'LU': 'Luxembourg', 'LV': 'Latvia',
    'MT': 'Malta', 'NL': 'Netherlands', 'PL': 'Poland', 'PT': 'Portugal',
    'RO': 'Romania', 'SE': 'Sweden', 'SI': 'Slovenia', 'SK': 'Slovakia'
}

# ISO-2 to ISO-3 mapping for Plotly
ISO_MAP = {
    'AT': 'AUT', 'BE': 'BEL', 'BG': 'BGR', 'CY': 'CYP', 'CZ': 'CZE',
    'DE': 'DEU', 'DK': 'DNK', 'EE': 'EST', 'ES': 'ESP', 'FI': 'FIN',
    'FR': 'FRA', 'GR': 'GRC', 'EL': 'GRC', 'HR': 'HRV', 'HU': 'HUN',
    'IE': 'IRL', 'IT': 'ITA', 'LT': 'LTU', 'LU': 'LUX', 'LV': 'LVA',
    'MT': 'MLT', 'NL': 'NLD', 'PL': 'POL', 'PT': 'PRT', 'RO': 'ROU',
    'SE': 'SWE', 'SI': 'SVN', 'SK': 'SVK'
}

# --- Header ---
st.markdown("""
<div class="dashboard-header">
    <h1 class="dashboard-title">EU Border Risk Profiler</h1>
    <p class="dashboard-subtitle">Monitoring and Forecasting Asylum Application Trends across the European Union</p>
</div>
""", unsafe_allow_html=True)

# --- Load Data ---
df_pred = get_predictions()
df_curr = get_latest()

# --- KPI Metrics Row ---
if not df_pred.empty:
    # Use the same date as the map for consistency
    min_date = df_pred['date'].min()
    df_kpi = df_pred[df_pred['date'] == min_date]
    
    # Calculate KPIs from the filtered data
    avg_risk = df_kpi['risk_score'].mean()
    max_risk = df_kpi['risk_score'].max()
    max_risk_country = df_kpi.loc[df_kpi['risk_score'].idxmax(), 'geo_code']
    countries_with_data = df_kpi['geo_code'].nunique()
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.markdown("""
        <div class="metric-card">
            <div class="metric-label">Average Risk Score</div>
            <div class="metric-value">{:.2f}</div>
        </div>
        """.format(avg_risk), unsafe_allow_html=True)
    
    with col2:
        st.markdown("""
        <div class="metric-card">
            <div class="metric-label">Highest Risk Score</div>
            <div class="metric-value">{:.2f}</div>
        </div>
        """.format(max_risk), unsafe_allow_html=True)
    
    with col3:
        st.markdown("""
        <div class="metric-card">
            <div class="metric-label">Highest Risk Country</div>
            <div class="metric-value">{}</div>
        </div>
        """.format(COUNTRY_NAMES.get(max_risk_country, max_risk_country)), unsafe_allow_html=True)
    
    with col4:
        st.markdown("""
        <div class="metric-card">
            <div class="metric-label">Countries with Predictions</div>
            <div class="metric-value">{}</div>
        </div>
        """.format(countries_with_data), unsafe_allow_html=True)
    
    st.markdown("<br>", unsafe_allow_html=True)

# --- Main Content ---
col_map, col_ranking = st.columns([2, 1])

with col_map:
    st.markdown('<p class="section-header">📊 Risk Heatmap (Predicted)</p>', unsafe_allow_html=True)
    
    if not df_pred.empty:
        # Get the first prediction month
        min_date = df_pred['date'].min()
        df_map = df_pred[df_pred['date'] == min_date].copy()
        
        # Map to ISO-3 codes
        df_map['iso_alpha'] = df_map['geo_code'].map(ISO_MAP)
        df_map['country_name'] = df_map['geo_code'].map(COUNTRY_NAMES)
        
        # Create choropleth with only countries that have data
        fig = px.choropleth(
            df_map,
            locations="iso_alpha",
            color="risk_score",
            scope="europe",
            color_continuous_scale=[
                [0, "#f0f9ff"],      # Very light blue for low risk
                [0.25, "#bae6fd"],   # Light blue
                [0.5, "#fbbf24"],    # Yellow/amber for medium
                [0.75, "#f97316"],   # Orange for high
                [1, "#dc2626"]       # Red for very high
            ],
            hover_name="country_name",
            hover_data={
                "iso_alpha": False,
                "risk_score": ":.2f",
                "geo_code": False
            },
            labels={"risk_score": "Risk Score"},
        )
        
        # Update layout for professional look - show ONLY countries with data
        fig.update_geos(
            showcoastlines=True,
            coastlinecolor="#94a3b8",
            showland=True,
            landcolor="#f8fafc",  # Light gray for countries without data
            showocean=True,
            oceancolor="#e0f2fe",
            showlakes=True,
            lakecolor="#e0f2fe",
            showframe=False,
            projection_type="mercator",
            center={"lat": 54, "lon": 15},
            lataxis_range=[35, 72],
            lonaxis_range=[-12, 45],
        )
        
        fig.update_layout(
            margin={"r": 0, "t": 40, "l": 0, "b": 0},
            title={
                "text": f"<b>Predicted Risk Scores</b> — {min_date}",
                "font": {"size": 14, "color": "#374151"},
                "x": 0.5,
                "xanchor": "center"
            },
            coloraxis_colorbar={
                "title": {"text": "Risk<br>Score", "font": {"size": 11}},
                "thickness": 15,
                "len": 0.6,
                "tickfont": {"size": 10}
            },
            height=500,
            paper_bgcolor="rgba(0,0,0,0)",
            geo_bgcolor="rgba(0,0,0,0)",
        )
        
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("⏳ No prediction data available. Waiting for Harvester and Predictor to complete.")

with col_ranking:
    st.markdown('<p class="section-header">🏆 Risk Ranking</p>', unsafe_allow_html=True)
    
    if not df_pred.empty:
        # Use the same date as the map (min_date) for consistency
        min_date = df_pred['date'].min()
        df_ranking = df_pred[df_pred['date'] == min_date].copy()
        
        # Sort by risk score
        ranking = df_ranking[['geo_code', 'risk_score']].copy()
        ranking = ranking.sort_values('risk_score', ascending=False)
        ranking['Country'] = ranking['geo_code'].map(COUNTRY_NAMES)
        ranking = ranking.reset_index(drop=True)
        ranking.columns = ['Code', 'Risk Score', 'Country']
        ranking = ranking[['Country', 'Code', 'Risk Score']]
        ranking['Risk Score'] = ranking['Risk Score'].round(2)
        ranking['Rank'] = range(1, len(ranking) + 1)
        ranking = ranking[['Rank', 'Country', 'Code', 'Risk Score']]
        
        # Style the dataframe
        st.dataframe(
            ranking,
            hide_index=True,
            use_container_width=True,
            column_config={
                "Rank": st.column_config.NumberColumn("", width="small"),
                "Country": st.column_config.TextColumn("Country", width="medium"),
                "Code": st.column_config.TextColumn("ISO", width="small"),
                "Risk Score": st.column_config.ProgressColumn(
                    "Risk Score",
                    format="%.2f",
                    min_value=0,
                    max_value=ranking['Risk Score'].max() * 1.1 if len(ranking) > 0 else 10,
                ),
            }
        )
    else:
        st.info("No ranking data available.")

# --- Country Analysis Section ---
st.markdown("<br>", unsafe_allow_html=True)
st.markdown('<p class="section-header">📈 Country Analysis</p>', unsafe_allow_html=True)

if not df_curr.empty or not df_pred.empty:
    # Get available countries
    if not df_pred.empty:
        countries = sorted(df_pred['geo_code'].unique())
    elif not df_curr.empty:
        countries = sorted(df_curr['geo_code'].unique())
    else:
        countries = []
    
    # Format dropdown with country names
    country_options = {code: f"{COUNTRY_NAMES.get(code, code)} ({code})" for code in countries}
    
    if countries:
        col_select, col_spacer = st.columns([1, 3])
        with col_select:
            selected_code = st.selectbox(
                "Select a country to analyze",
                options=countries,
                format_func=lambda x: country_options.get(x, x),
                key="country_select"
            )
        
        if selected_code:
            # Fetch history
            df_hist = get_history(selected_code)
            
            if not df_hist.empty:
                df_hist['date'] = pd.to_datetime(df_hist['date'])
                df_hist = df_hist.sort_values('date')
                
                # Create line chart
                fig_line = go.Figure()
                
                fig_line.add_trace(go.Scatter(
                    x=df_hist['date'],
                    y=df_hist['total'],
                    mode='lines+markers',
                    name='Applications',
                    line=dict(color='#3b82f6', width=2),
                    marker=dict(size=4),
                    fill='tozeroy',
                    fillcolor='rgba(59, 130, 246, 0.1)'
                ))
                
                fig_line.update_layout(
                    title={
                        "text": f"<b>Asylum Applications History</b> — {COUNTRY_NAMES.get(selected_code, selected_code)}",
                        "font": {"size": 14, "color": "#374151"},
                    },
                    xaxis_title="",
                    yaxis_title="Total Applications",
                    hovermode="x unified",
                    height=350,
                    margin={"r": 20, "t": 50, "l": 60, "b": 40},
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                    xaxis=dict(
                        showgrid=True,
                        gridcolor='rgba(0,0,0,0.05)',
                    ),
                    yaxis=dict(
                        showgrid=True,
                        gridcolor='rgba(0,0,0,0.05)',
                    )
                )
                
                st.plotly_chart(fig_line, use_container_width=True)
            else:
                st.info(f"No historical data available for {COUNTRY_NAMES.get(selected_code, selected_code)}.")
else:
    st.info("⏳ Waiting for data... Please ensure the Harvester and Predictor services have completed their initial run.")

# --- Footer ---
st.markdown("<br><br>", unsafe_allow_html=True)
st.markdown("""
<div style="text-align: center; color: #94a3b8; font-size: 0.8rem; padding: 1rem;">
    EU Border Risk Profiler • Data sourced from Eurostat
</div>
""", unsafe_allow_html=True)
