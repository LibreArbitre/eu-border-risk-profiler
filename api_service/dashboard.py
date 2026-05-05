"""
EU Border Risk Profiler Dashboard
Advanced dashboard for analysts monitoring asylum trends and risk predictions
"""

import os
from datetime import datetime

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st

# Configuration
API_URL = os.getenv("API_URL", "http://localhost:8000")
API_KEY = os.getenv("API_KEY") or None
_API_HEADERS = {"X-API-Key": API_KEY} if API_KEY else {}

# Page config - must be first Streamlit command
st.set_page_config(
    page_title="EU Border Risk Profiler",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="collapsed",
    menu_items={"Get Help": None, "Report a bug": None, "About": None},
)

# Custom CSS for modern look
st.markdown(
    """
<style>
    /* Hide Streamlit branding and deploy button */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    .stDeployButton {display: none;}
    
    /* Main container styling */
    .main .block-container {
        padding-top: 1rem !important;
        padding-bottom: 2rem;
        max-width: 1400px;
    }
    
    /* Header styling */
    .dashboard-header {
        background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
        padding: 2rem;
        border-radius: 12px;
        margin-bottom: 2rem;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
        color: white;
    }
    
    .dashboard-title {
        color: #f8fafc !important;
        font-family: 'Inter', sans-serif;
        font-size: 2.25rem !important;
        font-weight: 800 !important;
        margin: 0 !important;
        letter-spacing: -0.025em;
    }
    
    .dashboard-subtitle {
        color: #94a3b8 !important;
        font-family: 'Inter', sans-serif;
        font-size: 1.1rem !important;
        margin-top: 0.5rem !important;
        font-weight: 400;
    }
    
    /* Metric cards */
    .metric-card {
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 12px;
        padding: 1.5rem;
        box-shadow: 0 1px 3px 0 rgba(0, 0, 0, 0.1), 0 1px 2px 0 rgba(0, 0, 0, 0.06);
        transition: transform 0.2s;
    }
    
    .metric-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05);
    }
    
    .metric-label {
        color: #64748b;
        font-size: 0.875rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        margin-bottom: 0.5rem;
    }
    
    .metric-value {
        color: #0f172a;
        font-size: 2rem;
        font-weight: 700;
        letter-spacing: -0.025em;
    }
    
    /* Section headers */
    .section-header {
        color: #0f172a;
        font-size: 1.5rem;
        font-weight: 700;
        margin-top: 1rem;
        margin-bottom: 1.5rem;
        display: flex;
        align-items: center;
        gap: 0.5rem;
    }
    
    /* Chart container */
    .chart-container {
        background: white;
        padding: 1rem;
        border-radius: 12px;
        border: 1px solid #e2e8f0;
        box-shadow: 0 1px 2px 0 rgba(0, 0, 0, 0.05);
    }
    
    /* Table Styling */
    div[data-testid="stDataFrame"] {
        border: 1px solid #e2e8f0;
        border-radius: 12px;
        box-shadow: 0 1px 2px 0 rgba(0, 0, 0, 0.05);
        padding: 0.5rem;
        background: white;
    }
</style>
""",
    unsafe_allow_html=True,
)


# --- Data Fetching Functions ---
@st.cache_data(ttl=60)  # Short cache for responsiveness
def get_predictions():
    """Fetch risk predictions from API"""
    try:
        r = requests.get(f"{API_URL}/api/v1/risk/predict", timeout=10, headers=_API_HEADERS)
        if r.status_code == 200:
            return pd.DataFrame(r.json())
        return pd.DataFrame()
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=60)
def get_latest():
    """Fetch latest risk data from API"""
    try:
        r = requests.get(f"{API_URL}/api/v1/risk/latest", timeout=10, headers=_API_HEADERS)
        if r.status_code == 200:
            return pd.DataFrame(r.json())
        return pd.DataFrame()
    except:
        return pd.DataFrame()


def get_history(geo_code: str):
    """Fetch historical data for a country"""
    try:
        r = requests.get(f"{API_URL}/api/v1/data/history/{geo_code}", timeout=10, headers=_API_HEADERS)
        if r.status_code == 200:
            return pd.DataFrame(r.json())
        return pd.DataFrame()
    except:
        return pd.DataFrame()


