"""
EU Border Risk Profiler — analyst dashboard.

Single-page Streamlit app served alongside the FastAPI backend. The visual
identity intentionally stays restrained (institutional, not consumery) and
all human-facing strings are localised through ``api_service.i18n``.
"""

from __future__ import annotations

import os
from datetime import datetime

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st

from api_service.i18n import country_name, language_selector, t

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

API_URL = os.getenv("API_URL", "http://localhost:8000")
API_KEY = os.getenv("API_KEY") or None
_API_HEADERS = {"X-API-Key": API_KEY} if API_KEY else {}

# When set, an "API documentation" link is added to the footer pointing at
# {API_PUBLIC_URL}/docs (FastAPI Swagger UI). Leave unset to hide the link
# — useful when the API is only reachable on the internal Docker network.
API_PUBLIC_URL = os.getenv("API_PUBLIC_URL", "").rstrip("/")

REPO_URL = "https://github.com/LibreArbitre/eu-border-risk-profiler"

# ---------------------------------------------------------------------------
# Visual identity
# ---------------------------------------------------------------------------

PRIMARY = "#0f172a"          # slate-900, used for titles
ACCENT = "#b91c1c"           # red-700, used for "high risk" emphasis
NEUTRAL = "#64748b"          # slate-500, used for axes and labels
NEUTRAL_LIGHT = "#94a3b8"    # slate-400, used for captions
GRID = "#f1f5f9"             # slate-100, used for chart grids
SURFACE_BORDER = "#e2e8f0"   # slate-200, used for card and container borders
ACCENT_BLUE = "#1e3a8a"      # blue-900, used for the volume series

# 8-color qualitative palette — picked to stay readable when stacked and
# to keep adjacent slices distinguishable at the typical chart sizes.
CHART_PALETTE = [
    "#1e3a8a",  # blue-900
    "#b45309",  # amber-700
    "#7c3aed",  # violet-600
    "#0e7490",  # cyan-700
    "#15803d",  # green-700
    "#be185d",  # pink-700
    "#475569",  # slate-600
    "#a16207",  # yellow-700
]

# Sequential scale for the choropleth — neutral at the bottom, red at the top.
CHOROPLETH_SCALE = [
    [0.0, "#f1f5f9"],
    [0.3, "#fde68a"],
    [0.5, "#fbbf24"],
    [0.7, "#f97316"],
    [0.85, "#dc2626"],
    [1.0, "#7f1d1d"],
]

PLOTLY_LAYOUT_DEFAULTS = dict(
    font=dict(family="Inter, system-ui, sans-serif", size=12, color="#334155"),
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    margin=dict(l=10, r=10, t=40, b=20),
    title=dict(font=dict(size=14, color=PRIMARY), x=0.0, xanchor="left"),
    legend=dict(font=dict(size=11, color="#334155"), bgcolor="rgba(255,255,255,0)"),
    hoverlabel=dict(bgcolor="white", font_family="Inter"),
)
PLOTLY_AXIS_DEFAULTS = dict(
    gridcolor=GRID,
    linecolor="#cbd5e1",
    tickfont=dict(size=11, color=NEUTRAL),
    title_font=dict(size=11, color=NEUTRAL),
)


def apply_chart_theme(fig, *, height=None, with_legend=False):
    """Apply the dashboard's standard look to a Plotly figure in-place."""
    fig.update_layout(**PLOTLY_LAYOUT_DEFAULTS)
    fig.update_xaxes(**PLOTLY_AXIS_DEFAULTS)
    fig.update_yaxes(**PLOTLY_AXIS_DEFAULTS)
    if height is not None:
        fig.update_layout(height=height)
    fig.update_layout(showlegend=with_legend)
    return fig


def source_caption(source_text: str = "Eurostat — migr_asyappctzm") -> None:
    """Render the standard source citation under a chart."""
    st.markdown(
        f'<div class="source-caption">{t("common.source_label")} : {source_text}</div>',
        unsafe_allow_html=True,
    )


def section_title(label: str) -> None:
    """Render a section title with the dashboard's standard styling.

    Uses a styled ``<div>`` rather than an HTML heading tag because
    Streamlit auto-attaches anchor links to anything that looks like a
    heading inside a markdown block, which we don't want.
    """
    st.markdown(f'<div class="section-title">{label}</div>', unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Page setup
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="EU Border Risk Profiler",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="collapsed",
    menu_items={"Get Help": None, "Report a bug": None, "About": None},
)

