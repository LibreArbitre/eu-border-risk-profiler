import streamlit as st
import requests
import pandas as pd
import plotly.express as px
import os

API_URL = os.getenv("API_URL", "http://localhost:8000")

st.set_page_config(page_title="EU Border Risk Profiler", layout="wide")

st.title("🇪🇺 EU Border Risk Profiler")
st.markdown("Monitoring and Forecasting Asylum Trends")

# Fetch Data
@st.cache_data(ttl=3600)
def get_predictions():
    try:
        r = requests.get(f"{API_URL}/api/v1/risk/predict")
        if r.status_code == 200:
            return pd.DataFrame(r.json())
        return pd.DataFrame()
    except Exception as e:
        st.error(f"API Error: {e}")
        return pd.DataFrame()

@st.cache_data(ttl=3600)
def get_latest():
    try:
        r = requests.get(f"{API_URL}/api/v1/risk/latest")
        if r.status_code == 200:
            return pd.DataFrame(r.json())
        return pd.DataFrame()
    except:
        return pd.DataFrame()

df_pred = get_predictions()
df_curr = get_latest()

col1, col2 = st.columns([2, 1])

with col1:
    st.subheader("Risk Map (Predicted)")
    if not df_pred.empty:
        # Get the first prediction month
        min_date = df_pred['date'].min()
        df_map = df_pred[df_pred['date'] == min_date].copy()

        # Simple ISO-2 to ISO-3 Mapper for Plotly (Partial)
        iso_map = {
            'AT':'AUT', 'BE':'BEL', 'BG':'BGR', 'CY':'CYP', 'CZ':'CZE', 'DE':'DEU', 'DK':'DNK',
            'EE':'EST', 'ES':'ESP', 'FI':'FIN', 'FR':'FRA', 'GR':'GRC', 'EL':'GRC', 'HR':'HRV',
            'HU':'HUN', 'IE':'IRL', 'IT':'ITA', 'LT':'LTU', 'LU':'LUX', 'LV':'LVA', 'MT':'MLT',
            'NL':'NLD', 'PL':'POL', 'PT':'PRT', 'RO':'ROU', 'SE':'SWE', 'SI':'SVN', 'SK':'SVK'
        }
        df_map['iso_alpha'] = df_map['geo_code'].map(iso_map).fillna(df_map['geo_code'])

        fig = px.choropleth(
            df_map,
            locations="iso_alpha",
            color="risk_score",
            scope="europe",
            color_continuous_scale="Reds",
            title=f"Predicted Risk Score - {min_date}"
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.warning("No prediction data available. Make sure Harvester and Predictor have run.")

with col2:
    st.subheader("Top Risk Countries")
    if not df_pred.empty:
        top = df_pred.groupby('geo_code')['risk_score'].mean().sort_values(ascending=False).head(10)
        st.dataframe(top)

# Drill down
st.subheader("Country Analysis")
if not df_curr.empty:
    countries = sorted(df_curr['geo_code'].unique())
    selected_country = st.selectbox("Select Country", countries)

    if selected_country:
        # Fetch history
        try:
            r = requests.get(f"{API_URL}/api/v1/data/history/{selected_country}")
            if r.status_code == 200:
                hist_data = r.json()
                df_hist = pd.DataFrame(hist_data)
                if not df_hist.empty:
                     df_hist['date'] = pd.to_datetime(df_hist['date'])
                     fig_line = px.line(df_hist, x='date', y='total', title=f"Asylum Applications History - {selected_country}")
                     st.plotly_chart(fig_line, use_container_width=True)
                else:
                    st.info("No history data found.")
            else:
                st.warning("Failed to fetch history.")
        except:
            st.error("Connection error.")
else:
    st.info("Waiting for data...")