# Country name mapping
COUNTRY_NAMES = {
    "AT": "Austria",
    "BE": "Belgium",
    "BG": "Bulgaria",
    "CY": "Cyprus",
    "CZ": "Czechia",
    "DE": "Germany",
    "DK": "Denmark",
    "EE": "Estonia",
    "ES": "Spain",
    "FI": "Finland",
    "FR": "France",
    "GR": "Greece",
    "EL": "Greece",
    "HR": "Croatia",
    "HU": "Hungary",
    "IE": "Ireland",
    "IT": "Italy",
    "LT": "Lithuania",
    "LU": "Luxembourg",
    "LV": "Latvia",
    "MT": "Malta",
    "NL": "Netherlands",
    "PL": "Poland",
    "PT": "Portugal",
    "RO": "Romania",
    "SE": "Sweden",
    "SI": "Slovenia",
    "SK": "Slovakia",
}

# ISO-2 to ISO-3 mapping for Plotly
ISO_MAP = {
    "AT": "AUT",
    "BE": "BEL",
    "BG": "BGR",
    "CY": "CYP",
    "CZ": "CZE",
    "DE": "DEU",
    "DK": "DNK",
    "EE": "EST",
    "ES": "ESP",
    "FI": "FIN",
    "FR": "FRA",
    "GR": "GRC",
    "EL": "GRC",
    "HR": "HRV",
    "HU": "HUN",
    "IE": "IRL",
    "IT": "ITA",
    "LT": "LTU",
    "LU": "LUX",
    "LV": "LVA",
    "MT": "MLT",
    "NL": "NLD",
    "PL": "POL",
    "PT": "PRT",
    "RO": "ROU",
    "SE": "SWE",
    "SI": "SVN",
    "SK": "SVK",
}

# --- Header ---
st.markdown(
    """
<div class="dashboard-header">
    <div style="display: flex; align-items: center; justify-content: space-between;">
        <div>
            <h1 class="dashboard-title">EU Border Risk Profiler</h1>
            <p class="dashboard-subtitle">Monitoring and Forecasting Asylum Application Trends across the European Union</p>
        </div>
        <div style="text-align: right;">
            <div style="background: rgba(255,255,255,0.1); padding: 0.5rem 1rem; border-radius: 8px;">
                <span style="color: #cbd5e1; font-size: 0.9rem;">System Status</span><br>
                <span style="color: #4ade80; font-weight: 600;">● Operational</span>
            </div>
        </div>
    </div>
</div>
""",
    unsafe_allow_html=True,
)

# --- Load Data ---
df_pred = get_predictions()
if not df_pred.empty:
    df_pred["date"] = pd.to_datetime(df_pred["date"])
    df_pred["prediction_target_month"] = pd.to_datetime(df_pred["prediction_target_month"])

df_curr = get_latest()

# --- Logic: Handle Data Lags ---
# We want to display the "Current Risk" which is the prediction for the coming month
# based on the LATEST available data for each country.
valid_data = False
df_map = pd.DataFrame()

if not df_pred.empty:
    # 1. Sort by date (source date)
    df_sorted = df_pred.sort_values("date")

    # 2. Get latest source date per country
    latest_dates = df_pred.groupby("geo_code")["date"].max().reset_index()

    # 3. Merge back to get the rows corresponding to these latest dates
    merged = pd.merge(df_pred, latest_dates, on=["geo_code", "date"])

    # 4. Aggregate predictions (Stable indicator: Mean of 3 months horizon)
    df_map = (
        merged.groupby("geo_code")
        .agg(
            {
                "risk_score_calculated": "first",  # Current calculated risk
                "predicted_risk_score": "mean",  # Average risk in next 3 months (Stable)
                "date": "first",
            }
        )
        .reset_index()
    )

    df_map["risk_score"] = df_map["predicted_risk_score"]  # Use this for viz
    valid_data = True

# --- KPI Metrics Row ---
if valid_data:
    # Calculate KPIs
    avg_risk = df_map["risk_score"].mean()
    max_risk = df_map["risk_score"].max()
    max_risk_country = df_map.loc[df_map["risk_score"].idxmax(), "geo_code"]
    total_countries = df_map["geo_code"].nunique()

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.markdown(
            f"""
        <div class="metric-card">
            <div class="metric-label">EU Avg Risk Index</div>
            <div class="metric-value">{avg_risk:.1f}</div>
        </div>
        """,
            unsafe_allow_html=True,
        )

    with col2:
        st.markdown(
            f"""
        <div class="metric-card">
            <div class="metric-label">Max Risk Index</div>
            <div class="metric-value" style="color: #dc2626;">{max_risk:.1f}</div>
        </div>
        """,
            unsafe_allow_html=True,
        )

    with col3:
        st.markdown(
            f"""
        <div class="metric-card">
            <div class="metric-label">High Risk Hotspot</div>
            <div class="metric-value">{COUNTRY_NAMES.get(max_risk_country, max_risk_country)}</div>
        </div>
        """,
            unsafe_allow_html=True,
        )

    with col4:
        st.markdown(
            f"""
        <div class="metric-card">
            <div class="metric-label">Monitored Countries</div>
            <div class="metric-value">{total_countries}</div>
        </div>
        """,
            unsafe_allow_html=True,
        )

    st.markdown("<br>", unsafe_allow_html=True)