st.markdown(
    """
<style>
    :root {
        --primary: #0f172a;
        --accent: #b91c1c;
        --neutral: #64748b;
        --neutral-light: #94a3b8;
        --border: #e2e8f0;
        --grid: #f1f5f9;
    }

    /* Use Inter consistently — Streamlit ships with it but mixes other faces. */
    html, body, [class*="css"], .stMarkdown, .stApp {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, system-ui, sans-serif;
    }

    /* Hide Streamlit chrome */
    #MainMenu, footer, header, .stDeployButton { visibility: hidden; display: none; }

    .main .block-container {
        padding-top: 1.5rem !important;
        padding-bottom: 3rem;
        max-width: 1280px;
    }

    /* Page title block (sits inside an outer column; the accent rule and
       hairline below the metadata strip are rendered as separate full-width
       elements so they span the whole page, not just the title column). */
    .page-title {
        font-size: 1.875rem;
        font-weight: 700;
        color: var(--primary);
        letter-spacing: -0.025em;
        margin: 0;
        line-height: 1.2;
    }
    .page-subtitle {
        color: var(--neutral);
        font-size: 0.95rem;
        margin: 0.35rem 0 0;
    }
    /* Metadata strip below the title — gives the header more
       informational density and a more "dashboard" feel. */
    .page-meta {
        color: var(--neutral-light);
        font-size: 0.78rem;
        margin: 0.65rem 0 0;
        font-variant-numeric: tabular-nums;
    }
    .page-meta .sep {
        color: var(--border);
        margin: 0 0.55rem;
    }

    /* Section title */
    .section-title {
        font-size: 0.85rem;
        font-weight: 600;
        color: var(--primary);
        text-transform: uppercase;
        letter-spacing: 0.06em;
        margin: 1.75rem 0 0.85rem;
        padding-bottom: 0.5rem;
        border-bottom: 1px solid var(--border);
    }

    /* Metric cards */
    .metric-card {
        background: #ffffff;
        border: 1px solid var(--border);
        border-radius: 4px;
        padding: 1rem 1.15rem;
    }
    .metric-label {
        color: var(--neutral);
        font-size: 0.7rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        margin-bottom: 0.45rem;
    }
    .metric-value {
        color: var(--primary);
        font-size: 1.7rem;
        font-weight: 700;
        line-height: 1.1;
        letter-spacing: -0.025em;
    }
    .metric-value-accent { color: var(--accent); }
    .metric-sub {
        color: var(--neutral-light);
        font-size: 0.75rem;
        margin-top: 0.5rem;
    }

    /* Chart source line */
    .source-caption {
        font-size: 0.72rem;
        color: var(--neutral-light);
        margin: -0.35rem 0 1.25rem;
        font-style: italic;
    }

    /* Footer */
    .app-footer {
        text-align: center;
        color: var(--neutral-light);
        font-size: 0.78rem;
        padding: 1.5rem 0 0.5rem;
        border-top: 1px solid var(--border);
        margin-top: 3rem;
        line-height: 1.7;
    }
    .app-footer a {
        color: var(--neutral);
        text-decoration: none;
    }
    .app-footer a:hover {
        color: var(--primary);
        text-decoration: underline;
    }
    .app-footer .sep {
        color: var(--border);
        margin: 0 0.45rem;
    }

    /* Tables */
    div[data-testid="stDataFrame"] {
        border: 1px solid var(--border);
        border-radius: 4px;
        background: white;
    }

    /* Tighten the language selector */
    div[data-testid="stHorizontalBlock"] div[data-baseweb="select"] > div {
        font-size: 0.85rem;
    }
</style>
""",
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------


@st.cache_data(ttl=60)
def get_predictions():
    try:
        r = requests.get(f"{API_URL}/api/v1/risk/predict", timeout=10, headers=_API_HEADERS)
        if r.status_code == 200:
            return pd.DataFrame(r.json())
        return pd.DataFrame()
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=60)
def get_latest():
    try:
        r = requests.get(f"{API_URL}/api/v1/risk/latest", timeout=10, headers=_API_HEADERS)
        if r.status_code == 200:
            return pd.DataFrame(r.json())
        return pd.DataFrame()
    except Exception:
        return pd.DataFrame()


