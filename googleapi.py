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
    """Recupera la chiave API salvata per l'utente"""
    if not email: return None
    keys_path = os.path.join(os.path.dirname(__file__), 'api_keys.json')
    if os.path.exists(keys_path):
        with open(keys_path, 'r') as f:
            try:
                keys = json.load(f)
                return keys.get(email)
            except:
                return None
    return None

def save_persistent_api_key(email, key):
    """Salva la chiave API per l'utente"""
    if not email or not key: return
    keys_path = os.path.join(os.path.dirname(__file__), 'api_keys.json')
    keys = {}
    if os.path.exists(keys_path):
        with open(keys_path, 'r') as f:
            try:
                keys = json.load(f)
            except:
                keys = {}
    keys[email] = key
    with open(keys_path, 'w') as f:
        json.dump(keys, f)
