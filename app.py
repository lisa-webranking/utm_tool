import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import os
import json
import hashlib
import hmac
from datetime import datetime, timedelta
from slugify import slugify
from urllib.parse import urlparse, parse_qs, parse_qsl, urlencode, urlunparse
from io import BytesIO

import re
import html as html_lib  # per escapare valori UTM nell'HTML
from pathlib import Path

# Google Auth & Analytics import os
import google.auth
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.analytics.admin import AnalyticsAdminServiceClient
from google.analytics.data import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import RunReportRequest, DateRange, Metric, Dimension, OrderBy

import google.generativeai as genai
from googleapi import get_persistent_api_key, save_persistent_api_key, get_user_email
import ga4_mcp_tools # Import tools module
from functools import partial

# Import new Chatbot UI
from chatbot_ui import render_chatbot_interface

# --- CONFIGURAZIONE ---
st.set_page_config(page_title="Universal UTM Governance", layout="wide")


def _get_config_value(name: str) -> str:
    env_val = os.getenv(name, "").strip()
    if env_val:
        return env_val
    try:
        return str(st.secrets.get(name, "")).strip()
    except Exception:
        return ""


CLIENT_LINK_SECRET = _get_config_value("CLIENT_LINK_SECRET")
CLIENT_CONFIG_DIR = Path(__file__).with_name("client_configs")

