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

from api_service.i18n import country_name, language_selector, t

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


@st.cache_data(ttl=60)
def get_history_by_citizen(geo_code: str, top: int = 5, since: str | None = None):
    """Fetch top-N nationalities for a country."""
    try:
        params = {"top": top}
        if since:
            params["since"] = since
        r = requests.get(
            f"{API_URL}/api/v1/data/history/{geo_code}/by-citizen",
            timeout=10,
            headers=_API_HEADERS,
            params=params,
        )
        if r.status_code == 200:
            return pd.DataFrame(r.json())
        return pd.DataFrame()
    except Exception:
        return pd.DataFrame()


# Country names are localised via api_service.i18n.country_name(); see
# api_service/locales/*.toml for the per-language tables.

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

# --- Language selector (top of page, right-aligned) ---
language_selector()

# --- Header ---
st.markdown(
    f"""
<div class="dashboard-header">
    <div style="display: flex; align-items: center; justify-content: space-between;">
        <div>
            <h1 class="dashboard-title">{t("header.title")}</h1>
            <p class="dashboard-subtitle">{t("header.subtitle")}</p>
        </div>
        <div style="text-align: right;">
            <div style="background: rgba(255,255,255,0.1); padding: 0.5rem 1rem; border-radius: 8px;">
                <span style="color: #cbd5e1; font-size: 0.9rem;">{t("header.status_label")}</span><br>
                <span style="color: #4ade80; font-weight: 600;">● {t("header.status_value")}</span>
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

    # 4. Aggregate predictions (Stable indicator: Mean of 3 months horizon).
    #    The P10/P90 columns may be absent on legacy rows; aggregate them
    #    only when present so older data still renders without quantiles.
    agg_spec = {
        "risk_score_calculated": "first",  # Current calculated risk
        "predicted_risk_score": "mean",     # Average risk in next 3 months (Stable)
        "date": "first",
    }
    if "predicted_risk_score_p10" in merged.columns:
        agg_spec["predicted_risk_score_p10"] = "mean"
    if "predicted_risk_score_p90" in merged.columns:
        agg_spec["predicted_risk_score_p90"] = "mean"

    df_map = merged.groupby("geo_code").agg(agg_spec).reset_index()

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
            <div class="metric-label">{t("kpi.avg_risk")}</div>
            <div class="metric-value">{avg_risk:.1f}</div>
        </div>
        """,
            unsafe_allow_html=True,
        )

    with col2:
        st.markdown(
            f"""
        <div class="metric-card">
            <div class="metric-label">{t("kpi.max_risk")}</div>
            <div class="metric-value" style="color: #dc2626;">{max_risk:.1f}</div>
        </div>
        """,
            unsafe_allow_html=True,
        )

    with col3:
        st.markdown(
            f"""
        <div class="metric-card">
            <div class="metric-label">{t("kpi.hotspot")}</div>
            <div class="metric-value">{country_name(max_risk_country)}</div>
        </div>
        """,
            unsafe_allow_html=True,
        )

    with col4:
        st.markdown(
            f"""
        <div class="metric-card">
            <div class="metric-label">{t("kpi.monitored")}</div>
            <div class="metric-value">{total_countries}</div>
        </div>
        """,
            unsafe_allow_html=True,
        )

    st.markdown("<br>", unsafe_allow_html=True)

# --- Main Content ---
col_map, col_ranking = st.columns([2, 1])

with col_map:
    st.markdown(
        f'<div class="section-header"><span>🌍</span> {t("section.heatmap")}</div>',
        unsafe_allow_html=True,
    )

    if valid_data:
        # Map to ISO-3 codes
        df_map["iso_alpha"] = df_map["geo_code"].map(ISO_MAP)
        df_map["country_name"] = df_map["geo_code"].map(country_name)

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
            labels={"risk_score": t("map.risk_label")},
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
        st.info(t("map.initializing"))

with col_ranking:
    st.markdown(
        f'<div class="section-header"><span>🏆</span> {t("section.ranking")}</div>',
        unsafe_allow_html=True,
    )

    if valid_data:
        # Sort by risk score
        ranking = df_map[["geo_code", "risk_score"]].copy()
        ranking = ranking.sort_values("risk_score", ascending=False)
        ranking["Country"] = ranking["geo_code"].map(country_name)
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
                "Country": st.column_config.TextColumn(t("ranking.country"), width="medium"),
                "Score": st.column_config.ProgressColumn(
                    t("ranking.risk_index"),
                    format="%.1f",
                    min_value=0,
                    max_value=100,
                ),
            },
        )
    else:
        st.info(t("ranking.no_data"))

