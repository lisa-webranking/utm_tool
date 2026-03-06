import os
import json

def get_user_email(creds):
    """Estrae l'email dall'utente autenticato"""
    try:
        from googleapiclient.discovery import build
        service = build('oauth2', 'v2', credentials=creds)
        user_info = service.userinfo().get().execute()
        return user_info.get('email')
    except Exception as e:
        return None

def get_persistent_api_key(email):
    """Recupera la chiave API salvata per l'utente dalla session_state"""
    if not email: return None
    import streamlit as st
    if 'user_gemini_api_keys' in st.session_state:
        return st.session_state.user_gemini_api_keys.get(email)
    return None

def save_persistent_api_key(email, key):
    """Salva la chiave API per l'utente nella session_state"""
    if not email or not key: return
    import streamlit as st
    if 'user_gemini_api_keys' not in st.session_state:
        st.session_state.user_gemini_api_keys = {}
    st.session_state.user_gemini_api_keys[email] = key