# --- CSS (STILE CLEAN + CHECKER CORRETTO) ---
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Space+Grotesk:wght@500;600;700&display=swap');

    :root {
        --bg-soft: #f8fafc;
        --surface: #ffffff;
        --surface-soft: #f6f9fc;
        --ink: #141d2d;
        --muted: #5c6b80;
        --line: #dfe6ee;
        --brand: #141d2d;
        --brand-strong: #101827;
        --accent: #66c6ac;
        --accent-soft: rgba(102, 198, 172, 0.14);
        --ok: #188038;
        --warn: #e37400;
        --danger: #d93025;
    }

    .stApp {
        background: var(--bg-soft);
        font-family: "DM Sans", "Segoe UI", Arial, sans-serif;
    }

    .block-container {
        max-width: 1260px;
        margin: 0 auto;
        padding-top: 0.35rem;
        padding-left: 1.15rem;
        padding-right: 1.15rem;
        padding-bottom: 2rem;
    }

    .lovable-topbar {
        display: flex;
        align-items: center;
        justify-content: flex-start;
        padding: 6px 0;
        margin-bottom: 8px;
        min-height: 40px;
    }

    .lovable-brand {
        display: inline-flex;
        align-items: center;
        gap: 10px;
    }

    .lovable-badge-w {
        width: 34px;
        height: 34px;
        border-radius: 10px;
        background: linear-gradient(140deg, #85dcc5, #69c9bb);
        color: #103a34;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        font-family: "Space Grotesk", sans-serif;
        font-weight: 700;
        box-shadow: 0 8px 18px rgba(89, 198, 177, 0.28);
    }

    .lovable-title {
        font-family: "Space Grotesk", sans-serif;
        font-size: 14px;
        font-weight: 700;
        color: var(--ink);
        letter-spacing: 0.03em;
    }

    .lovable-beta {
        display: inline-flex;
        margin-left: 8px;
        padding: 2px 8px;
        border-radius: 999px;
        background: #d8f3ea;
        color: #3f9d8d;
        font-size: 10px;
        font-weight: 700;
        letter-spacing: 0.3px;
        text-transform: uppercase;
    }

    .lovable-docs-link {
        height: 48px;
        display: flex;
        align-items: center;
        justify-content: center;
        color: var(--muted);
        font-size: 14px;
        font-weight: 500;
    }

    [data-testid="stPopover"] > button {
        height: 48px;
        border-radius: 12px !important;
        background: var(--surface) !important;
        border: 1px solid #d8dee8 !important;
        color: #1f2937 !important;
        font-weight: 600 !important;
        box-shadow: 0 1px 1px rgba(16, 24, 40, 0.06);
    }

    .top-shell {
        background: var(--surface);
        border: 1px solid #dbe5f0;
        border-radius: 14px;
        box-shadow: 0 4px 14px rgba(20, 36, 52, 0.06);
        padding: 16px 18px;
        margin-bottom: 14px;
    }
    .top-shell-empty {
        min-height: 8px;
    }

    .top-shell .title {
        color: #1d2731;
        font-size: 30px;
        font-weight: 700;
        margin: 0 0 4px 0;
    }

    .top-shell .subtitle {
        color: #506172;
        font-size: 14px;
        margin: 0;
    }

    .user-pill {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        border: 1px solid #d4e1ee;
        border-radius: 999px;
        background: #f4f8fc;
        color: #2f455a;
        padding: 6px 10px;
        font-size: 12px;
        font-weight: 600;
    }

    .user-avatar {
        width: 24px;
        height: 24px;
        border-radius: 50%;
        background: linear-gradient(140deg, #1f8fff, #50e3c2);
        color: #082b46;
        font-weight: 800;
        display: inline-flex;
        align-items: center;
        justify-content: center;
    }

    /* 1. Header Sezioni */
    .section-header {
        font-size: 15px; font-weight: 800; color: #213142; margin-top: 0; margin-bottom: 10px;
        text-transform: none; letter-spacing: .2px; font-family: sans-serif;
    }
    
    /* 2. Messaggi Validazione */
    .msg-error { color: var(--danger); font-size: 13px; margin-top: -5px; margin-bottom: 5px; display: flex; align-items: center; gap: 5px; }
    .msg-warning { color: var(--warn); font-size: 13px; margin-top: -5px; margin-bottom: 5px; display: flex; align-items: center; gap: 5px; }
    .msg-success { color: var(--ok); font-size: 13px; margin-top: -5px; margin-bottom: 5px; display: flex; align-items: center; gap: 5px; font-weight: 500; }
    
    /* 3. Output Box Builder */
    .output-box-ready { background-color: #e8f0fe; color: #174ea6; padding: 15px; border-radius: 8px; border: 1px solid #d2e3fc; }
    .output-box-success { background-color: #e6f4ea; color: #137333; padding: 15px; border-radius: 8px; border: 1px solid #ceead6; }

    .hero {
        position: relative;
        background: var(--brand);
        border: 0;
        border-radius: 0;
        width: 100vw;
        margin-left: calc(50% - 50vw);
        margin-right: calc(50% - 50vw);
        padding: 64px 0 56px 0;
        box-shadow: none;
        margin-top: 4px;
        margin-bottom: 18px;
        text-align: center;
        overflow: hidden;
    }

    .hero::before {
        content: "";
        position: absolute;
        inset: 0;
        background-image:
            linear-gradient(rgba(255, 255, 255, 0.045) 1px, transparent 1px),
            linear-gradient(90deg, rgba(255, 255, 255, 0.045) 1px, transparent 1px);
        background-size: 60px 60px;
        opacity: 0.55;
        pointer-events: none;
    }

    .hero::after {
        display: none;
    }

    .hero > * {
        position: relative;
        z-index: 1;
    }

    .hero-status {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        border-radius: 999px;
        border: 1px solid rgba(102, 198, 172, 0.24);
        background: rgba(102, 198, 172, 0.12);
        color: var(--accent);
        font-size: 12px;
        font-weight: 500;
        padding: 6px 16px;
        margin-bottom: 20px;
        margin-left: auto;
        margin-right: auto;
    }

    .hero-title {
        font-size: 56px;
        line-height: 1.08;
        font-weight: 700;
        font-family: "Space Grotesk", sans-serif;
        color: #f7fbff;
        margin-bottom: 14px;
        letter-spacing: -0.02em;
        padding-left: 24px;
        padding-right: 24px;
    }

    .hero-title-accent {
        position: relative;
        display: inline-block;
        margin-left: 10px;
        color: var(--accent);
    }

    .hero-title-accent::after {
        content: "";
        position: absolute;
        left: 0;
        right: 0;
        bottom: -5px;
        height: 9px;
        border-bottom: 2px solid rgba(102, 198, 172, 0.55);
        border-radius: 50% 50% 60% 40%;
    }

    .hero-sub {
        font-size: 12px;
        color: rgba(235, 243, 252, 0.7);
        font-weight: 600;
        margin-bottom: 0;
        text-transform: none;
        padding-left: 24px;
        padding-right: 24px;
    }

    .hero-desc {
        max-width: 640px;
        margin: 0 auto 32px auto;
        font-size: 16px;
        color: rgba(241, 246, 255, 0.84);
        font-weight: 500;
        line-height: 1.55;
        padding-left: 24px;
        padding-right: 24px;
    }

    .assistant-cta {
        margin: 0 auto 14px auto;
        width: 100%;
        display: block;
        gap: 16px;
        border: 1px solid rgba(102, 198, 172, 0.42);
        background: rgba(55, 72, 88, 0.92);
        border-radius: 16px;
        padding: 4px;
        box-shadow:
            0 0 0 1px rgba(102, 198, 172, 0.08),
            0 10px 20px rgba(10, 18, 32, 0.32),
            0 18px 26px rgba(67, 216, 186, 0.18);
    }

    .assistant-cta-link {
        display: block;
        width: 500px;
        max-width: calc(100% - 48px);
        margin: 0 auto;
        text-decoration: none !important;
        color: inherit !important;
        cursor: pointer;
        user-select: none;
    }

    .assistant-cta-link:hover .assistant-cta {
        border-color: rgba(117, 226, 201, 0.76);
        box-shadow:
            0 0 0 1px rgba(117, 226, 201, 0.16),
            0 14px 26px rgba(9, 16, 28, 0.42),
            0 22px 34px rgba(77, 224, 196, 0.3);
    }

    .assistant-cta-inner {
        position: relative;
        width: 100%;
        box-sizing: border-box;
        display: flex;
        align-items: center;
        gap: 16px;
        border-radius: 12px;
        padding: 18px 24px;
        background: rgba(255, 255, 255, 0.03);
    }

    .assistant-cta-icon {
        width: 56px;
        height: 56px;
        border-radius: 16px;
        background: var(--accent);
        color: #1a2432;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        font-size: 24px;
        font-weight: 800;
        position: relative;
        box-shadow: 0 10px 22px rgba(102, 198, 172, 0.34);
    }

    .assistant-cta-sparkle {
        position: absolute;
        top: -8px;
        right: -8px;
        width: 20px;
        height: 20px;
        border-radius: 999px;
        background: var(--surface);
        color: #0f2b48;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        font-size: 12px;
        font-weight: 800;
        box-shadow: 0 0 0 0 rgba(168, 235, 217, 0.5);
        animation: sparklePulse 1.8s ease-in-out infinite;
    }

    @keyframes sparklePulse {
        0% {
            transform: scale(0.94);
            box-shadow: 0 0 0 0 rgba(168, 235, 217, 0.5);
        }
        50% {
            transform: scale(1.12);
            box-shadow: 0 0 0 10px rgba(168, 235, 217, 0.0);
        }
        100% {
            transform: scale(0.94);
            box-shadow: 0 0 0 0 rgba(168, 235, 217, 0.0);
        }
    }

    .assistant-cta-body {
        flex: 1;
        text-align: left;
    }

    .assistant-cta-title {
        color: #eef6ff;
        font-size: 19px;
        font-weight: 700;
        margin-bottom: 2px;
        font-family: "Space Grotesk", sans-serif;
        line-height: 1.2;
    }

    .assistant-cta-copy {
        color: rgba(229, 238, 251, 0.54);
        font-size: 14px;
        font-weight: 500;
    }

    .assistant-cta-arrow {
        width: 40px;
        height: 40px;
        border-radius: 12px;
        border: 0;
        color: var(--accent);
        background: rgba(102, 198, 172, 0.2);
        display: inline-flex;
        align-items: center;
        justify-content: center;
        font-size: 20px;
    }

    .feature-grid {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 12px;
        margin: 40px 0 0 0;
        max-width: 1140px;
        margin-left: auto;
        margin-right: auto;
        padding-left: 24px;
        padding-right: 24px;
    }

    .feature-card {
        background: rgba(255, 255, 255, 0.03);
        border: 1px solid rgba(241, 246, 255, 0.07);
        border-radius: 16px;
        padding: 20px;
        min-height: 178px;
        box-shadow: none;
        backdrop-filter: blur(4px);
    }

    .feature-icon {
        width: 40px;
        height: 40px;
        border-radius: 12px;
        background: rgba(102, 198, 172, 0.16);
        color: var(--accent);
        display: inline-flex;
        align-items: center;
        justify-content: center;
        margin-bottom: 12px;
    }

    .feature-title {
        font-size: 14px;
        font-weight: 600;
        color: #f1f7ff;
        margin-bottom: 6px;
        font-family: "Space Grotesk", sans-serif;
        line-height: 1.35;
    }

    .feature-copy {
        font-size: 12px;
        color: rgba(229, 238, 251, 0.45);
        line-height: 1.6;
    }

    div[data-testid="stTabs"] [data-baseweb="tab-list"] {
        justify-content: center;
        gap: 2px;
        background: var(--surface);
        border: 1px solid var(--line);
        border-radius: 16px;
        padding: 4px 6px;
        width: fit-content;
        margin: 20px auto 16px auto;
    }

    div[data-testid="stTabs"] [data-baseweb="tab"] {
        border-radius: 12px;
        padding: 8px 18px;
        font-weight: 600;
        font-size: 14px;
        color: var(--muted);
    }

    div[data-testid="stTabs"] [aria-selected="true"] {
        background: var(--brand) !important;
        color: #ffffff !important;
    }

    .step-label {
        display: inline-block;
        font-size: 11px;
        letter-spacing: .5px;
        font-weight: 700;
        color: #27537e;
        background: #eaf3ff;
        border: 1px solid #cadef7;
        border-radius: 8px;
        padding: 4px 8px;
        margin: 2px 0 8px 0;
        text-transform: uppercase;
    }

    .form-card {
        background: var(--surface);
        border: 1px solid var(--line);
        border-radius: 16px;
        padding: 20px;
        margin-bottom: 16px;
        box-shadow: 0 1px 2px rgba(15, 23, 42, 0.06);
    }

    .sticky-panel {
        position: sticky;
        top: 80px;
    }

    .output-card {
        background: var(--surface);
        border: 1px solid var(--line);
        border-radius: 12px;
        padding: 14px;
        box-shadow: 0 2px 8px rgba(20, 36, 52, 0.04);
    }

    .param-chip-row {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        margin: 10px 0 0 0;
    }

    .param-chip {
        display: inline-flex;
        align-items: center;
        padding: 5px 8px;
        border-radius: 8px;
        font-size: 12px;
        font-weight: 600;
        border: 1px solid transparent;
    }

    .param-chip.source { background: #e7f5ef; border-color: #cdebdc; color: #1b6b45; }
    .param-chip.medium { background: #ebefff; border-color: #d5defd; color: #3a4ea8; }
    .param-chip.campaign { background: #fff3e7; border-color: #ffe2c2; color: #8a4f11; }
    .param-chip.content { background: #f0f3f6; border-color: #dfe6ee; color: #465465; }

    .tilda-panel {
        background: var(--surface);
        border: 1px solid var(--line);
        border-radius: 16px;
        padding: 20px;
        margin-top: 8px;
        box-shadow: 0 1px 2px rgba(15, 23, 42, 0.06);
    }

    .tilda-title {
        font-size: 34px;
        font-weight: 700;
        color: var(--ink);
        margin-bottom: 4px;
        letter-spacing: 0;
        font-family: "Space Grotesk", sans-serif;
    }

    .tilda-sub {
        font-size: 14px;
        color: var(--muted);
        margin-bottom: 16px;
    }

    .tilda-section {
        font-size: 20px;
        font-weight: 600;
        color: var(--ink);
        margin: 14px 0 8px 0;
        font-family: "Space Grotesk", sans-serif;
    }

    .tilda-note {
        font-size: 13px;
        color: #4a627a;
        margin: 4px 0 10px 0;
    }

    .builder-head {
        display: flex;
        align-items: flex-end;
        justify-content: space-between;
        gap: 12px;
        margin-bottom: 22px;
    }

    .builder-head-title {
        font-family: "Space Grotesk", sans-serif;
        font-size: 30px;
        font-weight: 700;
        color: var(--ink);
        line-height: 1.2;
        margin: 0;
        letter-spacing: -0.01em;
    }

    .builder-head-sub {
        font-size: 14px;
        color: var(--muted);
        margin-top: 2px;
    }

    .builder-head-right {
        display: inline-flex;
        align-items: center;
        gap: 10px;
        margin-bottom: 2px;
    }

    .builder-required-pill {
        border-radius: 999px;
        padding: 6px 12px;
        background: rgba(102, 198, 172, 0.14);
        color: #5bbda6;
        font-size: 12px;
        font-weight: 600;
        border: 1px solid rgba(102, 198, 172, 0.2);
    }

    .builder-reset {
        color: var(--muted);
        font-size: 14px;
        font-weight: 500;
    }

    .builder-card {
        background: var(--surface);
        border: 1px solid var(--line);
        border-radius: 16px;
        padding: 20px;
        margin: 0 0 20px 0;
        box-shadow: 0 1px 2px rgba(15, 23, 42, 0.06);
    }

    div[data-testid="stVerticalBlockBorderWrapper"]:has(.builder-box-marker) {
        background: var(--surface) !important;
        border: 1px solid var(--line) !important;
        border-radius: 16px !important;
        box-shadow: 0 1px 2px rgba(15, 23, 42, 0.06) !important;
        padding: 18px 18px 14px 18px !important;
        margin: 0 0 20px 0 !important;
    }

    div[data-testid="stVerticalBlockBorderWrapper"]:has(.builder-box-marker) > div {
        background: transparent !important;
    }

    div[data-testid="stVerticalBlockBorderWrapper"]:has(.builder-box-marker) div[data-testid="stTextInput"] input,
    div[data-testid="stVerticalBlockBorderWrapper"]:has(.builder-box-marker) div[data-baseweb="select"] > div,
    div[data-testid="stVerticalBlockBorderWrapper"]:has(.builder-box-marker) div[data-testid="stDateInput"] input {
        background: #f5f8fb !important;
        border-color: #d1d9e4 !important;
        color: var(--ink) !important;
        border-radius: 12px !important;
    }

    .builder-card-title {
        display: inline-flex;
        align-items: center;
        gap: 10px;
        font-family: "Space Grotesk", sans-serif;
        color: var(--ink);
        font-size: 14px;
        font-weight: 600;
        margin-bottom: 12px;
    }

    .builder-box-marker {
        display: none;
    }

    .builder-icon-dot {
        width: 26px;
        height: 26px;
        border-radius: 9px;
        background: #eef7f3;
        color: #6abda8;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        font-size: 13px;
        font-weight: 600;
    }

    .builder-step-dot {
        width: 20px;
        height: 20px;
        border-radius: 999px;
        background: var(--brand);
        color: #ffffff;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        font-size: 11px;
        font-weight: 700;
    }

    .builder-subhead {
        display: flex;
        align-items: center;
        gap: 10px;
        font-size: 12px;
        font-weight: 600;
        color: #4b5563;
        margin: 10px 0 12px 0;
        text-transform: uppercase;
        letter-spacing: 0.09em;
        font-family: "DM Sans", sans-serif;
    }

    .builder-subhead::after {
        content: "";
        flex: 1;
        height: 1px;
        background: #dbe3ed;
    }

    .builder-naming-link {
        text-align: right;
        font-size: 13px;
        color: #6abda8;
        font-weight: 600;
        margin-top: 2px;
    }
    
    /* 4. STILE UTM CHECKER (Riproduzione Screenshot) */
    .utm-check-card {
        background-color: white;
        border: 1px solid #e0e0e0;
        border-radius: 5px;
        box-shadow: 0 1px 2px rgba(0,0,0,0.05);
        margin-top: 15px;
        overflow: hidden; /* Importante per i bordi */
    }
    
    .utm-row {
        display: flex;
        align-items: center;
        border-bottom: 1px solid #e9ecef;
        padding: 12px 15px;
    }
    
    .utm-row:last-child {
        border-bottom: none;
    }
    
    /* Colonna Etichetta (Tag) */
    .utm-label-col {
        width: 160px;
        flex-shrink: 0;
    }
    
    .utm-tag {
        display: inline-block;
        padding: 6px 12px;
        border-radius: 4px;
        color: white;
        font-weight: 600;
        font-size: 13px;
        text-align: center;
        min-width: 110px;
    }
    
    .tag-blue { background-color: #0077c8; } 
    .tag-gray { background-color: #6c757d; } 
    
    /* Colonna Valore */
    .utm-value-col {
        flex-grow: 1;
        font-size: 15px;
        color: #333;
        display: flex;
        align-items: center;
        gap: 10px;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    }
    
    .check-icon { color: #28a745; font-weight: bold; font-size: 18px; }
    .error-icon { color: #dc3545; font-weight: bold; font-size: 18px; }
    .error-text { color: #dc3545; font-weight: 500; font-size: 14px; font-style: italic; }

    .status-badge {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        border-radius: 999px;
        padding: 4px 10px;
        font-size: 11px;
        font-weight: 700;
        border: 1px solid transparent;
    }

    .badge-ok { background: #e7f5ec; color: #1a7a43; border-color: #cdebd9; }
    .badge-warn { background: #fff2e6; color: #9f5b00; border-color: #ffddb8; }
    .badge-bad { background: #fdeced; color: #a32828; border-color: #f6c9cc; }
    .badge-opt { background: #eff3f7; color: #4f6071; border-color: #dbe3eb; }

    .checks-grid {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 10px;
        margin-top: 8px;
    }

    .checks-item {
        border: 1px solid var(--line);
        border-radius: 10px;
        background: #fff;
        padding: 10px;
    }

    .checks-label {
        font-size: 12px;
        color: #4e5d6c;
        margin-bottom: 6px;
        font-weight: 600;
    }

    .utm-compact-grid {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 10px;
        margin-top: 8px;
    }

    .utm-param-item {
        border: 1px solid var(--line);
        border-radius: 10px;
        padding: 10px;
        background: #fff;
    }

    .utm-param-title {
        font-size: 12px;
        font-weight: 700;
        color: #2f3f4f;
        margin-bottom: 6px;
    }

    .utm-param-value {
        font-size: 13px;
        color: #1f2933;
        word-break: break-word;
        margin-top: 6px;
    }

    /* 5. STILE CHAT GEMINI (Riproduzione) */
    .gemini-container {
        max-width: 800px;
        margin: 0 auto;
        padding: 20px;
    }
    
    .gemini-msg {
        margin-bottom: 24px;
        font-family: 'Google Sans', Roboto, Arial, sans-serif;
        font-size: 16px;
        line-height: 1.5;
        color: #1f1f1f;
    }
    
    .gemini-msg-user {
        display: flex;
        flex-direction: column;
        align-items: flex-end;
    }
    
    .gemini-msg-user .bubble {
        background-color: #f0f4f9;
        padding: 12px 20px;
        border-radius: 18px;
        max-width: 85%;
        word-wrap: break-word;
    }
    
    .gemini-msg-assistant {
        display: flex;
        gap: 16px;
        align-items: flex-start;
    }
    
    .gemini-msg-assistant .avatar {
        width: 30px;
        height: 30px;
        background: linear-gradient(135deg, #4285f4, #9b72cb, #d96570);
        border-radius: 50%;
        flex-shrink: 0;
        margin-top: 4px;
    }
    
    .gemini-msg-assistant .content {
        flex-grow: 1;
        padding-top: 2px;
    }

    /* Override Streamlit Chat Input to look more like Gemini */
    .stChatInputContainer {
        border-radius: 28px !important;
        border: 1px solid #757575 !important;
        background-color: white !important;
        max-width: 800px !important;
        margin: 0 auto !important;
    }

    div[data-testid="stWidgetLabel"] p {
        color: #243342 !important;
        font-weight: 620 !important;
        font-size: 0.94rem !important;
    }

    div[data-testid="stTabs"] [data-baseweb="tab-list"],
    div[data-testid="stTabs"] [role="tablist"] {
        display: flex !important;
        justify-content: center !important;
        align-items: center !important;
        gap: 2px;
        background: var(--surface) !important;
        border: 1px solid var(--line) !important;
        border-radius: 16px;
        padding: 4px 6px;
        width: fit-content;
        margin: 20px auto 16px auto;
    }

    div[data-testid="stTabs"] > div,
    div[data-testid="stTabs"] > div > div,
    div[data-testid="stTabs"] [data-baseweb="tab-border"] {
        background: transparent !important;
        border: none !important;
        box-shadow: none !important;
        padding: 0 !important;
    }
    div[data-testid="stTabs"] [data-baseweb="tab-highlight"] {
        display: none !important;
    }
    div[data-testid="stTabs"] [role="tabpanel"] {
        background: transparent !important;
        border: none !important;
        box-shadow: none !important;
        padding-top: 0 !important;
    }

    div[data-testid="stTabs"] [data-baseweb="tab"],
    div[data-testid="stTabs"] [role="tab"] {
        border-radius: 12px;
        padding: 8px 18px;
        font-weight: 600;
        color: var(--muted);
        border: 1px solid transparent;
        background: transparent;
        transition: all .2s ease;
    }

    div[data-testid="stTabs"] [aria-selected="true"] {
        background: var(--brand) !important;
        color: #fff !important;
        border-color: transparent;
        box-shadow: none;
    }

    div[data-testid="stTabs"] [data-baseweb="tab"]:hover,
    div[data-testid="stTabs"] [role="tab"]:hover {
        background: #f4f7fa;
        border-color: var(--line);
    }

    .stButton > button {
        border-radius: 12px;
        border: 1px solid var(--line);
        background: var(--surface);
        color: var(--ink);
        font-weight: 600;
        box-shadow: 0 1px 2px rgba(15, 23, 42, 0.06);
    }

    .stButton > button[kind="primary"] {
        background: var(--brand);
        border: 1px solid var(--brand);
        color: #fff;
        font-weight: 600;
        box-shadow: 0 2px 6px rgba(17, 24, 39, 0.22);
    }

    /* Allinea altezza e migliora leggibilità dei campi */
    div[data-testid="stTextInput"] input,
    div[data-baseweb="select"] > div,
    div[data-testid="stDateInput"] input {
        min-height: 42px !important;
        border-radius: 12px !important;
        border: 1px solid var(--line) !important;
        background: var(--surface) !important;
        color: var(--ink) !important;
        box-shadow: none !important;
    }

    div[data-testid="stTextInput"] input::placeholder {
        color: #7d95ab !important;
    }

    div[data-baseweb="select"] > div {
        background: var(--surface) !important;
    }

    div[data-testid="stTextInput"] input:focus,
    div[data-baseweb="select"] > div:focus-within,
    div[data-testid="stDateInput"] input:focus {
        border-color: rgba(102, 198, 172, 0.62) !important;
        box-shadow: 0 0 0 3px rgba(102, 198, 172, 0.18) !important;
    }

    /* Campi disabilitati (es. label utm_*) volutamente differenziati */
    div[data-testid="stTextInput"] input:disabled {
        background: #f5f8fb !important;
        border: 1px solid var(--line) !important;
        color: #50627a !important;
        font-weight: 600 !important;
    }

    div[data-testid="stTextInput"] input[value^="utm_"]:disabled,
    div[data-testid="stTextInput"] input[value="campaign_type"]:disabled {
        background: var(--brand) !important;
        border: 1px solid var(--brand) !important;
        color: #ffffff !important;
        -webkit-text-fill-color: #ffffff !important;
        opacity: 1 !important;
        border-radius: 999px !important;
        min-height: 34px !important;
        font-size: 12px !important;
        font-weight: 700 !important;
        text-align: center;
    }

    div[data-testid="stRadio"] [role="radiogroup"] {
        gap: 8px;
    }

    div[data-testid="stRadio"] [role="radiogroup"] label {
        background: transparent;
        border: 1px solid transparent;
        border-radius: 999px;
        padding: 2px 10px;
    }

    div[data-testid="stTextInput"] label,
    div[data-testid="stSelectbox"] label,
    div[data-testid="stDateInput"] label {
        color: #23415e !important;
        font-weight: 620 !important;
    }

    @media (max-width: 900px) {
        .feature-grid {
            grid-template-columns: repeat(2, minmax(0, 1fr));
        }

        .checks-grid,
        .utm-compact-grid {
            grid-template-columns: 1fr;
        }

        .sticky-panel {
            position: static;
        }

        .hero-title {
            font-size: 42px;
        }

        .assistant-cta-title {
            font-size: 18px;
        }

        .assistant-cta-copy {
            font-size: 13px;
        }
    }

    @media (max-width: 640px) {
        .block-container {
            padding-left: 0.6rem;
            padding-right: 0.6rem;
        }
        .feature-grid {
            grid-template-columns: 1fr;
            padding-left: 14px;
            padding-right: 14px;
        }
        .hero {
            padding: 42px 0 28px 0;
        }
        .hero-title {
            font-size: 34px;
        }
        .hero-desc {
            font-size: 14px;
        }
        .assistant-cta-inner {
            padding: 14px;
        }
    }

</style>
""", unsafe_allow_html=True)

# --- GOOGLE AUTH FUNCTIONS ---
SCOPES = [
    'https://www.googleapis.com/auth/analytics.readonly',
    'https://www.googleapis.com/auth/analytics.edit',
    'https://www.googleapis.com/auth/userinfo.email',
    'openid'
]

def get_oauth_flow():
    """Configura l'oggetto Flow per Web OAuth usando i Secrets o il json locale"""
    # Prova a prendere le configurazioni dai Secrets di Streamlit
    if "gcp_service_account" in st.secrets:
        # Se c'è un service account configurato nei secrets, potresti saltare OAuth, 
        # ma per il flusso utente richiesto presupponiamo OAuth Client ID Web App.
        # Fallback al json locale per la configurazione se nei secrets mettiamo l'intero JSON client_secrets
        pass
    
    # Per ora gestiamo il file locale o i secrets (se configurati come dict nel toml)
    base_path = os.path.dirname(os.path.abspath(__file__))
    secrets_path = os.path.join(base_path, 'client_secrets.json')
    
    # Determina la redirect URI dinamica dalla URL dell'app Streamlit, o usa un default
    # Notare che Streamlit Cloud su redirect tipicamente usa l'URL base.
    # In locale useremo http://localhost:8501
    
    # Ottieni i parametri attuali per capire se siamo in callback
    query_params = st.query_params
    
    if os.path.exists(secrets_path):
        import json
        with open(secrets_path, 'r') as f:
            client_config = json.load(f)
    elif "google_oauth" in st.secrets:
        # Crea dict dal toml
        client_config = {"web": dict(st.secrets["google_oauth"])}
    else:
        st.error("Configurazione OAuth (client_secrets.json o st.secrets) mancante!")
        return None

    from google_auth_oauthlib.flow import Flow
    flow = Flow.from_client_config(
        client_config,
        scopes=SCOPES
    )
    
    # Costruisci redirect_uri base 
    # (Attenzione: DEVE coincidere esattamente con quella registrata per l'app su Google Cloud)
    # Su Streamlit Cloud è un po' tricky ottenere il proprio URL dinamicamente via codice in modo affidabile,
    # quindi se impostato in st.secrets["redirect_uri"] usiamo quello, altrimenti cerchiamo di indovinarlo.
    if "redirect_uri" in st.secrets:
        redirect_uri = st.secrets["redirect_uri"]
    else:
        # Assume test locale
        redirect_uri = 'http://localhost:8501/'
        
    flow.redirect_uri = redirect_uri
    return flow

def do_oauth_flow():
    """Gestisce il flow di autenticazione Google OAuth 2.0 Web"""
    
    # Controlla se le credenziali sono già in sessione
    if 'google_credentials' in st.session_state and st.session_state.google_credentials:
        creds = Credentials(
            token=st.session_state.google_credentials['token'],
            refresh_token=st.session_state.google_credentials.get('refresh_token'),
            token_uri=st.session_state.google_credentials.get('token_uri'),
            client_id=st.session_state.google_credentials.get('client_id'),
            client_secret=st.session_state.google_credentials.get('client_secret'),
            scopes=st.session_state.google_credentials.get('scopes')
        )
        
        if creds.valid:
            return creds
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                # Aggiorna sessione
                st.session_state.google_credentials['token'] = creds.token
                return creds
            except Exception:
                st.session_state.google_credentials = None
                
    # Verifica se stiamo tornando da un redirect di login
    query_params = st.query_params
    if 'code' in query_params:
        flow = get_oauth_flow()
        if not flow:
            return None
            
        try:
            # Recupera il token
            code = query_params['code']
            flow.fetch_token(code=code)
            creds = flow.credentials
            
            # Salva credenziali scalari compatibili con JSON in session_state, NO file
            st.session_state.google_credentials = {
                'token': creds.token,
                'refresh_token': creds.refresh_token,
                'token_uri': creds.token_uri,
                'client_id': creds.client_id,
                'client_secret': creds.client_secret,
                'scopes': creds.scopes
            }
            
            # Ripulisci l'URL (rimuovi ?code=...) così se refresha la pagina non va in crash
            import urllib.parse
            if hasattr(st, "query_params"):
                st.query_params.clear()
            else:
                st.experimental_set_query_params() # per vecchie versioni streamlit
                
            st.rerun() # Forza rerun per mostrare UI pulita
        except Exception as e:
            st.error(f"Errore durante l'accesso: {e}")
            
    # Se arriva qui, serve fare il login
    return None

def get_ga4_accounts_structure(creds):
    """Recupera la struttura Account -> Properties usando ga4_mcp_tools"""
    try:
        # Usa la funzione centralizzata che ritorna già la gerarchia
        return ga4_mcp_tools.get_account_summaries(creds)
    except Exception as e:
        st.error(f"Errore nel recupero property: {e}")
        return []

def get_top_traffic_sources(property_id, creds):
    """Recupera le sorgenti di traffico principali degli ultimi 30 giorni"""
    try:
        client = BetaAnalyticsDataClient(credentials=creds)
        request = RunReportRequest(
            property=property_id,
            date_ranges=[DateRange(start_date="30daysAgo", end_date="today")],
            dimensions=[Dimension(name="sessionSource")],
            metrics=[Metric(name="sessions")],
            order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="sessions"), desc=True)],
            limit=50
        )
        response = client.run_report(request)
        
        sources = []
        for row in response.rows:
            sources.append(row.dimension_values[0].value)
        return sources
    except Exception as e:
        st.warning(f"Impossibile recuperare sorgenti da GA4: {e}")
        return []

def get_top_traffic_mediums(property_id, creds):
    """Recupera i medium principali degli ultimi 30 giorni"""
    try:
        client = BetaAnalyticsDataClient(credentials=creds)
        request = RunReportRequest(
            property=property_id,
            date_ranges=[DateRange(start_date="30daysAgo", end_date="today")],
            dimensions=[Dimension(name="sessionMedium")],
            metrics=[Metric(name="sessions")],
            order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="sessions"), desc=True)],
            limit=50
        )
        response = client.run_report(request)
        mediums = []
        for row in response.rows:
            mediums.append(row.dimension_values[0].value)
        return mediums
    except Exception as e:
        st.warning(f"Impossibile recuperare medium da GA4: {e}")
        return []

def get_source_medium_pairs(property_id, creds):
    """Recupera coppie source-medium principali degli ultimi 30 giorni."""
    try:
        client = BetaAnalyticsDataClient(credentials=creds)
        request = RunReportRequest(
            property=property_id,
            date_ranges=[DateRange(start_date="30daysAgo", end_date="today")],
            dimensions=[Dimension(name="sessionSource"), Dimension(name="sessionMedium")],
            metrics=[Metric(name="sessions")],
            order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="sessions"), desc=True)],
            limit=200
        )
        response = client.run_report(request)
        pairs = []
        for row in response.rows:
            src = row.dimension_values[0].value
            med = row.dimension_values[1].value
            pairs.append((src, med))
        return pairs
    except Exception as e:
        st.warning(f"Impossibile recuperare coppie source-medium da GA4: {e}")
        return []

# --- DATI GUIDA (Fallback e Mapping) ---
GUIDE_TABLE_DATA = [
    {"Traffic type": "Organic", "utm_medium": "organic", "utm_source": "google, bing, yahoo"},
    {"Traffic type": "Referral", "utm_medium": "referral", "utm_source": "(domain)"},
    {"Traffic type": "Direct", "utm_medium": "(none)", "utm_source": "(direct)"},
    {"Traffic type": "Paid Search", "utm_medium": "cpc", "utm_source": "google, bing"},
    {"Traffic type": "Affiliate", "utm_medium": "affiliate", "utm_source": "tradetracker, awin"},
    {"Traffic type": "Display", "utm_medium": "cpm", "utm_source": "reservation, display, dv360, google"},
    {"Traffic type": "Video", "utm_medium": "cpv", "utm_source": "youtube, vimeo, google"},
    {"Traffic type": "Programmatic", "utm_medium": "cpm", "utm_source": "rcs, mediamond, rai, manzoni"},
    {"Traffic type": "Email", "utm_medium": "email|mailing_campaign", "utm_source": "newsletter, email, crm, sfmc, mailchimp"},
    {"Traffic type": "Organic Social", "utm_medium": "social_org", "utm_source": "facebook, instagram, tiktok, linkedin, pinterest"},
    {"Traffic type": "Paid Social", "utm_medium": "social_paid", "utm_source": "facebook, instagram, tiktok, linkedin, pinterest"},
    {"Traffic type": "App traffic", "utm_medium": "-", "utm_source": "app"},
    {"Traffic type": "SMS", "utm_medium": "offline", "utm_source": "sms"},
    {"Traffic type": "Altro", "utm_medium": "other", "utm_source": ""},
]

# --- UTILS ---
def get_source_options():
    sources = set()
    for row in GUIDE_TABLE_DATA:
        parts = row["utm_source"].split(",")
        for p in parts:
            clean = p.strip().replace("...", "")
            if clean and "(" not in clean and "[" not in clean:
                sources.add(clean)
    return [""] + sorted(list(sources)) + ["Altro (Inserisci manuale)"]

SOURCE_OPTIONS = get_source_options()

def get_compatible_channels(selected_source, all_client_channels):
    if not selected_source or selected_source == "Altro (Inserisci manuale)":
        return [""] + all_client_channels
    norm_source = selected_source.strip().lower()
    compatible_types = set()
    for row in GUIDE_TABLE_DATA:
        row_sources = [s.strip().lower() for s in row["utm_source"].split(",")]
        if norm_source in row_sources:
            compatible_types.add(row["Traffic type"])
    if not compatible_types:
        return [""] + all_client_channels
    filtered_channels = [c for c in all_client_channels if c in compatible_types]
    return [""] + sorted(filtered_channels) if filtered_channels else [""] + all_client_channels

def normalize_token(text):
    if not text: return ""
    return slugify(text, separator="-", lowercase=True)


def normalize_client_id(value: str) -> str:
    return slugify((value or "").strip(), separator="_")

def normalize_medium_token(text):
    """Normalizza utm_medium preservando underscore GA4 (es. social_paid)."""
    if not text:
        return ""
    value = str(text).strip().lower()
    value = value.replace("-", "_")
    value = re.sub(r"\s+", "_", value)
    value = re.sub(r"[^a-z0-9_-]", "", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return value

def suggest_naming_value(text, prefer_hyphen=True):
    """Produce a best-practice suggestion for campaign naming values."""
    if not text:
        return ""
    value = str(text).strip().lower()
    value = re.sub(r"\s+", "-", value)
    value = re.sub(r"[^a-z0-9_-]", "", value)
    if prefer_hyphen:
        value = value.replace("_", "-")
    value = re.sub(r"-{2,}", "-", value)
    value = re.sub(r"_{2,}", "_", value)
    return value.strip("-_")

def validate_naming_rules(text, prefer_hyphen=True):
    """Return (issues, suggestion) for naming best-practices validation."""
    issues = []
    if not text:
        return issues, ""
    raw = str(text).strip()
    suggestion = suggest_naming_value(raw, prefer_hyphen=prefer_hyphen)

    if raw != raw.lower():
        issues.append("usa solo minuscole")
    if re.search(r"\s", raw):
        issues.append("evita spazi")
    if re.search(r"[^A-Za-z0-9_-]", raw):
        issues.append("evita caratteri speciali")
    if prefer_hyphen and "_" in raw:
        issues.append("preferisci trattini (-) agli underscore (_)")
    if len(raw) > 50:
        issues.append("mantieni il nome descrittivo ma conciso")
    return issues, suggestion

def filter_options_by_source_mode(options, mode, field):
    """Filter source/medium options according to selected traffic source mode."""
    if field == "medium":
        tokens = [normalize_medium_token(o) for o in options if normalize_medium_token(o)]
    else:
        tokens = [normalize_token(o) for o in options if normalize_token(o)]
    if mode == "Custom values":
        return sorted(set(tokens))

    if field == "source":
        source_map = {
            "Paid": ["google", "bing", "adwords", "googleads", "facebook", "instagram", "tiktok", "linkedin", "meta"],
            "Email": ["email", "newsletter", "crm", "mailchimp", "sfmc"],
            "SMS": ["sms", "whatsapp", "messenger"],
            "Google Ads": ["google", "adwords", "googleads", "bing"],
            "Social": ["facebook", "instagram", "tiktok", "linkedin", "pinterest", "social", "meta", "twitter", "x"],
        }
        hints = source_map.get(mode, [])
    else:
        medium_map = {
            "Paid": ["cpc", "ppc", "sem", "paid_search", "paid-search", "cpm", "cpv", "social_paid", "paid_social", "paid-social"],
            "Email": ["email", "mailing_campaign", "newsletter", "mail"],
            "SMS": ["sms"],
            "Google Ads": ["cpc", "ppc", "paid-search", "paid_search", "sem"],
            "Social": ["social", "social_paid", "social_org", "paid-social", "organic-social", "organic_social", "paid_social"],
        }
        hints = medium_map.get(mode, [])

    filtered = [t for t in tokens if any(h in t for h in hints)]
    return sorted(set(filtered))


def order_by_ga4_priority(options, ga4_priority, normalizer):
    """Order options by GA4 popularity (sessions) first, then alphabetical fallback."""
    values = []
    seen = set()
    for raw in options or []:
        v = normalizer(raw)
        if v and v not in seen:
            values.append(v)
            seen.add(v)

    priority = []
    seen_p = set()
    for raw in ga4_priority or []:
        v = normalizer(raw)
        if v and v not in seen_p:
            priority.append(v)
            seen_p.add(v)

    head = [v for v in priority if v in seen]
    tail = sorted([v for v in values if v not in set(head)])
    return head + tail


def is_valid_url(url):
    regex = re.compile(r'^https?://(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|localhost|\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})(?::\d+)?(?:/?|[/?]\S+)$', re.IGNORECASE)
    return re.match(regex, url) is not None


def _client_config_path(client_id: str) -> Path:
    return CLIENT_CONFIG_DIR / f"{normalize_client_id(client_id)}.json"


def load_client_config(client_id: str):
    cid = normalize_client_id(client_id)
    if not cid:
        return None
    path = _client_config_path(cid)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def save_client_config(client_id: str, payload: dict) -> Path:
    cid = normalize_client_id(client_id)
    if not cid:
        raise ValueError("client_id non valido")
    CLIENT_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    path = _client_config_path(cid)
    body = dict(payload or {})
    body["client_id"] = cid
    path.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def parse_rules_rows_from_uploaded_file(file_name: str, file_bytes: bytes) -> list:
    ext = Path(file_name or "").suffix.lower()
    rows = []

    if ext == ".csv":
        df = pd.read_csv(BytesIO(file_bytes), dtype=str).fillna("")
        for _, row in df.iterrows():
            row_dict = {str(k): str(v) for k, v in row.to_dict().items()}
            row_dict["__sheet_name"] = "csv"
            rows.append(row_dict)
        return rows

    sheets = pd.read_excel(BytesIO(file_bytes), sheet_name=None, dtype=str)
    for sheet_name, df in (sheets or {}).items():
        if df is None:
            continue
        safe_sheet_name = str(sheet_name or "").strip()[:80] or "__sheet__"
        for _, row in df.fillna("").iterrows():
            row_dict = {str(k): str(v) for k, v in row.to_dict().items()}
            row_dict["__sheet_name"] = safe_sheet_name
            rows.append(row_dict)
    return rows


def list_saved_client_ids() -> list:
    CLIENT_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    return sorted({p.stem for p in CLIENT_CONFIG_DIR.glob("*.json")})


def sign_client_id(client_id: str) -> str:
    cid = normalize_client_id(client_id)
    if not cid or not CLIENT_LINK_SECRET:
        return ""
    return hmac.new(CLIENT_LINK_SECRET.encode("utf-8"), cid.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_client_signature(client_id: str, signature: str) -> bool:
    cid = normalize_client_id(client_id)
    sig = str(signature or "").strip()
    if not cid or not sig or not CLIENT_LINK_SECRET:
        return False
    expected = sign_client_id(cid)
    return bool(expected) and hmac.compare_digest(expected, sig)


def get_client_lock_from_query_params():
    def _qp(name: str) -> str:
        raw = st.query_params.get(name, "")
        if isinstance(raw, (list, tuple)):
            raw = raw[0] if raw else ""
        return str(raw or "").strip()

    client_id = normalize_client_id(_qp("client_id"))
    sig = _qp("sig")
    if not client_id:
        return None, ""

    def _verify_with_saved_link(cid: str, signature: str) -> bool:
        cfg = load_client_config(cid)
        if not cfg:
            return False
        shared_link = str(cfg.get("shared_link", "")).strip()
        if not shared_link:
            return False
        try:
            q = parse_qs(urlparse(shared_link).query)
            saved_cid = normalize_client_id((q.get("client_id") or [""])[0])
            saved_sig = str((q.get("sig") or [""])[0] or "").strip()
            return bool(saved_cid and saved_sig and saved_cid == cid and hmac.compare_digest(saved_sig, signature))
        except Exception:
            return False

    if CLIENT_LINK_SECRET and verify_client_signature(client_id, sig):
        return client_id, ""
    if _verify_with_saved_link(client_id, sig):
        return client_id, ""
    if not CLIENT_LINK_SECRET:
        return None, "CLIENT_LINK_SECRET non configurato: impossibile verificare il link cliente."
    return None, "Link cliente non valido o firma scaduta/non corretta."


def _split_rule_values(value: str) -> list:
    raw = str(value or "").strip()
    if not raw:
        return []
    return [x.strip() for x in re.split(r"[,\|;/]+", raw) if str(x).strip()]


def extract_client_rule_values(client_config: dict):
    rows = (client_config or {}).get("rules_rows", []) or []
    source_keys = {"utm_source", "source"}
    medium_keys = {"utm_medium", "medium"}
    campaign_type_keys = {"campaigntype", "campaign_type", "type"}
    sources = set()
    mediums = set()
    campaign_types = set()

    # 1) parsing diretto per colonne già nominate
    for row in rows:
        if not isinstance(row, dict):
            continue
        for key, raw_val in row.items():
            norm_key = str(key).strip().lower().replace(" ", "_")
            tokens = _split_rule_values(raw_val)
            if not tokens:
                continue
            if norm_key in source_keys:
                for t in tokens:
                    v = normalize_token(t)
                    if v:
                        sources.add(v)
            if norm_key in medium_keys:
                for t in tokens:
                    v = normalize_medium_token(t)
                    if v:
                        mediums.add(v)
            if norm_key in campaign_type_keys:
                for t in tokens:
                    v = normalize_token(t)
                    if v:
                        campaign_types.add(v)

    # 2) parsing tabellare per file excel importati con Unnamed:* e header in riga
    role_map_by_sheet = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        sheet_name = str(row.get("__sheet_name", "")).strip().lower() or "__default__"
        current_map = dict(role_map_by_sheet.get(sheet_name, {}))
        header_detected = False
        for key, raw_val in row.items():
            val_norm = normalize_token(str(raw_val or ""))
            if val_norm in source_keys:
                current_map[str(key)] = "source"
                header_detected = True
            elif val_norm in medium_keys:
                current_map[str(key)] = "medium"
                header_detected = True
            elif val_norm in campaign_type_keys:
                current_map[str(key)] = "campaign_type"
                header_detected = True
        if header_detected:
            role_map_by_sheet[sheet_name] = current_map
            continue
        if not current_map:
            continue
        for col_key, role in current_map.items():
            for t in _split_rule_values(row.get(col_key, "")):
                norm_t = normalize_token(t)
                if not norm_t:
                    continue
                if norm_t in source_keys or norm_t in medium_keys or norm_t in campaign_type_keys:
                    continue
                if role == "source":
                    sources.add(norm_t)
                elif role == "medium":
                    mediums.add(normalize_medium_token(t))
                elif role == "campaign_type":
                    campaign_types.add(norm_t)
    return sorted(sources), sorted(mediums), sorted(campaign_types)


def build_client_rules_text_for_chatbot(client_config: dict) -> str:
    if not client_config:
        return ""
    cid = normalize_client_id(client_config.get("client_id", ""))
    sources, mediums, campaign_types = extract_client_rule_values(client_config)
    lines = [f"- client_id: {cid}"] if cid else []
    ga4_name = str(client_config.get("ga4_client_name", "")).strip()
    if ga4_name:
        lines.append(f"- cliente GA4: {ga4_name}")
    if sources:
        lines.append(f"- utm_source consentiti (esempi): {', '.join(sources[:20])}")
    if mediums:
        lines.append(f"- utm_medium consentiti (esempi): {', '.join(mediums[:20])}")
    if campaign_types:
        lines.append(f"- campaign_type usati: {', '.join(campaign_types[:20])}")
    lines.append("- Evita valori fuori convenzione cliente se non esplicitamente richiesti.")
    return "\n".join(lines)


def resolve_locked_client_context(locked_client_id: str):
    locked_cid = normalize_client_id(locked_client_id)
    if not locked_cid:
        return "", None, ""
    direct = load_client_config(locked_cid)
    if direct:
        return locked_cid, direct, ""
    candidates = [cid for cid in list_saved_client_ids() if locked_cid in cid or cid in locked_cid]
    if candidates:
        chosen = sorted(candidates, key=lambda x: (x != locked_cid, len(x)))[0]
        cfg = load_client_config(chosen)
        if cfg:
            return chosen, cfg, f"Link cliente '{locked_cid}' agganciato alla configurazione '{chosen}'."
    return locked_cid, None, ""

def load_utm_history():
    if 'utm_history' not in st.session_state:
        st.session_state.utm_history = []
    return st.session_state.utm_history

def save_utm_history(items):
    st.session_state.utm_history = items

def infer_expected_channel_group(utm_medium: str) -> str:
    m = normalize_medium_token(utm_medium)
    if m in ("social_paid", "paid_social", "paid-social"):
        return "Paid Social"
    if m in ("social_org", "organic_social", "organic-social"):
        return "Organic Social"
    if m in ("email", "mailing_campaign", "newsletter"):
        return "Email"
    if m in ("cpc", "ppc", "sem", "paid_search", "paid-search"):
        return "Paid Search"
    if m in ("cpm", "display"):
        return "Display"
    if m == "referral":
        return "Referral"
    if m == "organic":
        return "Organic Search"
    return "Other"

def upsert_utm_history_entry(entry: dict):
    items = load_utm_history()
    key_fields = ("user_email", "property_id", "final_url")
    idx = next(
        (i for i, x in enumerate(items) if all(x.get(k) == entry.get(k) for k in key_fields)),
        None
    )
    if idx is None:
        items.append(entry)
    else:
        items[idx].update(entry)
    save_utm_history(items)

def parse_ddmmyyyy_to_date(date_str: str):
    try:
        return datetime.strptime(date_str, "%d/%m/%Y").date()
    except Exception:
        return None

def _extract_live_date_from_utm_campaign(utm_campaign: str) -> str:
    campaign = (utm_campaign or "").strip().lower()
    for token in campaign.split("_"):
        if re.fullmatch(r"\d{8}", token):
            try:
                dt = datetime.strptime(token, "%d%m%Y")
                return dt.strftime("%d/%m/%Y")
            except Exception:
                continue
    return datetime.today().strftime("%d/%m/%Y")

def save_chatbot_url_to_history(final_url: str, property_id: str = "") -> bool:
    try:
        parsed = urlparse((final_url or "").strip())
        if not parsed.scheme or not parsed.netloc:
            return False
        params = parse_qs(parsed.query)

        utm_source = normalize_token((params.get("utm_source") or [""])[0])
        utm_medium = normalize_medium_token((params.get("utm_medium") or [""])[0])
        utm_campaign = normalize_token((params.get("utm_campaign") or [""])[0])
        if not (utm_source and utm_medium and utm_campaign):
            return False

        campaign_parts = [p for p in utm_campaign.split("_") if p]
        campaign_name = campaign_parts[2] if len(campaign_parts) >= 3 else utm_campaign
        live_date = _extract_live_date_from_utm_campaign(utm_campaign)

        prop_lookup = build_property_name_lookup(st.session_state.get("ga4_accounts", []))
        prop_id_raw = str(property_id or "").replace("properties/", "")
        property_name = (
            prop_lookup.get(str(property_id or ""))
            or prop_lookup.get(prop_id_raw)
            or ""
        )

        entry = {
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "user_email": st.session_state.get("user_email", ""),
            "property_id": prop_id_raw,
            "property_name": property_name,
            "client_id": st.session_state.get("active_client_id", ""),
            "campaign_name": campaign_name,
            "live_date": live_date,
            "utm_source": utm_source,
            "utm_medium": utm_medium,
            "utm_campaign": utm_campaign,
            "final_url": final_url,
            "expected_channel_group": infer_expected_channel_group(utm_medium),
        }
        upsert_utm_history_entry(entry)
        return True
    except Exception:
        return False

def build_property_name_lookup(accounts_structure):
    lookup = {}
    if not isinstance(accounts_structure, list):
        return lookup
    for acc in accounts_structure:
        for p in acc.get("properties", []) or []:
            pid_raw = str(p.get("property_id", "")).strip()
            if not pid_raw:
                continue
            pid_num = pid_raw.replace("properties/", "")
            name = p.get("display_name", "")
            if name:
                lookup[pid_raw] = name
                lookup[pid_num] = name
    return lookup

def check_tracking_status_for_entry(entry: dict, creds, grace_days: int = 2):
    property_id = entry.get("property_id")
    if not property_id:
        return {"status": "ERROR", "message": "Property non disponibile", "sessions": 0, "observed": "-"}
    try:
        client = BetaAnalyticsDataClient(credentials=creds)
        ga4_prop = property_id if str(property_id).startswith("properties/") else f"properties/{property_id}"
        report = client.run_report(
            RunReportRequest(
                property=ga4_prop,
                date_ranges=[DateRange(start_date="30daysAgo", end_date="today")],
                dimensions=[
                    Dimension(name="sessionSource"),
                    Dimension(name="sessionMedium"),
                    Dimension(name="sessionCampaignName"),
                    Dimension(name="sessionPrimaryChannelGroup"),
                    Dimension(name="sessionDefaultChannelGroup"),
                ],
                metrics=[Metric(name="sessions")],
                limit=1000,
            )
        )
        src = normalize_token(entry.get("utm_source", ""))
        med = normalize_medium_token(entry.get("utm_medium", ""))
        cmpn = normalize_token(entry.get("utm_campaign", ""))

        matched = []
        for row in report.rows:
            ds = normalize_token(row.dimension_values[0].value)
            dm = normalize_medium_token(row.dimension_values[1].value)
            dc = normalize_token(row.dimension_values[2].value)
            sessions = int(float(row.metric_values[0].value or 0))
            observed = row.dimension_values[3].value or row.dimension_values[4].value or "Unassigned"
            if ds == src and dm == med and dc == cmpn:
                matched.append((sessions, observed))

        total_sessions = sum(x[0] for x in matched)
        observed_channel = "-"
        if matched:
            by_channel = {}
            for s, ch in matched:
                by_channel[ch] = by_channel.get(ch, 0) + s
            observed_channel = sorted(by_channel.items(), key=lambda x: x[1], reverse=True)[0][0]

        expected = entry.get("expected_channel_group", "Other")
        live_date = parse_ddmmyyyy_to_date(entry.get("live_date", ""))
        today = datetime.today().date()
        after_grace = bool(live_date and today > (live_date + timedelta(days=grace_days)))

        if total_sessions == 0 and after_grace:
            return {
                "status": "ERROR",
                "message": "Nessun traffico rilevato con questi UTM",
                "sessions": 0,
                "observed": observed_channel,
            }
        if total_sessions > 0 and observed_channel != expected:
            return {
                "status": "WARNING",
                "message": f"Il traffico è finito in {observed_channel} invece di {expected}",
                "sessions": total_sessions,
                "observed": observed_channel,
            }
        if total_sessions > 0 and observed_channel == expected:
            return {
                "status": "OK",
                "message": "Tracking e canalizzazione corretti",
                "sessions": total_sessions,
                "observed": observed_channel,
            }
        return {
            "status": "PENDING",
            "message": "Campagna recente: in attesa di traffico",
            "sessions": total_sessions,
            "observed": observed_channel,
        }
    except Exception as e:
        return {"status": "ERROR", "message": f"Errore GA4: {e}", "sessions": 0, "observed": "-"}

# --- SERVER-SIDE OAUTH CACHE ---
# Necessario perché Streamlit distrugge st.session_state quando l'utente cambia tab o naviga via,
# perdendo il PKCE code_verifier autogenerato da google-auth.
@st.cache_resource
def get_oauth_cache():
    return {}

# --- LOGIN PAGE ---
def show_login_page():
    st.container()
    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        st.markdown("<div style='text-align: center; margin-top: 100px;'>", unsafe_allow_html=True)
        st.title("🛡️ Universal UTM Governance")
        st.subheader("Accedi per gestire i tuoi link")
        st.markdown("</div>", unsafe_allow_html=True)
        
        st.write("")
        st.write("")
        
        # Link OAuth generato web-side (Gestione sicura PKCE via Server Cache)
        flow = get_oauth_flow()
        if flow:
            auth_url, state_token = flow.authorization_url(prompt='consent')
            
            # Salviamo il code_verifier nella cache persistente del server, non nella sessione del browser,
            # agganciandolo all'ID univoco 'state' per recuperarlo quando l'utente torna (anche in un nuovo tab)
            cache = get_oauth_cache()
            if hasattr(flow, 'code_verifier'):
                cache[state_token] = flow.code_verifier

            st.link_button("🔐 Login con Google Analytics", auth_url, type="primary", use_container_width=True)
        else:
            st.error("Configurazione Google Auth mancante.")

# --- DASHBOARD PAGE ---
def show_dashboard():
    # --- INITIALIZE USER EMAIL AND API KEY ---
    if "user_email" not in st.session_state:
        st.session_state.user_email = get_user_email(st.session_state.credentials)
    current_user_email = st.session_state.get("user_email", "")
    user_email_lower = str(current_user_email or "").strip().lower()
    is_webranking_user = user_email_lower.endswith("@webranking.it") or user_email_lower.endswith("@webranking.com")
    cached_for_email = st.session_state.get("ga4_cache_user_email", "")
    if current_user_email and cached_for_email != current_user_email:
        st.session_state.pop("ga4_accounts", None)
        for k in list(st.session_state.keys()):
            if str(k).startswith("sources_") or str(k).startswith("mediums_") or str(k).startswith("source_medium_pairs_"):
                st.session_state.pop(k, None)
        st.session_state["ga4_cache_user_email"] = current_user_email
    
    if "gemini_api_key" not in st.session_state:
        # Try to load saved API key for this user
        saved_key = get_persistent_api_key(st.session_state.user_email)
        st.session_state.gemini_api_key = saved_key
    
    # --- HEADER PRINCIPALE ---
    if "show_user_menu" not in st.session_state:
        st.session_state.show_user_menu = False

    header_left, header_docs, header_account = st.columns([0.74, 0.12, 0.14], gap="small")
    with header_left:
        st.markdown(
            """
            <div class="lovable-topbar">
                <div class="lovable-brand">
                    <span class="lovable-badge-w">W</span>
                    <div class="lovable-title">SMART UTM <span class="lovable-beta">BETA</span></div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with header_docs:
        st.markdown('<div class="lovable-docs-link">Docs</div>', unsafe_allow_html=True)
    with header_account:
        if hasattr(st, "popover"):
            with st.popover("Account", use_container_width=True):
                st.caption(st.session_state.get("user_email", ""))
                if st.button("Impostazioni", key="settings_btn_menu", use_container_width=True):
                    st.session_state.show_settings = True
                if st.button("Logout", key="logout_btn", use_container_width=True):
                    if "credentials" in st.session_state:
                        del st.session_state.credentials
                    if "user_email" in st.session_state:
                        del st.session_state.user_email
                    if "gemini_api_key" in st.session_state:
                        del st.session_state.gemini_api_key
                    if "google_credentials" in st.session_state:
                        del st.session_state.google_credentials
                    st.session_state.pop("ga4_accounts", None)
                    st.session_state.pop("ga4_cache_user_email", None)
                    st.rerun()
        else:
            if st.button("Account ▾", key="user_menu_btn", use_container_width=True):
                st.session_state.show_user_menu = not st.session_state.show_user_menu
            if st.session_state.show_user_menu:
                if st.button("Impostazioni", key="settings_btn_menu_fallback", use_container_width=True):
                    st.session_state.show_settings = not st.session_state.get("show_settings", False)
                    st.session_state.show_user_menu = False
                if st.button("Logout", key="logout_btn_fallback", use_container_width=True):
                    if "credentials" in st.session_state:
                        del st.session_state.credentials
                    if "user_email" in st.session_state:
                        del st.session_state.user_email
                    if "gemini_api_key" in st.session_state:
                        del st.session_state.gemini_api_key
                    if "google_credentials" in st.session_state:
                        del st.session_state.google_credentials
                    st.session_state.pop("ga4_accounts", None)
                    st.session_state.pop("ga4_cache_user_email", None)
                    st.rerun()

    # --- SETTINGS MODAL ---
    if st.session_state.get("show_settings", False):
        st.markdown('<div class="form-card">', unsafe_allow_html=True)
        s_col1, s_col2 = st.columns([0.92, 0.08])
        with s_col1:
            st.markdown("### ⚙️ Impostazioni")
        with s_col2:
            if st.button("✕", key="close_settings_top", help="Chiudi impostazioni", use_container_width=True):
                st.session_state.show_settings = False
                st.rerun()
        with st.container():
            st.markdown("### Configurazione Gemini API")
            st.markdown(f"**Account:** {st.session_state.user_email}")
            
            current_key = st.session_state.get("gemini_api_key", "")
            key_status = "✅ Configurata" if current_key else "❌ Non configurata"
            st.markdown(f"**Stato API Key:** {key_status}")
            
            with st.form("api_key_form"):
                new_api_key = st.text_input(
                    "Gemini API Key",
                    value=current_key if current_key else "",
                    type="password",
                    help="Inserisci la tua chiave API di Google Gemini"
                )
                col1, col2 = st.columns([1, 1])
                with col1:
                    save_btn = st.form_submit_button("💾 Salva", use_container_width=True)
                with col2:
                    close_btn = st.form_submit_button("Chiudi", use_container_width=True)
                
                if save_btn and new_api_key:
                    st.session_state.gemini_api_key = new_api_key
                    save_persistent_api_key(st.session_state.user_email, new_api_key)
                    st.success("✅ API Key salvata con successo!")
                    st.session_state.show_settings = False
                    st.rerun()
                
                if close_btn:
                    st.session_state.show_settings = False
                    st.rerun()
            
            # --- GA4 Diagnostics ---
            st.markdown("---")
            st.markdown("### 🔌 Connessione GA4")
            if st.button("🔁 Test connessione GA4", key="test_ga4_btn"):
                with st.spinner("Verifica connessione GA4..."):
                    result = ga4_mcp_tools.get_account_summaries(st.session_state.credentials)
                if isinstance(result, list) and len(result) > 0:
                    st.success(f"✅ Connessione GA4 OK! Trovati {len(result)} account.")
                elif isinstance(result, list) and len(result) == 0:
                    st.warning("⚠️ Connessione OK ma nessun account GA4 trovato per questo utente.")
                elif isinstance(result, dict) and "error" in result:
                    error_type = result.get("error_type", "Sconosciuto")
                    error_msg = result.get("error", "")
                    st.error(f"❌ Errore GA4\n\n**Tipo:** {error_type}\n\n**Dettaglio:** {error_msg}")
                    if any(kw in error_msg.lower() for kw in ["credentials", "scope", "permission", "unauthenticated", "unauthorized", "403", "401"]):
                        st.warning("💡 Il token OAuth potrebbe avere scope insufficienti. Prova a fare **Logout** e ri-accedere con Google.")
                else:
                    st.info(f"Risposta inattesa: {result}")
        st.markdown('</div>', unsafe_allow_html=True)

    st.markdown("""
    <div class="hero">
        <div class="hero-status">● Connesso a GA4 in tempo reale</div>
        <div class="hero-title">Smart UTM <span class="hero-title-accent">Assistant</span></div>
        <div class="hero-desc">Crea e valida link UTM con guida passo-passo, leggendo in tempo reale source e medium dalla tua property GA4.</div>
        <div id="hero-open-chat-cta" class="assistant-cta-link" role="button" tabindex="0" aria-label="Apri chatbot WR Assistant">
            <div class="assistant-cta">
                <div class="assistant-cta-inner">
                    <div class="assistant-cta-icon">💬<span class="assistant-cta-sparkle">✦</span></div>
                    <div class="assistant-cta-body">
                        <div class="assistant-cta-title">Crea UTM con l'Assistente AI</div>
                        <div class="assistant-cta-copy">Apri il chatbot e lasciati guidare passo dopo passo</div>
                    </div>
                    <div class="assistant-cta-arrow">→</div>
                </div>
            </div>
        </div>
        <div class="hero-sub">Oppure compila manualmente i campi qui sotto ↓</div>
        <div class="feature-grid">
            <div class="feature-card">
                <div class="feature-icon">
                    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <ellipse cx="12" cy="5" rx="7" ry="3"></ellipse>
                        <path d="M5 5v14c0 1.7 3.1 3 7 3s7-1.3 7-3V5"></path>
                        <path d="M5 12c0 1.7 3.1 3 7 3s7-1.3 7-3"></path>
                    </svg>
                </div>
                <div class="feature-title">Dati reali da GA4</div>
                <div class="feature-copy">Source e medium precaricati dalla tua property: niente più errori di digitazione.</div>
            </div>
            <div class="feature-card">
                <div class="feature-icon">
                    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <rect x="4" y="8" width="16" height="11" rx="2"></rect>
                        <path d="M9 4h6"></path>
                        <path d="M12 4v4"></path>
                        <circle cx="9" cy="13" r="1"></circle>
                        <circle cx="15" cy="13" r="1"></circle>
                    </svg>
                </div>
                <div class="feature-title">Assistente AI dedicato</div>
                <div class="feature-copy">Un chatbot che ti guida nella scelta dei parametri, suggerendo best practice.</div>
            </div>
            <div class="feature-card">
                <div class="feature-icon">
                    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M16 3h5v5"></path>
                        <path d="M4 20l8-8"></path>
                        <path d="M21 3l-9 9"></path>
                        <path d="M4 4h5v5"></path>
                        <path d="M16 16l5 5"></path>
                    </svg>
                </div>
                <div class="feature-title">Naming convention unificata</div>
                <div class="feature-copy">Parametri coerenti tra team e campagne, addio a UTM duplicati o incoerenti.</div>
            </div>
            <div class="feature-card">
                <div class="feature-icon">
                    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M12 3l7 3v6c0 5-3.5 8.8-7 10-3.5-1.2-7-5-7-10V6l7-3z"></path>
                        <path d="M9 12l2 2 4-4"></path>
                    </svg>
                </div>
                <div class="feature-title">Validazione automatica</div>
                <div class="feature-copy">Controllo in tempo reale di errori, duplicati e formattazione prima di generare l'URL.</div>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    components.html(
        """
        <script>
            (function () {
                const doc = window.parent && window.parent.document ? window.parent.document : document;
                const cta = doc.getElementById("hero-open-chat-cta");
                if (!cta || cta.dataset.chatBound === "1") return;

                const openChat = () => {
                    let wrBtn = null;
                    try {
                        wrBtn = doc.querySelector('div[data-testid="stColumn"]:has(div.fab-unique-marker) button');
                    } catch (e) {}
                    if (!wrBtn) {
                        const cols = Array.from(doc.querySelectorAll('div[data-testid="stColumn"]'));
                        for (const col of cols) {
                            if (col.querySelector('.fab-unique-marker')) {
                                wrBtn = col.querySelector('button');
                                if (wrBtn) break;
                            }
                        }
                    }
                    if (wrBtn) {
                        wrBtn.click();
                    }
                };

                cta.addEventListener("click", function (ev) {
                    ev.preventDefault();
                    openChat();
                });
                cta.addEventListener("keydown", function (ev) {
                    if (ev.key === "Enter" || ev.key === " ") {
                        ev.preventDefault();
                        openChat();
                    }
                });
                cta.dataset.chatBound = "1";
            })();
        </script>
        """,
        height=0,
    )

    # --- CONTESTO CLIENTE ATTIVO (LINK FIRMATO O SCELTA INTERNA WR) ---
    locked_client_id = st.session_state.get("client_id_lock", "")
    selected_builder_client_id = normalize_client_id(st.session_state.get("builder_selected_client_id", ""))
    active_client_id = ""
    active_client_config = None
    lock_resolution_note = ""
    if locked_client_id:
        active_client_id, active_client_config, lock_resolution_note = resolve_locked_client_context(locked_client_id)
    elif is_webranking_user and selected_builder_client_id:
        active_client_id, active_client_config, lock_resolution_note = resolve_locked_client_context(selected_builder_client_id)
    st.session_state["active_client_id"] = active_client_id or ""
    st.session_state["active_client_config"] = active_client_config
    st.session_state["active_client_rules_text"] = build_client_rules_text_for_chatbot(active_client_config)

    if active_client_id:
        if active_client_config:
            st.info(f"Tool configurato sul cliente: {active_client_id}")
            if lock_resolution_note:
                st.caption(lock_resolution_note)
            st.caption("Apri il chatbot con il pulsante WR in basso a destra.")
        else:
            st.warning(f"Nessuna configurazione trovata per il cliente bloccato: {active_client_id}")

    if st.session_state.get("client_lock_error"):
        st.warning(st.session_state.get("client_lock_error"))
    # --- TABS DI NAVIGAZIONE ---
    tab_builder, tab_checker, tab_client_config, tab_history = st.tabs(
        ["Build URL", "Check URL", "Client Configuration", "UTM History & Tracking"]
    )

    # --- SESSION STATE PER CHAT ---
    if "messages" not in st.session_state:
        st.session_state.messages = []

    # ==============================================================================
    # TAB 1: UTM GENERATOR (BUILDER)
    # ==============================================================================
    with tab_builder:
        st.markdown(
            """
            <div class="builder-head">
                <div>
                    <div class="builder-head-title">Campaign URL Builder</div>
                    <div class="builder-head-sub">Seleziona la property GA4 per caricare source e medium reali.</div>
                </div>
                <div class="builder-head-right">
                    <span class="builder-required-pill">0/3 required</span>
                    <span class="builder-reset">↻ Reset</span>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        selected_prop_name = None
        sel_prop_id = None
        is_locked_client_view = bool(st.session_state.get("client_id_lock"))

        if is_webranking_user and not is_locked_client_view:
            saved_ids = list_saved_client_ids()
            builder_cfg_options = ["Nessuna configurazione"] + saved_ids
            current_builder_cfg = normalize_client_id(st.session_state.get("builder_selected_client_id", ""))
            default_cfg_idx = builder_cfg_options.index(current_builder_cfg) if current_builder_cfg in builder_cfg_options else 0
            picked_builder_cfg = st.selectbox(
                "Configurazione cliente (solo interno WR)",
                builder_cfg_options,
                index=default_cfg_idx,
                key="builder_client_config_select",
                help="Selezionando un cliente vengono preimpostate account/property e regole dal file configurazione.",
            )
            picked_norm = normalize_client_id(picked_builder_cfg) if picked_builder_cfg != "Nessuna configurazione" else ""
            if picked_norm != current_builder_cfg:
                st.session_state["builder_selected_client_id"] = picked_norm
                st.rerun()

        active_client_config = st.session_state.get("active_client_config") or {}
        client_rule_sources, client_rule_mediums, _client_rule_campaign_types = extract_client_rule_values(active_client_config)
        prop_channels = ["Paid Search", "Paid Social", "Display", "Email", "Organic Social", "Affiliate", "Video", "Altro"]
        raw_prop_cfg = active_client_config.get("property_config") if isinstance(active_client_config.get("property_config"), dict) else {}
        prop_config = {
            "default_country": str(raw_prop_cfg.get("default_country", "it") or "it"),
            "expected_domain": str(raw_prop_cfg.get("expected_domain", "")).strip().lower(),
        }
        real_sources = []
        real_mediums = []
        source_medium_map = {}

        # Applica defaults quando cambia profilo cliente attivo nel Builder.
        builder_profile_token = normalize_client_id(active_client_config.get("client_id", "")) if active_client_config else ""
        if st.session_state.get("builder_profile_token") != builder_profile_token:
            if builder_profile_token:
                expected_domain = str(prop_config.get("expected_domain", "")).strip()
                if expected_domain:
                    st.session_state["builder_url_domain"] = expected_domain
                default_country = normalize_token(prop_config.get("default_country", "")) or "it"
                st.session_state["campaign_country_language"] = default_country
                if client_rule_sources:
                    st.session_state["req_src_val_select"] = client_rule_sources[0]
                if client_rule_mediums:
                    st.session_state["req_med_val_select"] = client_rule_mediums[0]
            st.session_state["builder_profile_token"] = builder_profile_token

        with st.container(border=True):
            st.markdown('<div class="builder-box-marker"></div>', unsafe_allow_html=True)
            st.markdown('<div class="builder-card-title"><span class="builder-icon-dot">⋮</span>Collegamento GA4</div>', unsafe_allow_html=True)
            ga_col1, ga_col2 = st.columns([1.2, 1], gap="small")
            if "ga4_accounts" not in st.session_state:
                with st.spinner("Caricamento Account GA4..."):
                    st.session_state.ga4_accounts = get_ga4_accounts_structure(st.session_state.credentials)
            accounts_structure = st.session_state.ga4_accounts
            if accounts_structure:
                account_names = [a["display_name"] for a in accounts_structure]
                preferred_ga4_client_name = str(active_client_config.get("ga4_client_name", "")).strip()
                selected_account = None
                selected_account_name = ""
                default_account_idx = 0
                if preferred_ga4_client_name:
                    selected_account = next(
                        (
                            a for a in accounts_structure
                            if str(a.get("display_name", "")).strip().lower() == preferred_ga4_client_name.lower()
                        ),
                        None
                    )
                    if not selected_account:
                        selected_account = next(
                            (
                                a for a in accounts_structure
                                if preferred_ga4_client_name.lower() in str(a.get("display_name", "")).strip().lower()
                            ),
                            None
                        )
                if selected_account:
                    selected_name = str(selected_account.get("display_name", "")).strip()
                    if selected_name in account_names:
                        default_account_idx = account_names.index(selected_name)
                account_widget_key = f"builder_ga4_account_{builder_profile_token or 'none'}"
                property_widget_key = f"builder_ga4_property_{builder_profile_token or 'none'}"
                with ga_col1:
                    if selected_account and is_locked_client_view:
                        selected_account_name = str(selected_account.get("display_name", "")).strip()
                        st.text_input(
                            "GA4 Account",
                            value=selected_account_name,
                            disabled=True,
                            key=f"builder_locked_account_{st.session_state.get('active_client_id', '') or 'none'}",
                        )
                    else:
                        selected_account_name = st.selectbox("GA4 Account", account_names, index=default_account_idx, key=account_widget_key)
                        selected_account = next((a for a in accounts_structure if a["display_name"] == selected_account_name), None)
                if selected_account and selected_account["properties"]:
                    prop_map = {p["display_name"]: p["property_id"] for p in selected_account["properties"]}
                    with ga_col2:
                        prop_names = list(prop_map.keys())
                        preferred_prop_id = str(active_client_config.get("ga4_property_id", "")).replace("properties/", "").strip()
                        default_prop_idx = 0
                        if preferred_prop_id:
                            for idx, prop_name in enumerate(prop_names):
                                pid_raw = str(prop_map.get(prop_name, "")).replace("properties/", "").strip()
                                if pid_raw == preferred_prop_id:
                                    default_prop_idx = idx
                                    break
                        selected_prop_name = st.selectbox("GA4 Property", prop_names, index=default_prop_idx, key=property_widget_key)
                    if selected_prop_name:
                        sel_prop_id = prop_map[selected_prop_name]
                        current_prop_key = f"sources_{sel_prop_id}"
                        if current_prop_key not in st.session_state:
                            with st.spinner("Lettura sorgenti reali dalla property..."):
                                st.session_state[current_prop_key] = get_top_traffic_sources(sel_prop_id, st.session_state.credentials)
                        current_medium_key = f"mediums_{sel_prop_id}"
                        if current_medium_key not in st.session_state:
                            with st.spinner("Lettura medium reali dalla property..."):
                                st.session_state[current_medium_key] = get_top_traffic_mediums(sel_prop_id, st.session_state.credentials)
                        current_pairs_key = f"source_medium_pairs_{sel_prop_id}"
                        if current_pairs_key not in st.session_state:
                            with st.spinner("Lettura relazione source-medium dalla property..."):
                                st.session_state[current_pairs_key] = get_source_medium_pairs(sel_prop_id, st.session_state.credentials)
                        real_sources = st.session_state.get(current_prop_key, [])
                        real_mediums = st.session_state.get(current_medium_key, [])
                        pairs = st.session_state.get(current_pairs_key, [])
                        source_medium_map = {}
                        source_medium_seen = {}
                        for src_raw, med_raw in pairs:
                            src_n = normalize_token(src_raw)
                            med_n = normalize_medium_token(med_raw)
                            if src_n and med_n:
                                if src_n not in source_medium_map:
                                    source_medium_map[src_n] = []
                                    source_medium_seen[src_n] = set()
                                if med_n not in source_medium_seen[src_n]:
                                    source_medium_map[src_n].append(med_n)
                                    source_medium_seen[src_n].add(med_n)
                        if real_sources:
                            global SOURCE_OPTIONS
                            SOURCE_OPTIONS = sorted(list(set(get_source_options() + real_sources)))
                            preview = ", ".join(real_sources[:6])
                            st.markdown(f'<div class="tilda-note">Sorgenti recenti da GA4: {html_lib.escape(preview)}</div>', unsafe_allow_html=True)
                        if real_mediums:
                            medium_preview = ", ".join(real_mediums[:6])
                            st.markdown(f'<div class="tilda-note">Medium recenti da GA4: {html_lib.escape(medium_preview)}</div>', unsafe_allow_html=True)
                else:
                    st.warning("Nessuna property disponibile nell'account selezionato.")
            else:
                st.warning("Nessun account GA4 trovato o accesso negato.")

        st.session_state["builder_selected_property_id"] = str(sel_prop_id or "")
        st.session_state["builder_selected_property_name"] = str(selected_prop_name or "")

        with st.container(border=True):
            st.markdown('<div class="builder-box-marker"></div>', unsafe_allow_html=True)
            st.markdown('<div class="builder-card-title"><span class="builder-step-dot">1</span>URL di destinazione</div>', unsafe_allow_html=True)
            url_col1, url_col2 = st.columns([0.16, 0.84], gap="small")
            with url_col1:
                url_scheme = st.selectbox(" ", ["https://", "http://"], key="builder_url_scheme")
            with url_col2:
                url_domain = st.text_input(
                    "URL di destinazione",
                    key="builder_url_domain",
                    placeholder="thismywebsite.com",
                    help="Dove atterrerà l’utente quando clicca sulla CTA?"
                )
            url_domain = url_domain.strip()
            if url_domain.startswith("http://") or url_domain.startswith("https://"):
                destination_url = url_domain
            else:
                destination_url = f"{url_scheme}{url_domain}" if url_domain else ""
            domain_hint = prop_config.get("expected_domain", "")
            if not url_domain:
                st.markdown('<div class="msg-warning">⚠️ Inserisci un URL completo (es. https://example.com/pagina)</div>', unsafe_allow_html=True)
            elif not is_valid_url(destination_url):
                st.markdown('<div class="msg-error">❌ URL non valido. Usa formato corretto: https://dominio.tld/percorso</div>', unsafe_allow_html=True)
            elif domain_hint and domain_hint not in destination_url:
                st.markdown(f'<div class="msg-warning">⚠️ Dominio diverso da quello atteso: {html_lib.escape(domain_hint)}</div>', unsafe_allow_html=True)
            else:
                st.markdown('<div class="msg-success">✅ URL valido</div>', unsafe_allow_html=True)

        with st.container(border=True):
            st.markdown('<div class="builder-box-marker"></div>', unsafe_allow_html=True)
            st.markdown('<div class="builder-card-title"><span class="builder-step-dot">2</span>Parametri UTM</div>', unsafe_allow_html=True)
            head_l, head_r = st.columns([0.78, 0.22], gap="small")
            with head_r:
                st.markdown('<div class="builder-naming-link">▸ Naming Convention ↗</div>', unsafe_allow_html=True)
            with st.expander("Golden Rules Naming Convention", expanded=False):
                st.markdown("""
                - Usa solo minuscole (GA4 è case-sensitive).
                - Evita spazi e caratteri speciali (`? % & $ !`); usa `-` o `_`.
                - Sii coerente nella struttura dei nomi.
                - Sii descrittivo ma conciso.
                - Preferisci i trattini (`-`) agli underscore (`_`) quando possibile.
                """)
            if is_locked_client_view or active_client_config:
                source_mode = "Custom values"
                st.caption("Modalità cliente attiva: opzioni filtrate da regole cliente.")
            else:
                source_mode = st.radio(
                    "Traffic source mode",
                    ["Paid", "Email", "SMS", "Custom values"],
                    horizontal=True,
                    label_visibility="collapsed"
                )

            source_default = ""
            medium_default = ""
            if source_mode == "Paid":
                source_default = "google"
                medium_default = "cpc"
            elif source_mode == "Email":
                source_default = "newsletter"
                medium_default = "email"
            elif source_mode == "SMS":
                source_default = "sms"
                medium_default = "sms"

            if active_client_config:
                if client_rule_sources:
                    source_default = normalize_token(client_rule_sources[0])
                if client_rule_mediums:
                    medium_default = normalize_medium_token(client_rule_mediums[0])

            # In "Custom values" non mostriamo un preset extra:
            # l'utente compila direttamente utm_source/utm_medium nel blocco parametri.
            if source_mode == "Custom values":
                final_input_source = source_default
            else:
                final_input_source = source_default

            st.markdown("")
            req_col, opt_col = st.columns(2, gap="large")
            with req_col:
                st.markdown('<div class="builder-subhead">REQUIRED</div>', unsafe_allow_html=True)
                st.caption("Campaign source")
                s1, s2 = st.columns([0.28, 0.72], gap="small")
                with s1:
                    st.text_input(" ", value="utm_source", key="req_src_key", disabled=True)
                with s2:
                    normalized_sources = [normalize_token(s) for s in real_sources if normalize_token(s)]
                    if is_locked_client_view and client_rule_sources:
                        normalized_sources = list(client_rule_sources)
                    elif client_rule_sources:
                        normalized_sources = list(normalized_sources) + list(client_rule_sources)
                    if not normalized_sources and not selected_prop_name:
                        normalized_sources = [normalize_token(s) for s in get_source_options() if normalize_token(s) and "altro" not in s.lower()]
                    normalized_sources = order_by_ga4_priority(normalized_sources, real_sources, normalize_token)
                    source_options = filter_options_by_source_mode(normalized_sources, source_mode, "source")
                    source_options = order_by_ga4_priority(source_options, real_sources, normalize_token)
                    if not source_options:
                        source_options = [normalize_token(source_default)] if normalize_token(source_default) else []
                    if not is_locked_client_view:
                        source_options = source_options + ["manuale"]
                    source_default = normalize_token(final_input_source)
                    source_index = source_options.index(source_default) if source_default in source_options else 0
                    selected_source_value = st.selectbox(
                        "Source value",
                        source_options,
                        index=source_index,
                        key="req_src_val_select",
                        help="Su quale piattaforma o canale stai attivando questa campagna?"
                    )
                    if selected_source_value == "manuale":
                        utm_source = st.text_input(
                            "Manual source",
                            key="req_src_val_manual",
                            placeholder="google, facebook",
                            help="Su quale piattaforma o canale stai attivando questa campagna?"
                        )
                    else:
                        utm_source = selected_source_value
                    source_issues, source_suggest = validate_naming_rules(utm_source, prefer_hyphen=True)
                    if source_issues:
                        st.markdown(
                            f'<div class="msg-error">❌ Source non conforme: {", ".join(source_issues)}. '
                            f'Suggerito: <b>{html_lib.escape(source_suggest)}</b></div>',
                            unsafe_allow_html=True
                        )
                    if client_rule_sources:
                        src_norm = normalize_token(utm_source)
                        if src_norm and src_norm not in set(client_rule_sources):
                            st.markdown(
                                '<div class="msg-warning">⚠️ Source non presente nelle regole cliente caricate.</div>',
                                unsafe_allow_html=True
                            )
                st.caption("Campaign medium")
                m1, m2 = st.columns([0.28, 0.72], gap="small")
                with m1:
                    st.text_input(" ", value="utm_medium", key="req_med_key", disabled=True)
                with m2:
                    normalized_mediums = [normalize_medium_token(m) for m in real_mediums if normalize_medium_token(m)]
                    if is_locked_client_view and client_rule_mediums:
                        normalized_mediums = list(client_rule_mediums)
                    elif client_rule_mediums:
                        normalized_mediums = list(normalized_mediums) + list(client_rule_mediums)
                    # Se c'e' property selezionata, medium dropdown basato su sessionMedium GA4.
                    # Usiamo fallback tabellare solo quando GA4 non e' selezionato.
                    if not normalized_mediums and not selected_prop_name:
                        fallback_mediums = []
                        for row in GUIDE_TABLE_DATA:
                            fallback_mediums.extend([normalize_medium_token(x) for x in str(row.get("utm_medium", "")).replace("|", ",").split(",") if normalize_medium_token(x)])
                        normalized_mediums = list(fallback_mediums)
                    normalized_mediums = order_by_ga4_priority(normalized_mediums, real_mediums, normalize_medium_token)
                    # Collega medium alla source selezionata usando la mappa GA4 source->medium.
                    selected_source_normalized = normalize_token(utm_source) if 'utm_source' in locals() else ""
                    mapped_mediums = source_medium_map.get(selected_source_normalized, [])
                    if mapped_mediums:
                        # Se abbiamo medium reali gia' mappati sulla source, NON rifiltriamo per canale:
                        # la relazione source->medium GA4 e' la fonte di verita'.
                        medium_options = mapped_mediums
                    else:
                        # Fallback: nessuna coppia source-medium disponibile, applichiamo filtro di canale.
                        medium_options = filter_options_by_source_mode(normalized_mediums, source_mode, "medium")
                    medium_options = order_by_ga4_priority(medium_options, real_mediums, normalize_medium_token)
                    if not medium_options:
                        medium_options = [normalize_medium_token(medium_default)] if normalize_medium_token(medium_default) else []
                    if not is_locked_client_view:
                        medium_options = medium_options + ["manuale"]
                    default_medium_pick = normalize_medium_token(medium_default)
                    medium_index = medium_options.index(default_medium_pick) if default_medium_pick in medium_options else 0
                    selected_medium_value = st.selectbox(
                        "Medium value",
                        medium_options,
                        index=medium_index,
                        key="req_med_val_select",
                        help="Che tipo di campagna sarà? organic, social organico, social paid, email, ecc"
                    )
                    if selected_medium_value == "manuale":
                        utm_medium = st.text_input(
                            "Manual medium",
                            key="req_med_val_manual",
                            placeholder="cpc, email, banner, article",
                            help="Che tipo di campagna sarà? organic, social organico, social paid, email, ecc"
                        )
                    else:
                        utm_medium = selected_medium_value
                    medium_issues, medium_suggest = validate_naming_rules(utm_medium, prefer_hyphen=False)
                    if medium_issues:
                        st.markdown(
                            f'<div class="msg-error">❌ Medium non conforme: {", ".join(medium_issues)}. '
                            f'Suggerito: <b>{html_lib.escape(medium_suggest)}</b></div>',
                            unsafe_allow_html=True
                        )
                    if client_rule_mediums:
                        med_norm = normalize_medium_token(utm_medium)
                        if med_norm and med_norm not in set(client_rule_mediums):
                            st.markdown(
                                '<div class="msg-warning">⚠️ Medium non presente nelle regole cliente caricate.</div>',
                                unsafe_allow_html=True
                            )
                st.caption("Campaign name")
                c1, c2 = st.columns([0.28, 0.72], gap="small")
                with c1:
                    st.text_input(" ", value="utm_campaign", key="req_cmp_key", disabled=True)
                with c2:
                    utm_campaign = st.text_input(
                        "Nome campagna",
                        key="req_cmp_val",
                        placeholder="promo, discount, sale",
                        help="Come chiameresti questa campagna internamente?",
                        autocomplete="new-password"
                    )
                    cmp_issues, cmp_suggest = validate_naming_rules(utm_campaign, prefer_hyphen=True)
                    if cmp_issues:
                        st.markdown(
                            f'<div class="msg-error">❌ Nome campagna non conforme: {", ".join(cmp_issues)}. '
                            f'Suggerito: <b>{html_lib.escape(cmp_suggest)}</b></div>',
                            unsafe_allow_html=True
                        )
                type_col1, type_col2 = st.columns([0.28, 0.72], gap="small")
                with type_col1:
                    st.text_input(" ", value="campaign_type", key="req_typ_key", disabled=True)
                with type_col2:
                    campaign_type = st.text_input(
                        "Tipo campagna",
                        key="req_typ_val",
                        placeholder="always-on, promo, launch",
                        help="Tipologia della campagna (es. promo, launch, always-on)."
                    )
                    type_issues, type_suggest = validate_naming_rules(campaign_type, prefer_hyphen=True)
                    if type_issues:
                        st.markdown(
                            f'<div class="msg-error">❌ Tipo campagna non conforme: {", ".join(type_issues)}. '
                            f'Suggerito: <b>{html_lib.escape(type_suggest)}</b></div>',
                            unsafe_allow_html=True
                        )
                meta_col1, meta_col2 = st.columns(2, gap="small")
                with meta_col1:
                    campaign_start_date = st.date_input(
                        "Data di inizio campagna",
                        datetime.today(),
                        key="campaign_start_date",
                        format="DD/MM/YYYY",
                        help="Quando partirà la campagna?"
                    )
                with meta_col2:
                    campaign_language = st.text_input(
                        "Country/Lingua",
                        key="campaign_country_language",
                        placeholder="es. it, de, fr",
                        help="In che lingua è la comunicazione principale di questa campagna?"
                    )
                    lang_issues, lang_suggest = validate_naming_rules(campaign_language, prefer_hyphen=True)
                    if lang_issues:
                        st.markdown(
                            f'<div class="msg-error">❌ Country/Lingua non conforme: {", ".join(lang_issues)}. '
                            f'Suggerito: <b>{html_lib.escape(lang_suggest)}</b></div>',
                            unsafe_allow_html=True
                        )

            with opt_col:
                st.markdown('<div class="builder-subhead">OPTIONAL</div>', unsafe_allow_html=True)
                st.caption("Campaign content")
                o1, o2 = st.columns([0.28, 0.72], gap="small")
                with o1:
                    st.text_input(" ", value="utm_content", key="opt_cnt_key", disabled=True)
                with o2:
                    utm_content = st.text_input(
                        "Content",
                        key="opt_cnt_val",
                        placeholder="cta, banner, image",
                        help="Dettaglia variante creativa, posizione o formato del contenuto."
                    )
                    cnt_issues, cnt_suggest = validate_naming_rules(utm_content, prefer_hyphen=True)
                    if cnt_issues:
                        st.markdown(
                            f'<div class="msg-error">❌ Content non conforme: {", ".join(cnt_issues)}. '
                            f'Suggerito: <b>{html_lib.escape(cnt_suggest)}</b></div>',
                            unsafe_allow_html=True
                        )
                st.caption("Campaign term")
                t1, t2 = st.columns([0.28, 0.72], gap="small")
                with t1:
                    st.text_input(" ", value="utm_term", key="opt_trm_key", disabled=True)
                with t2:
                    utm_term = st.text_input(
                        "Term",
                        key="opt_trm_val",
                        placeholder="keyword, prospecting, retargeting",
                        help="Usato per keyword o segmenti specifici della campagna."
                    )
                    trm_issues, trm_suggest = validate_naming_rules(utm_term, prefer_hyphen=True)
                    if trm_issues:
                        st.markdown(
                            f'<div class="msg-error">❌ Term non conforme: {", ".join(trm_issues)}. '
                            f'Suggerito: <b>{html_lib.escape(trm_suggest)}</b></div>',
                            unsafe_allow_html=True
                        )

        p_src = normalize_token(utm_source)
        p_med = normalize_medium_token(utm_medium)
        p_cmp_name = normalize_token(utm_campaign)
        p_cmp_type = normalize_token(campaign_type)
        p_cmp_lang = normalize_token(campaign_language)
        p_cmp_date = campaign_start_date.strftime("%d%m%Y")
        cmp_parts = [p for p in [p_cmp_lang, p_cmp_type, p_cmp_name, p_cmp_date] if p]
        p_cmp = "_".join(cmp_parts)
        p_cnt = normalize_token(utm_content)
        p_trm = normalize_token(utm_term)

        errors = []
        if not destination_url or not is_valid_url(destination_url):
            errors.append("URL")
        if not p_src:
            errors.append("utm_source")
        if not p_med:
            errors.append("utm_medium")
        if not p_cmp_name:
            errors.append("nome_campagna")
        if not p_cmp_type:
            errors.append("campaign_type")
        if not p_cmp_lang:
            errors.append("country_lingua")
        if source_issues:
            errors.append("source_naming")
        if medium_issues:
            errors.append("medium_naming")
        if cmp_issues:
            errors.append("campaign_name_naming")
        if type_issues:
            errors.append("campaign_type_naming")
        if lang_issues:
            errors.append("country_lingua_naming")
        if utm_content and cnt_issues:
            errors.append("content_naming")
        if utm_term and trm_issues:
            errors.append("term_naming")

        st.markdown('<div class="tilda-section">Result URL</div>', unsafe_allow_html=True)
        final_url = ""
        if errors:
            st.markdown(
                f'<div class="output-box-ready"><b>Compila i campi obbligatori.</b><br><small>Mancano: {", ".join(errors)}</small></div>',
                unsafe_allow_html=True
            )
        else:
            sep = "&" if "?" in destination_url else "?"
            final_url = f"{destination_url}{sep}utm_source={p_src}&utm_medium={p_med}&utm_campaign={p_cmp}"
            if p_cnt:
                final_url += f"&utm_content={p_cnt}"
            if p_trm:
                final_url += f"&utm_term={p_trm}"

            # Save candidate entry for history tab
            history_entry = {
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "user_email": st.session_state.get("user_email", ""),
                "property_id": sel_prop_id or "",
                "property_name": selected_prop_name or "",
                "campaign_name": utm_campaign,
                "live_date": campaign_start_date.strftime("%d/%m/%Y"),
                "utm_source": p_src,
                "utm_medium": p_med,
                "utm_campaign": p_cmp,
                "final_url": final_url,
                "expected_channel_group": infer_expected_channel_group(p_med),
            }
        result_btn_col, result_input_col = st.columns([0.12, 0.88], gap="small")
        with result_btn_col:
            copy_value = json.dumps(final_url if final_url else "")
            copy_disabled = "disabled" if not final_url else ""
            components.html(
                f"""
                <style>
                    html, body {{
                        margin: 0;
                        padding: 0;
                    }}
                    #copy-btn {{
                        width: 100%;
                        height: 40px;
                        border-radius: 8px;
                        border: 1px solid #c8d8e8;
                        background: #f7f9fc;
                        color: #1f2f3f;
                        font-weight: 600;
                        cursor: pointer;
                    }}
                    #copy-btn:disabled {{
                        opacity: 0.65;
                        cursor: not-allowed;
                    }}
                </style>
                <button id="copy-btn" {copy_disabled}
                    >
                    Copy
                </button>
                <script>
                    const btn = document.getElementById('copy-btn');
                    btn?.addEventListener('click', async () => {{
                        try {{
                            await navigator.clipboard.writeText({copy_value});
                            btn.innerText = 'Copied';
                            setTimeout(() => btn.innerText = 'Copy', 1200);
                        }} catch (e) {{
                            btn.innerText = 'Copy failed';
                            setTimeout(() => btn.innerText = 'Copy', 1200);
                        }}
                    }});
                </script>
                """,
                height=40,
            )
        with result_input_col:
            st.text_input(
                "Result",
                value=final_url,
                placeholder="You will see the result of your actions here...",
                label_visibility="collapsed"
            )
        if final_url:
            if st.button("Salva nello storico", key="save_history_btn", use_container_width=True):
                upsert_utm_history_entry(history_entry)
                st.success("Link salvato nello storico UTM.")

        with st.expander("📘 Tabella guida parametri UTM"):
            st.table(pd.DataFrame(GUIDE_TABLE_DATA))

    # ==============================================================================
    # TAB 2: UTM CHECKER (CORRETTO E PULITO)
    # ==============================================================================
    with tab_checker:
        st.markdown("### Check URL")
        st.markdown("Incolla un URL e controlla rapidamente stato HTTPS, struttura e parametri UTM.")
        
        check_url_input = st.text_input("Inserisci qui il tuo URL con UTM", placeholder="https://sito.it?utm_source=...")
        
        if st.button("Check URL", type="primary"):
            if not check_url_input:
                st.error("Inserisci un URL per procedere.")
            else:
                try:
                    parsed = urlparse(check_url_input)
                    params = parse_qs(parsed.query)
                    
                    # 1. URL CHECKS
                    st.markdown("### URL checks")

                    is_https = parsed.scheme == 'https'
                    length = len(check_url_input)
                    has_utm = any(k.startswith('utm_') for k in params.keys())

                    https_badge = '<span class="status-badge badge-ok">Valido</span>' if is_https else '<span class="status-badge badge-warn">Non sicuro</span>'
                    len_badge = '<span class="status-badge badge-ok">Valido</span>' if length < 2048 else '<span class="status-badge badge-warn">Lungo</span>'
                    utm_badge = '<span class="status-badge badge-ok">Presente</span>' if has_utm else '<span class="status-badge badge-bad">Assente</span>'

                    st.markdown(f"""
                    <div class="checks-grid">
                        <div class="checks-item">
                            <div class="checks-label">HTTPS</div>
                            {https_badge}
                        </div>
                        <div class="checks-item">
                            <div class="checks-label">Lunghezza URL ({length} caratteri)</div>
                            {len_badge}
                        </div>
                        <div class="checks-item">
                            <div class="checks-label">Parametri UTM</div>
                            {utm_badge}
                        </div>
                    </div>
                    """, unsafe_allow_html=True)

                    # 2. UTM CHECKS
                    st.markdown("### UTM checks")

                    fields_to_check = [
                        ("UTM Source", "utm_source", True),
                        ("UTM Medium", "utm_medium", True),
                        ("UTM Campaign", "utm_campaign", True),
                        ("UTM Term", "utm_term", False),
                        ("UTM Content", "utm_content", False)
                    ]

                    html_output = '<div class="utm-compact-grid">'
                    for label, key, is_required in fields_to_check:
                        val_list = params.get(key, [])
                        val = val_list[0] if val_list else None

                        if val:
                            badge = '<span class="status-badge badge-ok">Valido</span>'
                            display_val = html_lib.escape(val)
                        else:
                            if is_required:
                                badge = '<span class="status-badge badge-bad">Mancante</span>'
                                display_val = '<span class="error-text">Parametro obbligatorio assente</span>'
                            else:
                                badge = '<span class="status-badge badge-opt">Opzionale</span>'
                                display_val = '<span style="color:#7a8896">Non valorizzato</span>'

                        html_output += (
                            '<div class="utm-param-item">'
                            f'<div class="utm-param-title">{label}</div>'
                            f'{badge}'
                            f'<div class="utm-param-value">{display_val}</div>'
                            '</div>'
                        )

                    html_output += "</div>"
                    st.markdown(html_output, unsafe_allow_html=True)

                except Exception as e:
                    st.error(f"Errore analisi URL: {e}")

    # ==============================================================================
    # TAB 3: CLIENT CONFIGURATION
    # ==============================================================================
    with tab_client_config:
        st.markdown("### Client Configuration")
        st.markdown("Configura app cliente: upload UTM Builder, selezione GA4 e link dedicato.")

        # Registro rapido configurazioni salvate (ultimo update + metadati principali)
        cfg_rows = []
        for cfg_id in list_saved_client_ids():
            cfg_payload = load_client_config(cfg_id) or {}
            ga4_prop_id = str(cfg_payload.get("ga4_property_id", "")).replace("properties/", "").strip()
            ga4_prop_name = str(cfg_payload.get("ga4_property_name", "")).strip()
            if ga4_prop_name and ga4_prop_id:
                ga4_prop_display = f"{ga4_prop_name} ({ga4_prop_id})"
            elif ga4_prop_id:
                ga4_prop_display = ga4_prop_id
            elif ga4_prop_name:
                ga4_prop_display = ga4_prop_name
            else:
                ga4_prop_display = "Non impostata"
            cfg_rows.append(
                {
                    "client_id": cfg_id,
                    "version": cfg_payload.get("version", "-"),
                    "updated_at": cfg_payload.get("updated_at", "-"),
                    "updated_by": cfg_payload.get("updated_by", "-"),
                    "ga4_account": cfg_payload.get("ga4_client_name", "-"),
                    "ga4_property": ga4_prop_display,
                    "ga4_property_id": ga4_prop_id or "-",
                    "source_file_name": cfg_payload.get("source_file_name", "-"),
                    "shared_link": str(cfg_payload.get("shared_link", "") or "-"),
                }
            )
        if st.session_state.get("client_id_lock"):
            st.warning("Modalità cliente bloccata attiva in questa sessione.")
            if st.button("Sblocca modalità cliente", key="unlock_client_mode_btn"):
                st.session_state.client_id_lock = ""
                st.session_state.client_lock_error = ""
                try:
                    st.query_params.clear()
                except Exception:
                    pass
                st.rerun()

        existing_client_ids = list_saved_client_ids()
        if "cfg_manage_mode" not in st.session_state:
            st.session_state.cfg_manage_mode = "Modifica configurazione" if existing_client_ids else "Nuova configurazione aggiuntiva"
        if "cfg_selected_existing_client" not in st.session_state:
            st.session_state.cfg_selected_existing_client = existing_client_ids[0] if existing_client_ids else ""

        if "cfg_selected_client" not in st.session_state:
            st.session_state.cfg_selected_client = "Nuova configurazione"
        if "cfg_form_loaded_client" not in st.session_state:
            st.session_state.cfg_form_loaded_client = ""
        if "cfg_client_id_input" not in st.session_state:
            st.session_state.cfg_client_id_input = ""
        if "cfg_ga4_client_name" not in st.session_state:
            st.session_state.cfg_ga4_client_name = ""
        if "cfg_ga4_property_id" not in st.session_state:
            st.session_state.cfg_ga4_property_id = ""
        if "cfg_ga4_property_name" not in st.session_state:
            st.session_state.cfg_ga4_property_name = ""
        if "cfg_expected_domain" not in st.session_state:
            st.session_state.cfg_expected_domain = ""
        if "cfg_default_country" not in st.session_state:
            st.session_state.cfg_default_country = "it"
        if "cfg_rules_rows" not in st.session_state:
            st.session_state.cfg_rules_rows = []
        if "cfg_rules_file_name" not in st.session_state:
            st.session_state.cfg_rules_file_name = ""
        if "cfg_rules_file_sha256" not in st.session_state:
            st.session_state.cfg_rules_file_sha256 = ""
        if "cfg_base_url" not in st.session_state:
            st.session_state.cfg_base_url = "https://utm-builder.streamlit.app/"

        manage_options = ["Modifica configurazione", "Nuova configurazione aggiuntiva"]
        st.radio(
            "Operazione",
            manage_options,
            key="cfg_manage_mode",
            horizontal=True,
        )

        selected_cfg = "Nuova configurazione"
        if st.session_state.cfg_manage_mode == "Modifica configurazione":
            if existing_client_ids:
                if st.session_state.get("cfg_selected_existing_client", "") not in existing_client_ids:
                    st.session_state.cfg_selected_existing_client = existing_client_ids[0]
                selected_cfg = st.selectbox(
                    "Configurazione da modificare",
                    existing_client_ids,
                    key="cfg_selected_existing_client",
                )
            else:
                st.info("Nessuna configurazione esistente: passa a 'Nuova configurazione aggiuntiva'.")
        else:
            st.caption("Stai creando una nuova configurazione. Inserisci un nuovo Client ID nel form.")

        st.session_state.cfg_selected_client = selected_cfg

        if selected_cfg != "Nuova configurazione" and st.session_state.cfg_form_loaded_client != selected_cfg:
            cfg = load_client_config(selected_cfg) or {}
            prop_cfg = cfg.get("property_config") if isinstance(cfg.get("property_config"), dict) else {}
            st.session_state.cfg_client_id_input = str(cfg.get("client_id", selected_cfg))
            st.session_state.cfg_ga4_client_name = str(cfg.get("ga4_client_name", ""))
            st.session_state.cfg_ga4_property_id = str(cfg.get("ga4_property_id", ""))
            st.session_state.cfg_ga4_property_name = str(cfg.get("ga4_property_name", ""))
            st.session_state.cfg_expected_domain = str(prop_cfg.get("expected_domain", ""))
            st.session_state.cfg_default_country = str(prop_cfg.get("default_country", "it") or "it")
            st.session_state.cfg_rules_rows = list(cfg.get("rules_rows", []) or [])
            st.session_state.cfg_rules_file_name = str(cfg.get("source_file_name", ""))
            st.session_state.cfg_rules_file_sha256 = str(cfg.get("source_file_sha256", ""))
            st.session_state.cfg_form_loaded_client = selected_cfg
            st.rerun()
        if selected_cfg == "Nuova configurazione" and st.session_state.cfg_form_loaded_client:
            st.session_state.cfg_form_loaded_client = ""
            st.session_state.cfg_client_id_input = ""
            st.session_state.cfg_ga4_client_name = ""
            st.session_state.cfg_ga4_property_id = ""
            st.session_state.cfg_ga4_property_name = ""
            st.session_state.cfg_expected_domain = ""
            st.session_state.cfg_default_country = "it"
            st.session_state.cfg_rules_rows = []
            st.session_state.cfg_rules_file_name = ""
            st.session_state.cfg_rules_file_sha256 = ""
            st.rerun()

        if cfg_rows:
            st.markdown("#### Stato configurazioni clienti")
            st.dataframe(
                pd.DataFrame(cfg_rows).sort_values(by=["updated_at", "client_id"], ascending=[False, True]),
                use_container_width=True,
                hide_index=True,
            )

            st.markdown("#### Recupera o rigenera link cliente")
            recover_client_id = st.selectbox(
                "Cliente da recuperare",
                list_saved_client_ids(),
                key="recover_client_id_select",
            )
            recover_cfg = load_client_config(recover_client_id) or {}
            current_shared_link = str(recover_cfg.get("shared_link", "")).strip()
            st.text_input(
                "Link cliente corrente",
                value=current_shared_link,
                disabled=True,
            )
            if st.button("Rigenera link cliente", key="regen_client_link_btn"):
                if not CLIENT_LINK_SECRET:
                    st.warning("CLIENT_LINK_SECRET non configurato: impossibile rigenerare il link firmato.")
                else:
                    previous_link = str(recover_cfg.get("shared_link", "")).strip()
                    base_url = str(st.session_state.get("cfg_base_url", "")).strip() or "https://utm-builder.streamlit.app/"
                    if previous_link:
                        try:
                            parsed_prev = urlparse(previous_link)
                            if parsed_prev.scheme and parsed_prev.netloc:
                                base_url = f"{parsed_prev.scheme}://{parsed_prev.netloc}{parsed_prev.path}"
                        except Exception:
                            pass
                    if not base_url.startswith(("http://", "https://")):
                        base_url = f"https://{base_url}"
                    base_url = base_url.rstrip("/")

                    new_sig = sign_client_id(recover_client_id)
                    regenerated_link = f"{base_url}/?client_id={recover_client_id}&sig={new_sig}"

                    recover_cfg["shared_link"] = regenerated_link
                    recover_cfg["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    recover_cfg["updated_by"] = st.session_state.get("user_email", "")
                    save_client_config(recover_client_id, recover_cfg)
                    st.success("Link cliente rigenerato.")
                    st.code(regenerated_link, language="text")
        else:
            st.info("Nessuna configurazione cliente salvata.")

        st.markdown("#### 1) Carica file UTM Builder")
        uploaded_rules_file = st.file_uploader(
            "File UTM Builder (xlsx/csv)",
            type=["xlsx", "xls", "csv"],
            key="cfg_rules_uploader",
        )
        if uploaded_rules_file is not None:
            uploaded_bytes = uploaded_rules_file.getvalue()
            uploaded_sha = hashlib.sha256(uploaded_bytes).hexdigest()
            if uploaded_sha != st.session_state.get("cfg_rules_file_sha256", ""):
                try:
                    parsed_rows = parse_rules_rows_from_uploaded_file(uploaded_rules_file.name, uploaded_bytes)
                    st.session_state.cfg_rules_rows = parsed_rows
                    st.session_state.cfg_rules_file_name = str(uploaded_rules_file.name)
                    st.session_state.cfg_rules_file_sha256 = uploaded_sha
                    st.success(f"File caricato: {uploaded_rules_file.name} ({len(parsed_rows)} righe)")
                except Exception as e:
                    st.error(f"Errore lettura file UTM Builder: {e}")
        elif st.session_state.get("cfg_rules_file_name"):
            st.caption(f"File regole corrente: {st.session_state.get('cfg_rules_file_name')}")

        rules_preview_cfg = {"rules_rows": st.session_state.get("cfg_rules_rows", [])}
        prev_sources, prev_mediums, prev_campaign_types = extract_client_rule_values(rules_preview_cfg)
        st.caption(
            f"Regole estratte: source={len(prev_sources)} | medium={len(prev_mediums)} | campaign_type={len(prev_campaign_types)}"
        )

        current_rows = st.session_state.get("cfg_rules_rows", []) or []
        if current_rows:
            st.markdown("#### Anteprima file UTM Builder")
            preview_df = pd.DataFrame(current_rows)
            if "__sheet_name" in preview_df.columns:
                sheet_names = [s for s in preview_df["__sheet_name"].fillna("").astype(str).unique().tolist() if s]
                if sheet_names:
                    preview_tabs = st.tabs([f"Foglio: {s}" for s in sheet_names])
                    for i, sheet_name in enumerate(sheet_names):
                        with preview_tabs[i]:
                            sheet_df = preview_df[preview_df["__sheet_name"].astype(str) == sheet_name].copy()
                            sheet_df = sheet_df.drop(columns=["__sheet_name"], errors="ignore")
                            st.dataframe(sheet_df.head(20), use_container_width=True, hide_index=True)
                            if len(sheet_df) > 20:
                                st.caption(f"Mostrate 20 righe su {len(sheet_df)} del foglio '{sheet_name}'.")
                else:
                    st.dataframe(preview_df.head(20), use_container_width=True, hide_index=True)
            else:
                st.dataframe(preview_df.head(20), use_container_width=True, hide_index=True)
            if len(preview_df) > 20:
                st.caption(f"Totale righe importate: {len(preview_df)}.")

        if "ga4_accounts" not in st.session_state:
            with st.spinner("Caricamento account GA4..."):
                st.session_state.ga4_accounts = get_ga4_accounts_structure(st.session_state.credentials)
        accounts_structure = st.session_state.get("ga4_accounts", [])
        if not isinstance(accounts_structure, list):
            accounts_structure = []

        selected_cfg_account_name = ""
        selected_cfg_property_name = ""
        selected_cfg_property_id = ""
        st.markdown("#### 2) Seleziona account e property GA4")
        if accounts_structure:
            acc_names = [str(a.get("display_name", "")) for a in accounts_structure]
            pref_acc_name = str(st.session_state.get("cfg_ga4_client_name", "")).strip().lower()
            acc_idx = 0
            if pref_acc_name:
                for idx, name in enumerate(acc_names):
                    if name.strip().lower() == pref_acc_name:
                        acc_idx = idx
                        break
            selected_cfg_account_name = st.selectbox("Account GA4 cliente", acc_names, index=acc_idx, key="cfg_ga4_account_select")
            selected_acc = next((a for a in accounts_structure if str(a.get("display_name", "")) == selected_cfg_account_name), None)

            prop_list = (selected_acc or {}).get("properties", []) or []
            if prop_list:
                prop_labels = []
                prop_by_label = {}
                for p in prop_list:
                    prop_name = str(p.get("display_name", "")).strip()
                    prop_id_raw = str(p.get("property_id", "")).replace("properties/", "").strip()
                    label = f"{prop_name} ({prop_id_raw})" if prop_id_raw else prop_name
                    prop_labels.append(label)
                    prop_by_label[label] = p
                pref_prop_id = str(st.session_state.get("cfg_ga4_property_id", "")).replace("properties/", "").strip()
                prop_idx = 0
                if pref_prop_id:
                    for idx, label in enumerate(prop_labels):
                        candidate = prop_by_label.get(label, {})
                        candidate_id = str(candidate.get("property_id", "")).replace("properties/", "").strip()
                        if candidate_id == pref_prop_id:
                            prop_idx = idx
                            break
                selected_label = st.selectbox("Property GA4 cliente", prop_labels, index=prop_idx, key="cfg_ga4_property_select")
                selected_prop = prop_by_label.get(selected_label, {})
                selected_cfg_property_name = str(selected_prop.get("display_name", "")).strip()
                selected_cfg_property_id = str(selected_prop.get("property_id", "")).replace("properties/", "").strip()
            else:
                st.warning("Nessuna property disponibile per l'account selezionato.")
        else:
            st.warning("Nessun account GA4 disponibile.")

        if selected_cfg_account_name:
            st.session_state.cfg_ga4_client_name = selected_cfg_account_name
        if selected_cfg_property_name:
            st.session_state.cfg_ga4_property_name = selected_cfg_property_name
        if selected_cfg_property_id:
            st.session_state.cfg_ga4_property_id = selected_cfg_property_id

        st.markdown("#### 3) Configurazione app cliente")
        st.text_input("Client ID", key="cfg_client_id_input", placeholder="es. chicco_2023")
        st.text_input("Dominio atteso", key="cfg_expected_domain", placeholder="es. chicco.it")
        st.text_input("Country default", key="cfg_default_country", placeholder="es. it")
        st.text_input(
            "Base URL app (per link cliente)",
            key="cfg_base_url",
            placeholder="es. https://utm-builder.streamlit.app/ oppure http://localhost:8503",
        )

        st.markdown("#### 4) Salva e genera link cliente")
        if st.button("Salva configurazione cliente", key="save_client_config_btn", type="primary"):
            cid = normalize_client_id(st.session_state.get("cfg_client_id_input", ""))
            if not cid:
                st.error("Inserisci un Client ID valido.")
            elif st.session_state.get("cfg_manage_mode") == "Nuova configurazione aggiuntiva" and cid in existing_client_ids:
                st.error("Questo Client ID esiste già. Per aggiornare usa 'Modifica configurazione' oppure inserisci un nuovo Client ID.")
            else:
                existing_cfg = load_client_config(cid) or {}
                base_url = str(st.session_state.get("cfg_base_url", "")).strip() or "https://utm-builder.streamlit.app/"
                if not base_url.startswith(("http://", "https://")):
                    base_url = f"https://{base_url}"
                base_url = base_url.rstrip("/")

                shared_link = str(existing_cfg.get("shared_link", "")).strip()
                if CLIENT_LINK_SECRET:
                    sig = sign_client_id(cid)
                    shared_link = f"{base_url}/?client_id={cid}&sig={sig}"

                payload = dict(existing_cfg)
                payload.update(
                    {
                        "client_id": cid,
                        "version": int(existing_cfg.get("version", 0) or 0) + 1,
                        "created_at": str(existing_cfg.get("created_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                        "updated_by": st.session_state.get("user_email", ""),
                        "source_file_name": str(st.session_state.get("cfg_rules_file_name", "")).strip(),
                        "source_file_sha256": str(st.session_state.get("cfg_rules_file_sha256", "")).strip(),
                        "ga4_client_name": str(st.session_state.get("cfg_ga4_client_name", "")).strip(),
                        "ga4_property_name": str(st.session_state.get("cfg_ga4_property_name", "")).strip(),
                        "ga4_property_id": str(st.session_state.get("cfg_ga4_property_id", "")).strip(),
                        "property_config": {
                            "default_country": normalize_token(st.session_state.get("cfg_default_country", "")) or "it",
                            "expected_domain": str(st.session_state.get("cfg_expected_domain", "")).strip().lower(),
                        },
                        "rules_rows": list(st.session_state.get("cfg_rules_rows", []) or existing_cfg.get("rules_rows", []) or []),
                        "shared_link": shared_link,
                        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    }
                )

                saved_path = save_client_config(cid, payload)
                st.success(f"Configurazione salvata: {saved_path.name}")
                if CLIENT_LINK_SECRET:
                    st.code(shared_link, language="text")
                else:
                    st.warning("CLIENT_LINK_SECRET non configurato: link firmato non generato.")

    # ==============================================================================
    # TAB 4: UTM HISTORY & TRACKING
    # ==============================================================================
    with tab_history:
        st.markdown("### UTM History & Tracking")
        st.markdown("Storico dei link UTM creati, con verifica del corretto channel grouping in GA4.")

        history_items = load_utm_history()
        prop_lookup = build_property_name_lookup(st.session_state.get("ga4_accounts", []))
        user_email = st.session_state.get("user_email", "")
        if user_email:
            history_items = [x for x in history_items if x.get("user_email") == user_email]
        history_items = sorted(
            history_items,
            key=lambda x: (x.get("live_date", ""), x.get("campaign_name", "")),
            reverse=True
        )

        if not history_items:
            st.info("Nessun link storico disponibile. Genera un link e clicca 'Salva nello storico'.")
        else:
            base_rows = []
            for item in history_items:
                base_rows.append(
                    {
                        "Campagna": item.get("campaign_name", "-"),
                        "Periodo": item.get("live_date", "-"),
                        "UTM (source / medium / campaign)": f"{item.get('utm_source','-')} / {item.get('utm_medium','-')} / {item.get('utm_campaign','-')}",
                        "Canale atteso": item.get("expected_channel_group", "-"),
                        "Stato tracking": "Da verificare",
                    }
                )
            st.dataframe(pd.DataFrame(base_rows), use_container_width=True, hide_index=True)

            selected_campaign = st.selectbox(
                "Seleziona campagna da verificare",
                [f"{x.get('campaign_name','-')} ({x.get('live_date','-')})" for x in history_items],
            )
            selected_index = [f"{x.get('campaign_name','-')} ({x.get('live_date','-')})" for x in history_items].index(selected_campaign)
            selected_item = history_items[selected_index]
            grace_days = st.number_input("Giorni di grace period post-live", min_value=0, max_value=30, value=2, step=1)

            if st.button("Verifica tracking su GA4", key="check_tracking_history_btn", type="primary"):
                result = check_tracking_status_for_entry(selected_item, st.session_state.credentials, grace_days=int(grace_days))
                status_icon = {"OK": "✅", "WARNING": "⚠️", "ERROR": "❌", "PENDING": "⏳"}.get(result["status"], "ℹ️")

                st.markdown(
                    f"""
                    <div class="output-box-ready">
                        <b>{status_icon} Stato tracking: {result['status']}</b><br>
                        <small>{html_lib.escape(result['message'])}</small>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                st.write("Dettaglio verifica:")
                detail_row = {
                    "Campagna": selected_item.get("campaign_name"),
                    "Periodo": selected_item.get("live_date"),
                    "GA4 Property Name": (
                        selected_item.get("property_name")
                        or prop_lookup.get(str(selected_item.get("property_id", "")).replace("properties/", ""))
                        or prop_lookup.get(str(selected_item.get("property_id", "")))
                        or "-"
                    ),
                    "GA4 Property ID": selected_item.get("property_id", "-"),
                    "UTM Source": selected_item.get("utm_source"),
                    "UTM Medium": selected_item.get("utm_medium"),
                    "UTM Campaign": selected_item.get("utm_campaign"),
                    "Sessions osservate": result.get("sessions", 0),
                    "Canale atteso": selected_item.get("expected_channel_group", "-"),
                    "Canale osservato": result.get("observed", "-"),
                    "Stato tracking": result.get("status"),
                }
                st.table(pd.DataFrame([detail_row]))

    # --- RENDER GLOBALLY (FLOATING) ---
    render_chatbot_interface(
        st.session_state.credentials,
        get_persistent_api_key,
        save_chatbot_url_to_history,
        client_rules_text=st.session_state.get("active_client_rules_text", ""),
        preferred_property_id=st.session_state.get("builder_selected_property_id", ""),
        preferred_property_name=st.session_state.get("builder_selected_property_name", ""),
    )


# --- MAIN APP FLOW ---
if __name__ == "__main__":
    if "credentials" not in st.session_state:
        st.session_state.credentials = None
    if "client_id_lock" not in st.session_state:
        st.session_state.client_id_lock = ""
    if "client_lock_error" not in st.session_state:
        st.session_state.client_lock_error = ""
    if "builder_selected_client_id" not in st.session_state:
        st.session_state.builder_selected_client_id = ""

    # Scopes setup for profile info
    if 'https://www.googleapis.com/auth/userinfo.profile' not in SCOPES:
        SCOPES.append('https://www.googleapis.com/auth/userinfo.profile')
    if 'https://www.googleapis.com/auth/userinfo.email' not in SCOPES:
        SCOPES.append('https://www.googleapis.com/auth/userinfo.email')

    # Lock cliente da query params firmati (persistente in sessione).
    raw_open_chat = str(st.query_params.get("open_chat", "")).strip().lower()
    if raw_open_chat in {"1", "true", "yes"}:
        st.session_state.chat_visible = True
        try:
            del st.query_params["open_chat"]
        except Exception:
            pass

    raw_client_qp = normalize_client_id(st.query_params.get("client_id", ""))
    if raw_client_qp:
        locked_client_id, lock_error = get_client_lock_from_query_params()
        if locked_client_id:
            st.session_state.client_id_lock = locked_client_id
            st.session_state.client_lock_error = ""
        elif lock_error:
            st.session_state.client_lock_error = lock_error
            st.session_state.client_id_lock = ""

    # Auto-login check
    base_path = os.path.dirname(os.path.abspath(__file__))
    token_path = os.path.join(base_path, 'token.json')
    
    if st.session_state.credentials is None and os.path.exists(token_path):
         try:
             creds = Credentials.from_authorized_user_file(token_path, SCOPES)
             if creds and creds.valid:
                  st.session_state.credentials = creds
             elif creds and creds.expired and creds.refresh_token:
                  creds.refresh(Request())
                  st.session_state.credentials = creds
         except:
             pass

    # Fallback to web auth if token.json is not present (or we are in Cloud)
    if not st.session_state.credentials:
        query_params = st.query_params
        if "code" in query_params:
            auth_code = query_params["code"]
            auth_state = query_params.get("state")
            
            flow = get_oauth_flow()
            if flow:
                try:
                    # Recupera il code_verifier dalla cache server-side usando lo state token
                    if auth_state:
                        cache = get_oauth_cache()
                        if auth_state in cache:
                            flow.code_verifier = cache[auth_state]
                            
                    flow.fetch_token(code=auth_code)
                    creds = flow.credentials
                    st.session_state.credentials = creds
                    
                    # Store as primitive dict to be completely safe with st.session_state
                    st.session_state.google_credentials = {
                        'token': creds.token,
                        'refresh_token': creds.refresh_token,
                        'token_uri': creds.token_uri,
                        'client_id': creds.client_id,
                        'client_secret': creds.client_secret,
                        'scopes': creds.scopes
                    }
                    
                    # Clean up URL params so we don't re-trigger the auth flow
                    st.query_params.clear()
                    st.rerun()
                except Exception as e:
                    st.error(f"Errore durante l'autenticazione: {e}")
            else:
                st.error("Configurazione Flow mancante durante la validazione del codice.")

    # Restoring from session state primitive dict if page reloads
    if not st.session_state.credentials and "google_credentials" in st.session_state:
        g_creds = st.session_state.google_credentials
        st.session_state.credentials = Credentials(
            token=g_creds.get('token'),
            refresh_token=g_creds.get('refresh_token'),
            token_uri=g_creds.get('token_uri'),
            client_id=g_creds.get('client_id'),
            client_secret=g_creds.get('client_secret'),
            scopes=g_creds.get('scopes')
        )

    # Routing
    if st.session_state.credentials:
        show_dashboard()
    else:
        if st.session_state.get("client_lock_error"):
            st.warning(st.session_state.get("client_lock_error"))
        show_login_page()



