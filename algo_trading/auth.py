"""
auth.py - Zerodha Kite Authentication Module
Zerodha ke saath login karo aur access token manage karo
"""

import os
import json
import logging
import webbrowser
import ssl
import certifi
from datetime import datetime, date
from pathlib import Path

# ── SSL Fix for Windows (certificate verify failed) ──────────
# Python 3.x on Windows mein SSL certs manually set karne padte hain
os.environ["SSL_CERT_FILE"] = certifi.where()
os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()

# requests library ke liye bhi patch karo
import requests
from requests.adapters import HTTPAdapter
_original_send = requests.Session.send

def _patched_send(self, request, **kwargs):
    kwargs.setdefault("verify", certifi.where())
    return _original_send(self, request, **kwargs)

requests.Session.send = _patched_send
# ─────────────────────────────────────────────────────────────

from kiteconnect import KiteConnect
import pytz

from config import (
    KITE_API_KEY, KITE_API_SECRET, KITE_USER_ID,
    KITE_API, IST
)

logger = logging.getLogger(__name__)
IST_tz = pytz.timezone("Asia/Kolkata")


class KiteAuth:
    """
    Zerodha Kite ke saath authentication handle karta hai.
    
    Flow:
    1. Login URL generate karo
    2. Browser mein open karo
    3. Request token milo
    4. Access token generate karo
    5. Token file mein save karo (aaj ke liye valid)
    """

    def __init__(self):
        self.api_key = KITE_API_KEY
        self.api_secret = KITE_API_SECRET
        self.token_file = Path(KITE_API["token_file"])
        self.kite = None

        # Token folder banao agar nahi hai
        self.token_file.parent.mkdir(parents=True, exist_ok=True)

    def get_kite_instance(self) -> KiteConnect:
        """
        Valid KiteConnect instance return karo.
        Pehle saved token try karo, nahi toh fresh login.
        """
        # Pehle saved token check karo
        access_token = self._load_saved_token()

        if access_token:
            logger.info("✅ Saved access token mila - use kar rahe hain")
            self.kite = KiteConnect(api_key=self.api_key)
            self.kite.set_access_token(access_token)

            # Token valid hai? Check karo
            if self._verify_token():
                return self.kite
            else:
                logger.warning("❌ Saved token expire ho gaya, fresh login karo")

        # Fresh login
        return self._fresh_login()

    def _fresh_login(self) -> KiteConnect:
        """Browser se fresh login karo"""
        self.kite = KiteConnect(api_key=self.api_key)

        # Login URL banao
        login_url = self.kite.login_url()
        logger.info(f"🌐 Login URL: {login_url}")
        print("\n" + "="*60)
        print("ZERODHA LOGIN REQUIRED")
        print("="*60)
        print(f"Browser mein yeh URL open ho raha hai:")
        print(f"{login_url}")
        print("\nLogin karne ke baad redirect URL se")
        print("'request_token' copy karke yahan paste karo")
        print("="*60 + "\n")

        # Browser mein open karo
        webbrowser.open(login_url)

        # Request token input lo
        request_token = input("Request Token paste karo: ").strip()

        if not request_token:
            raise ValueError("Request token empty hai!")

        # Access token generate karo
        try:
            session_data = self.kite.generate_session(
                request_token=request_token,
                api_secret=self.api_secret
            )
            access_token = session_data["access_token"]
            self.kite.set_access_token(access_token)

            # Token save karo
            self._save_token(access_token, session_data)

            logger.info(f"✅ Login successful! User: {session_data.get('user_id', '')}")
            print(f"\n✅ Login successful! Welcome {session_data.get('user_name', 'Trader')}!")

            return self.kite

        except Exception as e:
            logger.error(f"❌ Login failed: {e}")
            raise

    def _load_saved_token(self) -> str | None:
        """
        Aaj ka saved access token load karo.
        Kite access token sirf aaj ke din valid hota hai.
        """
        if not self.token_file.exists():
            return None

        try:
            with open(self.token_file, "r") as f:
                data = json.load(f)

            # Check karo - aaj ka token hai?
            saved_date = data.get("date", "")
            today = date.today().isoformat()

            if saved_date != today:
                logger.info("Token purana hai (aaj ka nahi)")
                return None

            # User match karo
            if data.get("user_id") != KITE_USER_ID:
                logger.warning("Token kisi aur user ka hai")
                return None

            return data.get("access_token")

        except Exception as e:
            logger.error(f"Token load error: {e}")
            return None

    def _save_token(self, access_token: str, session_data: dict):
        """Access token file mein save karo"""
        try:
            data = {
                "access_token": access_token,
                "user_id": session_data.get("user_id", KITE_USER_ID),
                "user_name": session_data.get("user_name", ""),
                "date": date.today().isoformat(),
                "timestamp": datetime.now(IST_tz).isoformat(),
            }
            with open(self.token_file, "w") as f:
                json.dump(data, f, indent=2)

            logger.info(f"✅ Token saved: {self.token_file}")

        except Exception as e:
            logger.error(f"Token save error: {e}")

    def _verify_token(self) -> bool:
        """Token valid hai check karo - profile fetch karke"""
        try:
            profile = self.kite.profile()
            logger.info(f"✅ Token verified for: {profile.get('user_name', '')}")
            return True
        except Exception as e:
            logger.warning(f"Token verify failed: {e}")
            return False

    def logout(self):
        """Kite session close karo"""
        try:
            if self.kite:
                self.kite.invalidate_access_token()
                logger.info("✅ Logged out successfully")
        except Exception as e:
            logger.error(f"Logout error: {e}")

    def get_saved_token_info(self) -> dict:
        """Saved token ki info return karo"""
        if not self.token_file.exists():
            return {"status": "No token saved"}

        try:
            with open(self.token_file, "r") as f:
                data = json.load(f)
            today = date.today().isoformat()
            data["is_valid_today"] = (data.get("date") == today)
            return data
        except Exception:
            return {"status": "Error reading token"}


def get_kite() -> KiteConnect:
    """
    Shortcut function - sirf isko call karo aur KiteConnect instance milega
    
    Usage:
        from auth import get_kite
        kite = get_kite()
        profile = kite.profile()
    """
    auth = KiteAuth()
    return auth.get_kite_instance()


if __name__ == "__main__":
    # Test karo
    import sys
    sys.path.insert(0, str(Path(__file__).parent))

    from utils.logger import setup_logger
    setup_logger()

    print("🔐 Kite Authentication Test")
    print("-" * 40)

    auth = KiteAuth()
    info = auth.get_saved_token_info()
    print(f"Saved token info: {info}")

    try:
        kite = auth.get_kite_instance()
        profile = kite.profile()
        print(f"\n✅ Connected!")
        print(f"   User: {profile['user_name']}")
        print(f"   Email: {profile['email']}")
        print(f"   Broker: {profile['broker']}")
    except Exception as e:
        print(f"\n❌ Error: {e}")