# --- Country Analysis Section ---
st.markdown("<br>", unsafe_allow_html=True)
st.markdown(
    f'<div class="section-header"><span>📈</span> {t("section.deep_dive")}</div>',
    unsafe_allow_html=True,
)

if valid_data:
    # Dropdown
    countries = sorted(df_map["geo_code"].unique())
    country_options = {code: f"{country_name(code)} ({code})" for code in countries}

    col_select, col_empty = st.columns([1, 2])
    with col_select:
        selected_code = st.selectbox(
            t("deep_dive.select_label"),
            options=countries,
            format_func=lambda x: country_options.get(x, x),
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
                    title=t("deep_dive.chart_title"),
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
                st.warning(t("deep_dive.no_history"))

        with col_stats:
            # Show specific stats for this country
            row = df_map[df_map["geo_code"] == selected_code].iloc[0]

            # Confidence band line — only when both quantiles are present.
            band_html = ""
            p10 = row.get("predicted_risk_score_p10") if hasattr(row, "get") else None
            p90 = row.get("predicted_risk_score_p90") if hasattr(row, "get") else None
            if p10 is not None and p90 is not None and not pd.isna(p10) and not pd.isna(p90):
                band_html = (
                    f'<div style="color: #64748b; font-size: 0.85rem; margin-top:0.25rem;">'
                    f'P10–P90 : {float(p10):.1f} – {float(p90):.1f}'
                    f'</div>'
                )

            st.markdown(
                f"""
            <div class="metric-card">
                <div class="metric-label">{t("deep_dive.current_label")}</div>
                <div class="metric-value">{row["risk_score"]:.1f}</div>
                {band_html}
                <div style="color: #64748b; font-size: 0.9rem; margin-top:0.5rem;">
                    {t("deep_dive.assessment_prefix")} {row["date"].strftime("%b %Y")}
                </div>
            </div>
            """,
                unsafe_allow_html=True,
            )

            st.markdown("<br>", unsafe_allow_html=True)
            st.info(f"**{t('deep_dive.note_title')}**\n\n{t('deep_dive.note_body')}")

        # --- Per-nationality breakdown (top N) ---
        st.markdown("<br>", unsafe_allow_html=True)
        col_title, col_slider = st.columns([3, 1])
        with col_title:
            st.markdown(
                f'<div class="section-header"><span>🌐</span> {t("deep_dive.by_citizen_title")}</div>',
                unsafe_allow_html=True,
            )
        with col_slider:
            top_n = st.slider(
                t("deep_dive.by_citizen_slider"),
                min_value=3,
                max_value=10,
                value=5,
                key=f"top_n_{selected_code}",
            )

        df_by_cit = get_history_by_citizen(selected_code, top=top_n)
        if not df_by_cit.empty:
            df_by_cit["date"] = pd.to_datetime(df_by_cit["date"])
            df_by_cit = df_by_cit.sort_values(["date", "citizen_code"])

            fig_cit = px.area(
                df_by_cit,
                x="date",
                y="total",
                color="citizen_code",
                category_orders={
                    "citizen_code": (
                        df_by_cit.groupby("citizen_code")["total"]
                        .sum()
                        .sort_values(ascending=False)
                        .index.tolist()
                    )
                },
                color_discrete_sequence=px.colors.qualitative.Set2,
            )
            fig_cit.update_layout(
                title=t("deep_dive.by_citizen_chart_title"),
                xaxis_title="",
                yaxis_title="",
                hovermode="x unified",
                height=380,
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                yaxis=dict(gridcolor="#f1f5f9"),
                xaxis=dict(gridcolor="#f1f5f9"),
                legend=dict(title=t("deep_dive.by_citizen_legend")),
            )
            st.plotly_chart(fig_cit, use_container_width=True)
        else:
            st.warning(t("deep_dive.by_citizen_no_data"))

# --- About this data ---
st.markdown("<br><br>", unsafe_allow_html=True)
st.markdown(
    f'<div class="section-header"><span>ℹ️</span> {t("section.about")}</div>',
    unsafe_allow_html=True,
)

with st.expander(t("about.expander"), expanded=False):
    st.markdown(t("about.body"))

# --- Footer ---
st.markdown("<br><br><hr>", unsafe_allow_html=True)
st.markdown(
    f"""
<div style="text-align: center; color: #94a3b8; font-size: 0.8rem; padding: 2rem;">
    <strong>{t("footer.version")}</strong><br>
    {t("footer.last_update", code="migr_asyappctzm", date=datetime.now().strftime("%d %b %Y"))}
</div>
""",
    unsafe_allow_html=True,
)
