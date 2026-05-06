"""Lightweight internationalisation for the Streamlit dashboard.

Locale strings live in ``api_service/locales/{lang}.toml`` and are looked up
with dot-notation keys (``t("kpi.avg_risk")``). The active language is
resolved in this order:

1. ``?lang=`` URL query parameter, so deep links keep the chosen locale;
2. ``st.session_state["lang"]``, so the selector is sticky for the session;
3. the ``DASHBOARD_DEFAULT_LANG`` environment variable;
4. English as the final fallback.

When a key is missing in the selected locale we fall back to English rather
than surfacing a placeholder, so partial translations degrade gracefully.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any, Mapping

import streamlit as st

LOCALES_DIR = Path(__file__).parent / "locales"
SUPPORTED_LANGS = ("en", "et", "fr")
LANG_LABELS = {
    "en": "🇬🇧 English",
    "et": "🇪🇪 Eesti",
    "fr": "🇫🇷 Français",
}


def _default_lang() -> str:
    candidate = os.getenv("DASHBOARD_DEFAULT_LANG", "en").lower()
    return candidate if candidate in SUPPORTED_LANGS else "en"


@st.cache_data
def _load_locale(lang: str) -> Mapping[str, Any]:
    path = LOCALES_DIR / f"{lang}.toml"
    with open(path, "rb") as fh:
        return tomllib.load(fh)


def get_lang() -> str:
    """Return the currently active language code."""
    qp = st.query_params.get("lang")
    if qp in SUPPORTED_LANGS:
        st.session_state["lang"] = qp
        return qp
    if st.session_state.get("lang") in SUPPORTED_LANGS:
        return st.session_state["lang"]
    return _default_lang()


def set_lang(lang: str) -> None:
    if lang not in SUPPORTED_LANGS:
        return
    st.session_state["lang"] = lang
    st.query_params["lang"] = lang


def _lookup(locale: Mapping[str, Any], dotted_key: str) -> str | None:
    cursor: Any = locale
    for part in dotted_key.split("."):
        if not isinstance(cursor, Mapping) or part not in cursor:
            return None
        cursor = cursor[part]
    return cursor if isinstance(cursor, str) else None


def t(key: str, **format_kwargs: Any) -> str:
    """Translate ``key`` into the active language with optional ``str.format``
    interpolation. Falls back to English, then to the literal key."""
    lang = get_lang()
    value = _lookup(_load_locale(lang), key)
    if value is None and lang != "en":
        value = _lookup(_load_locale("en"), key)
    if value is None:
        return key
    if format_kwargs:
        try:
            return value.format(**format_kwargs)
        except (KeyError, IndexError):
            return value
    return value


def country_name(geo_code: str) -> str:
    """Localised country label for a Eurostat geo code (falls back to the code)."""
    return t(f"countries.{geo_code}") if geo_code else geo_code


def language_selector() -> str:
    """Render a language selector and return the active code.

    The selector is a native ``st.selectbox`` rendered without any
    layout wrapper — the caller decides placement (e.g. inside a column
    of the page header). It persists the chosen value via session state
    and rewrites the ``?lang=`` query param so the URL can be shared
    with the chosen locale.
    """
    current = get_lang()
    choice = st.selectbox(
        t("selector.label"),
        options=list(SUPPORTED_LANGS),
        format_func=lambda code: LANG_LABELS.get(code, code),
        index=SUPPORTED_LANGS.index(current),
        key="lang_selector",
        label_visibility="collapsed",
    )
    if choice != current:
        set_lang(choice)
        st.rerun()
    return choice