def get_history(geo_code: str):
    try:
        r = requests.get(
            f"{API_URL}/api/v1/data/history/{geo_code}",
            timeout=10,
            headers=_API_HEADERS,
        )
        if r.status_code == 200:
            return pd.DataFrame(r.json())
        return pd.DataFrame()
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=60)
def get_history_by_citizen(geo_code: str, top: int = 5, since: str | None = None):
    try:
        params: dict = {"top": top}
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


# ISO-2 to ISO-3 mapping for Plotly choropleth.
# Country names are localised via api_service.i18n.country_name().
ISO_MAP = {
    "AT": "AUT", "BE": "BEL", "BG": "BGR", "CY": "CYP", "CZ": "CZE",
    "DE": "DEU", "DK": "DNK", "EE": "EST", "ES": "ESP", "FI": "FIN",
    "FR": "FRA", "GR": "GRC", "EL": "GRC", "HR": "HRV", "HU": "HUN",
    "IE": "IRL", "IT": "ITA", "LT": "LTU", "LU": "LUX", "LV": "LVA",
    "MT": "MLT", "NL": "NLD", "PL": "POL", "PT": "PRT", "RO": "ROU",
    "SE": "SWE", "SI": "SVN", "SK": "SVK",
}

# ---------------------------------------------------------------------------
# Data loading + df_map computation (must happen before the header so the
# metadata strip can quote the actual data range and country count).
# ---------------------------------------------------------------------------

df_pred = get_predictions()
if not df_pred.empty:
    df_pred["date"] = pd.to_datetime(df_pred["date"])
    df_pred["prediction_target_month"] = pd.to_datetime(df_pred["prediction_target_month"])

df_curr = get_latest()

valid_data = False
df_map = pd.DataFrame()

if not df_pred.empty:
    latest_dates = df_pred.groupby("geo_code")["date"].max().reset_index()
    merged = pd.merge(df_pred, latest_dates, on=["geo_code", "date"])

    agg_spec: dict = {
        "risk_score_calculated": "first",
        "predicted_risk_score": "mean",
        "date": "first",
    }
    if "predicted_risk_score_p10" in merged.columns:
        agg_spec["predicted_risk_score_p10"] = "mean"
    if "predicted_risk_score_p90" in merged.columns:
        agg_spec["predicted_risk_score_p90"] = "mean"

    df_map = merged.groupby("geo_code").agg(agg_spec).reset_index()
    df_map["risk_score"] = df_map["predicted_risk_score"]
    valid_data = True

# ---------------------------------------------------------------------------
# Header — primary-coloured accent rule, then a row with title + language
# selector, then a metadata strip, then a hairline closing the header band.
# ---------------------------------------------------------------------------

# Primary accent rule above the header (full-width).
st.markdown(
    '<div style="height:3px;background:#1e3a8a;margin:-0.5rem 0 1rem;"></div>',
    unsafe_allow_html=True,
)

# Title block (left) + language selector (right).
col_title, col_lang = st.columns([5, 1])
with col_title:
    st.markdown(
        f"""
<div>
    <div class="page-title">{t("header.title")}</div>
    <div class="page-subtitle">{t("header.subtitle")}</div>
</div>
""",
        unsafe_allow_html=True,
    )
with col_lang:
    language_selector()

# Metadata strip (full-width) — renders even when data isn't loaded yet so
# the layout stays stable; the date range is just omitted in that case.
meta_parts: list = []
if valid_data:
    src_min = df_pred["date"].min()
    src_max = df_pred["date"].max()
    if pd.notna(src_min) and pd.notna(src_max):
        meta_parts.append(f"{src_min.strftime('%Y-%m')} → {src_max.strftime('%Y-%m')}")
    meta_parts.append(f"{int(df_map['geo_code'].nunique())} {t('header.meta_countries')}")
meta_parts.append("Eurostat — migr_asyappctzm")

