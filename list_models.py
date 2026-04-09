"""
Script per verificare i modelli Gemini disponibili.
Esegui questo script per vedere quali modelli puoi usare con la chiave condivisa.
"""
import google.generativeai as genai
import sys

from googleapi import get_shared_gemini_api_key

def list_available_models(api_key):
    """Lista tutti i modelli Gemini disponibili"""
    try:
        genai.configure(api_key=api_key)

        print("Modelli Gemini disponibili:\n")
        print("-" * 80)

        for model in genai.list_models():
            if 'generateContent' in model.supported_generation_methods:
                print(model.name)
                print(f"   Display Name: {model.display_name}")
                print(f"   Description: {model.description}")
                print(f"   Methods: {', '.join(model.supported_generation_methods)}")
                print("-" * 80)

    except Exception as e:
        print(f"Errore: {e}")
        return False

    return True

if __name__ == "__main__":
    print("=" * 80)
    print("VERIFICA MODELLI GEMINI DISPONIBILI")
    print("=" * 80)
    print()

    api_key = get_shared_gemini_api_key()

    if not api_key:
        print("Chiave Gemini non configurata. Imposta GEMINI_API_KEY prima di eseguire lo script.")
        sys.exit(1)

    print()
    list_available_models(api_key)
