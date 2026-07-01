"""
setup_gdrive_oauth.py
---------------------
Google Drive OAuth 2.0 setup.

Usage:
  1. Run: uv run python scripts/setup_gdrive_oauth.py
  2. Open the URL in your browser and authorize
  3. Copy the code Google shows you
  4. Run: uv run python scripts/setup_gdrive_oauth.py <PASTE_CODE_HERE>
"""

import os
import sys
import json
import webbrowser
from urllib.parse import urlencode
from pathlib import Path

import requests

SCOPES = ["https://www.googleapis.com/auth/drive"]
REDIRECT_URI = "urn:ietf:wg:oauth:2.0:oob"


def main():
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        from dotenv import load_dotenv
        load_dotenv(env_path)

    client_id = os.getenv("GDRIVE_CLIENT_ID", "").strip()
    client_secret = os.getenv("GDRIVE_CLIENT_SECRET", "").strip()
    token_path = os.getenv("GDRIVE_TOKEN_PATH", "gdrive_token.json")

    if not client_id or not client_secret:
        print("ERROR: GDRIVE_CLIENT_ID and GDRIVE_CLIENT_SECRET must be set in .env")
        sys.exit(1)

    # If code passed as argument, exchange it
    if len(sys.argv) > 1:
        code = sys.argv[1]
        print("Exchanging code for tokens...")
        resp = requests.post("https://oauth2.googleapis.com/token", data={
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": REDIRECT_URI,
            "grant_type": "authorization_code",
        })
        if resp.status_code != 200:
            print(f"Error: {resp.status_code} - {resp.text}")
            sys.exit(1)

        raw = resp.json()
        token = {
            "token": raw["access_token"],
            "refresh_token": raw.get("refresh_token"),
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_id": client_id,
            "client_secret": client_secret,
            "scopes": SCOPES,
            "expiry": None,
        }
        with open(token_path, "w", encoding="utf-8") as f:
            json.dump(token, f, indent=2)

        print(f"\n✅ Token saved to: {os.path.abspath(token_path)}")
        return

    # Print auth URL
    LOGIN_HINT = "prodevsolution7708@gmail.com"

    params = {
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "select_account consent",
    }
    auth_url = "https://accounts.google.com/o/oauth2/auth?" + urlencode(params)

    print("\n" + "=" * 60)
    print("PASO 1: Abre esta URL en tu navegador:")
    print("=" * 60)
    print(auth_url)
    print()
    try:
        webbrowser.open(auth_url)
    except Exception:
        pass
    print()
    print("PASO 2: Inicia sesion con tu cuenta de Google")
    print("PASO 3: Haz clic en 'Continue' (aunque diga 'unverified')")
    print("PASO 4: Copia el codigo que Google te muestra")
    print()
    print("PASO 5: Ejecuta:")
    print(f'  uv run python scripts/setup_gdrive_oauth.py "<CODIGO>"')
    print()
    print("O simplemente pega el codigo aqui y te lo configuro.")


if __name__ == "__main__":
    main()