meta_html = '<span class="sep">·</span>'.join(meta_parts)
st.markdown(
    f'<div class="page-meta">{meta_html}</div>'
    f'<hr style="border:none;border-top:1px solid #e2e8f0;margin:0.6rem 0 1.5rem;" />',
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# KPI metrics row
# ---------------------------------------------------------------------------

if valid_data:
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
                <div class="metric-value metric-value-accent">{max_risk:.1f}</div>
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

# ---------------------------------------------------------------------------
# Heatmap + ranking (with click-to-select)
# ---------------------------------------------------------------------------

col_map, col_ranking = st.columns([2, 1])

with col_map:
    section_title(t("section.heatmap"))

    if valid_data:
        df_map["iso_alpha"] = df_map["geo_code"].map(ISO_MAP)
        df_map["country_name"] = df_map["geo_code"].map(country_name)

        fig = px.choropleth(
            df_map,
            locations="iso_alpha",
            color="risk_score",
            scope="europe",
            color_continuous_scale=CHOROPLETH_SCALE,
            range_color=[0, 100],
            hover_name="country_name",
            hover_data={"iso_alpha": False, "risk_score": ":.1f", "geo_code": False},
            labels={"risk_score": t("map.risk_label")},
        )
        fig.update_geos(
            showcoastlines=True,
            coastlinecolor="#cbd5e1",
            showland=True,
            landcolor="#f8fafc",
            showocean=True,
            oceancolor="#ffffff",
            showlakes=True,
            lakecolor="#ffffff",
            showframe=False,
            showcountries=True,
            countrycolor="#ffffff",
            projection_type="mercator",
            center={"lat": 54, "lon": 15},
            lataxis_range=[35, 72],
            lonaxis_range=[-12, 45],
        )
        fig.update_layout(
            margin={"r": 0, "t": 0, "l": 0, "b": 0},
            coloraxis_colorbar={
                "title": t("map.risk_label"),
                "thickness": 10,
                "len": 0.55,
                "x": 0.02,
                "y": 0.5,
                "tickfont": {"color": NEUTRAL, "size": 11},
                "title_font": {"color": NEUTRAL, "size": 11},
            },
            height=520,
            paper_bgcolor="rgba(0,0,0,0)",
            geo_bgcolor="rgba(0,0,0,0)",
            font=dict(family="Inter, system-ui, sans-serif"),
        )
        st.plotly_chart(fig, use_container_width=True)
        source_caption()
    else:
        st.info(t("map.initializing"))

with col_ranking:
    section_title(t("section.ranking"))

    if valid_data:
        ranking = df_map[["geo_code", "risk_score"]].copy()
        ranking = ranking.sort_values("risk_score", ascending=False)
        ranking["Country"] = ranking["geo_code"].map(country_name)
        ranking = ranking.reset_index(drop=True)
        ranking.columns = ["Code", "Score", "Country"]
        ranking.index = ranking.index + 1

        final_ranking = ranking[["Country", "Score"]]

        # Click-to-select: when the user picks a row, propagate the
        # underlying geo_code into st.session_state["deep_dive_geo"] BEFORE
        # the deep-dive selectbox renders below — the selectbox is keyed on
        # the same name and will pick up the new value as its default.
        ranking_event = st.dataframe(
            final_ranking,
            use_container_width=True,
            height=520,
            column_config={
                "Country": st.column_config.TextColumn(
                    t("ranking.country"), width="medium"
                ),
                "Score": st.column_config.ProgressColumn(
                    t("ranking.risk_index"),
                    format="%.1f",
                    min_value=0,
                    max_value=100,
                ),
            },
            on_select="rerun",
            selection_mode="single-row",
            key="ranking_selection",
        )
        if (
            ranking_event
            and getattr(ranking_event, "selection", None)
            and ranking_event.selection.get("rows")
        ):
            picked_idx = ranking_event.selection["rows"][0]
            picked_code = ranking.iloc[picked_idx]["Code"]
            if st.session_state.get("deep_dive_geo") != picked_code:
                st.session_state["deep_dive_geo"] = picked_code
    else:
        st.info(t("ranking.no_data"))

# ---------------------------------------------------------------------------
# Country deep-dive
# ---------------------------------------------------------------------------

section_title(t("section.deep_dive"))

if valid_data:
    countries = sorted(df_map["geo_code"].unique())
    country_options = {code: f"{country_name(code)} ({code})" for code in countries}

    # Initialise the session-state default if absent.
    if "deep_dive_geo" not in st.session_state:
        st.session_state["deep_dive_geo"] = countries[0]
    elif st.session_state["deep_dive_geo"] not in countries:
        st.session_state["deep_dive_geo"] = countries[0]

    col_select, _ = st.columns([1, 2])
    with col_select:
        st.selectbox(
            t("deep_dive.select_label"),
            options=countries,
            format_func=lambda x: country_options.get(x, x),
            key="deep_dive_geo",
        )
    selected_code = st.session_state["deep_dive_geo"]

    if selected_code:
        col_hist, col_stats = st.columns([2, 1])

        df_hist = get_history(selected_code)

        with col_hist:
            if not df_hist.empty:
                df_hist["date"] = pd.to_datetime(df_hist["date"])
                df_hist = df_hist.sort_values("date")

                fig_line = go.Figure()
                fig_line.add_trace(
                    go.Scatter(
                        x=df_hist["date"],
                        y=df_hist["total"],
                        mode="lines",
                        fill="tozeroy",
                        name="Applications",
                        line=dict(color=ACCENT_BLUE, width=2),
                        fillcolor="rgba(30, 58, 138, 0.08)",
                    )
                )
                fig_line.update_layout(
                    title=t("deep_dive.chart_title"),
                    hovermode="x unified",
                )
                apply_chart_theme(fig_line, height=320)
                st.plotly_chart(fig_line, use_container_width=True)
                source_caption()
            else:
                st.warning(t("deep_dive.no_history"))

        with col_stats:
            row = df_map[df_map["geo_code"] == selected_code].iloc[0]

            band_html = ""
            p10 = row.get("predicted_risk_score_p10") if hasattr(row, "get") else None
            p90 = row.get("predicted_risk_score_p90") if hasattr(row, "get") else None
            if (
                p10 is not None
                and p90 is not None
                and not pd.isna(p10)
                and not pd.isna(p90)
            ):
                band_html = (
                    f'<div class="metric-sub">'
                    f"P10–P90 : {float(p10):.1f} – {float(p90):.1f}"
                    f"</div>"
                )

            st.markdown(
                f"""
                <div class="metric-card">
                    <div class="metric-label">{t("deep_dive.current_label")}</div>
                    <div class="metric-value">{row["risk_score"]:.1f}</div>
                    {band_html}
                    <div class="metric-sub">
                        {t("deep_dive.assessment_prefix")} {row["date"].strftime("%b %Y")}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            st.markdown("<br>", unsafe_allow_html=True)
            st.markdown(
                f"<div style='font-size:0.85rem; color:{NEUTRAL}; line-height:1.55;'>"
                f"<strong>{t('deep_dive.note_title')}</strong><br>"
                f"{t('deep_dive.note_body')}"
                f"</div>",
                unsafe_allow_html=True,
            )

        # --- Per-nationality breakdown (top N) ---
        st.markdown("<div style='height:1.5rem'></div>", unsafe_allow_html=True)
        col_title, col_n = st.columns([4, 1])
        with col_title:
            section_title(t("deep_dive.by_citizen_title"))
        with col_n:
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

            citizen_order = (
                df_by_cit.groupby("citizen_code")["total"]
                .sum()
                .sort_values(ascending=False)
                .index.tolist()
            )

            fig_cit = px.area(
                df_by_cit,
                x="date",
                y="total",
                color="citizen_code",
                category_orders={"citizen_code": citizen_order},
                color_discrete_sequence=CHART_PALETTE,
            )
            fig_cit.update_layout(
                title=t("deep_dive.by_citizen_chart_title"),
                hovermode="x unified",
                legend=dict(title=dict(text=t("deep_dive.by_citizen_legend"))),
            )
            apply_chart_theme(fig_cit, height=380, with_legend=True)
            st.plotly_chart(fig_cit, use_container_width=True)
            source_caption()
        else:
            st.warning(t("deep_dive.by_citizen_no_data"))

# ---------------------------------------------------------------------------
# About this data
# ---------------------------------------------------------------------------

section_title(t("section.about"))

with st.expander(t("about.expander"), expanded=False):
    st.markdown(t("about.body"))

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------

footer_links = [
    f'<a href="{REPO_URL}">{t("footer.github")}</a>',
]
if API_PUBLIC_URL:
    footer_links.append(
        f'<a href="{API_PUBLIC_URL}/docs">{t("footer.api_docs")}</a>'
    )
links_html = '<span class="sep">·</span>'.join(footer_links)

st.markdown(
    f"""
<div class="app-footer">
    <strong>{t("footer.version")}</strong>
    <br>
    {t("footer.last_update", code="migr_asyappctzm", date=datetime.now().strftime("%d %b %Y"))}
    <br>
    {links_html}
</div>
""",
    unsafe_allow_html=True,
)