# --- Main Content ---
col_map, col_ranking = st.columns([2, 1])

with col_map:
    st.markdown('<div class="section-header"><span>🌍</span> Risk Heatmap (Forecast)</div>', unsafe_allow_html=True)

    if valid_data:
        # Map to ISO-3 codes
        df_map["iso_alpha"] = df_map["geo_code"].map(ISO_MAP)
        df_map["country_name"] = df_map["geo_code"].map(COUNTRY_NAMES)

        # Create choropleth
        fig = px.choropleth(
            df_map,
            locations="iso_alpha",
            color="risk_score",
            scope="europe",
            # Color Scale: Blue (Low) -> Yellow (Med) -> Orange (High) -> Red (Extreme)
            color_continuous_scale=[
                [0.0, "#f0f9ff"],  # Very Low
                [0.2, "#bae6fd"],  # Low
                [0.4, "#fde047"],  # Medium
                [0.6, "#f97316"],  # High
                [0.8, "#dc2626"],  # Very High
                [1.0, "#7f1d1d"],  # Extreme
            ],
            range_color=[0, 100],  # Force scale 0-100 for consistency
            hover_name="country_name",
            hover_data={"iso_alpha": False, "risk_score": ":.1f", "geo_code": False},
            labels={"risk_score": "Risk Score"},
        )

        # Update layout for polished look
        fig.update_geos(
            showcoastlines=True,
            coastlinecolor="#cbd5e1",
            showland=True,
            landcolor="#f8fafc",
            showocean=True,
            oceancolor="#e0f2fe",  # Light blue ocean
            showlakes=True,
            lakecolor="#e0f2fe",
            showframe=False,
            showcountries=True,
            countrycolor="white",
            projection_type="mercator",
            center={"lat": 54, "lon": 15},
            lataxis_range=[35, 72],
            lonaxis_range=[-12, 45],
        )

        fig.update_layout(
            margin={"r": 0, "t": 0, "l": 0, "b": 0},
            coloraxis_colorbar={
                "title": "",
                "thickness": 12,
                "len": 0.5,
                "x": 0.05,
                "y": 0.5,
                "tickfont": {"color": "#64748b"},
            },
            height=550,
            paper_bgcolor="rgba(0,0,0,0)",
            geo_bgcolor="rgba(0,0,0,0)",
        )

        with st.container():
            st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("⏳ System initializing... Waiting for prediction data.")

with col_ranking:
    st.markdown('<div class="section-header"><span>🏆</span> Risk Ranking</div>', unsafe_allow_html=True)

    if valid_data:
        # Sort by risk score
        ranking = df_map[["geo_code", "risk_score"]].copy()
        ranking = ranking.sort_values("risk_score", ascending=False)
        ranking["Country"] = ranking["geo_code"].map(COUNTRY_NAMES)
        ranking = ranking.reset_index(drop=True)
        ranking.columns = ["Code", "Score", "Country"]

        # Add Rank
        ranking.index = ranking.index + 1
        ranking["Rank"] = ranking.index

        final_ranking = ranking[["Country", "Score"]]

        st.dataframe(
            final_ranking,
            use_container_width=True,
            height=550,
            column_config={
                "Country": st.column_config.TextColumn("Country", width="medium"),
                "Score": st.column_config.ProgressColumn(
                    "Risk Index",
                    format="%.1f",
                    min_value=0,
                    max_value=100,
                ),
            },
        )
    else:
        st.info("No data available.")

# --- Country Analysis Section ---
st.markdown("<br>", unsafe_allow_html=True)
st.markdown('<div class="section-header"><span>📈</span> Deep Dive Analysis</div>', unsafe_allow_html=True)

if valid_data:
    # Dropdown
    countries = sorted(df_map["geo_code"].unique())
    country_options = {code: f"{COUNTRY_NAMES.get(code, code)} ({code})" for code in countries}

    col_select, col_empty = st.columns([1, 2])
    with col_select:
        selected_code = st.selectbox(
            "Select Country", options=countries, format_func=lambda x: country_options.get(x, x)
        )

    if selected_code:
        col_hist, col_stats = st.columns([2, 1])

        # Fetch history
        df_hist = get_history(selected_code)

        with col_hist:
            if not df_hist.empty:
                df_hist["date"] = pd.to_datetime(df_hist["date"])
                df_hist = df_hist.sort_values("date")

                # Chart
                fig_line = go.Figure()
                fig_line.add_trace(
                    go.Scatter(
                        x=df_hist["date"],
                        y=df_hist["total"],
                        mode="lines",
                        fill="tozeroy",
                        name="Applications",
                        line=dict(color="#0ea5e9", width=3),
                        fillcolor="rgba(14, 165, 233, 0.1)",
                    )
                )

                fig_line.update_layout(
                    title="Volume History (Applications)",
                    xaxis_title="",
                    yaxis_title="",
                    hovermode="x unified",
                    height=350,
                    showlegend=False,
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                    yaxis=dict(gridcolor="#f1f5f9"),
                    xaxis=dict(gridcolor="#f1f5f9"),
                )

                st.plotly_chart(fig_line, use_container_width=True)
            else:
                st.warning("No historical data available.")

        with col_stats:
            # Show specific stats for this country
            row = df_map[df_map["geo_code"] == selected_code].iloc[0]
            st.markdown(
                f"""
            <div class="metric-card">
                <div class="metric-label">Current Risk Index</div>
                <div class="metric-value">{row["risk_score"]:.1f}</div>
                <div style="color: #64748b; font-size: 0.9rem; margin-top:0.5rem;">
                    Assessment based on data up to {row["date"].strftime("%b %Y")}
                </div>
            </div>
            """,
                unsafe_allow_html=True,
            )

            st.markdown("<br>", unsafe_allow_html=True)
            st.info("""
            **Analysis Note:**
            Risk score is calculated based on volume relative to global historical peaks (Log Scale) and recent trend variations.
            """)

# --- About this data ---
st.markdown("<br><br>", unsafe_allow_html=True)
st.markdown(
    '<div class="section-header"><span>ℹ️</span> About this data</div>',
    unsafe_allow_html=True,
)

with st.expander("Source, methodology, intended use, and known limitations", expanded=False):
    st.markdown(
        """
**Source.** Monthly first-time asylum applications published by **Eurostat**
under dataset code [`migr_asyappctzm`](https://ec.europa.eu/eurostat/databrowser/view/migr_asyappctzm/default/table)
("*Asylum applicants by type, citizenship, age and sex — monthly data*").
The dataset is updated monthly with a typical reporting lag of **one to
two months**; recent months may be revised when Member States submit
corrections. The data is aggregated to the (date, destination Member
State) level by this project before any modelling.

**What the score means.** The **Risk Index** shown here is a 0-100
indicator of *administrative pressure* on a Member State's first-time
asylum procedure for a given month, derived as
`vol_norm × (1 + variation) × 100`, where `vol_norm` is the volume
log-normalised against the all-time EU peak and `variation` is the
month-over-month change. A 27-country Random Forest forecasts the
score for the next three months. See
[Model Card](https://github.com/LibreArbitre/eu-border-risk-profiler/blob/main/docs/MODEL_CARD.md).

**Intended use.** Operational situational awareness for migration
policy analysts. The score helps surface Member States where
short-term administrative pressure is likely to rise.

**Out-of-scope use.** This dashboard **must not** inform decisions
concerning individual asylum applicants, automated allocation between
Member States, or any border-policing action. The score reflects
administrative pressure on a Member State, not a judgement on the
people applying.

**Known limitations.** Reporting lag means the most recent month is
often understated and the predictor automatically drops a country's
last month if it would otherwise read as zero. Citizenship is
currently aggregated to `TOTAL` — per-nationality breakdowns are on
the roadmap. Forecasts at M+2 and M+3 are autoregressive and inherit
M+1's error.

**Citation.**
> Eurostat. *Asylum applicants by type, citizenship, age and sex —
> monthly data* (online data code: `migr_asyappctzm`).
> Accessed via the EU Border Risk Profiler.

**Further reading.**
[Data Card](https://github.com/LibreArbitre/eu-border-risk-profiler/blob/main/docs/DATA_CARD.md) ·
[Model Card](https://github.com/LibreArbitre/eu-border-risk-profiler/blob/main/docs/MODEL_CARD.md) ·
[Architecture Decision Records](https://github.com/LibreArbitre/eu-border-risk-profiler/tree/main/docs/adr) ·
[Security posture](https://github.com/LibreArbitre/eu-border-risk-profiler/blob/main/docs/SECURITY.md)
        """
    )

# --- Footer ---
st.markdown("<br><br><hr>", unsafe_allow_html=True)
st.markdown(
    """
<div style="text-align: center; color: #94a3b8; font-size: 0.8rem; padding: 2rem;">
    <strong>EU Border Risk Profiler v2.0</strong><br>
    Data Source: Eurostat (migr_asyappctzm) • Last Update: {}
</div>
""".format(datetime.now().strftime("%d %b %Y")),
    unsafe_allow_html=True,
)
