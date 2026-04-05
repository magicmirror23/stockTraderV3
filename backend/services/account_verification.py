"""AngelOne credential/account verification helpers.

Shared by market-data and trading routers so frontend gets a consistent
credential status regardless of which microservice handles the request.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


def _env_first_non_empty(*keys: str) -> str:
    for key in keys:
        value = os.getenv(key, "")
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _bool_map(api_key: str, client_id: str, mpin: str, totp_secret: str) -> dict[str, bool]:
    return {
        "ANGEL_API_KEY": bool(api_key),
        "ANGEL_CLIENT_ID": bool(client_id),
        "ANGEL_MPIN": bool(mpin),
        "ANGEL_TOTP_SECRET": bool(totp_secret),
    }


def get_angel_profile_sync() -> dict[str, Any]:
    """Verify AngelOne credential presence and optionally fetch account profile."""
    api_key = _env_first_non_empty("ANGEL_API_KEY", "SMARTAPI_API_KEY", "ANGELONE_API_KEY")
    client_id = _env_first_non_empty("ANGEL_CLIENT_ID", "SMARTAPI_CLIENT_ID", "ANGEL_CLIENT_CODE")
    mpin = _env_first_non_empty("ANGEL_MPIN", "ANGEL_CLIENT_PIN", "SMARTAPI_MPIN")
    totp_secret = _env_first_non_empty("ANGEL_TOTP_SECRET", "SMARTAPI_TOTP_SECRET", "ANGEL_TOTP")

    creds = _bool_map(api_key, client_id, mpin, totp_secret)
    if not all(creds.values()):
        return {
            "status": "not_configured",
            "message": (
                "AngelOne credentials are not set for this service. "
                "Set ANGEL_API_KEY, ANGEL_CLIENT_ID, ANGEL_MPIN, ANGEL_TOTP_SECRET in Render env vars."
            ),
            "credentials_set": creds,
        }

    paper_mode = os.getenv("PAPER_MODE", "true").lower() == "true"
    if paper_mode:
        paper_balance = float(os.getenv("PAPER_BALANCE", "100000"))
        return {
            "status": "paper_mode",
            "message": "Running in Paper Mode. Set PAPER_MODE=false to verify live broker session.",
            "name": "Paper Trader",
            "client_id": client_id,
            "email": "paper@demo.local",
            "balance": paper_balance,
            "net": paper_balance,
            "available_margin": paper_balance,
            "credentials_set": creds,
        }

    try:
        from SmartApi import SmartConnect
        import pyotp

        totp = pyotp.TOTP(totp_secret).now()
        api = SmartConnect(api_key=api_key)
        session = api.generateSession(client_id, mpin, totp)

        if not session or session.get("status") is False:
            return {
                "status": "login_failed",
                "message": f"AngelOne login failed: {session.get('message', 'Unknown error')}",
                "credentials_set": creds,
            }

        profile = api.getProfile(session["data"]["refreshToken"])
        rms = api.rmsLimit()

        profile_data = profile.get("data", {}) if profile else {}
        rms_data = rms.get("data", {}) if rms else {}

        return {
            "status": "connected",
            "message": "Credentials verified - connected to AngelOne",
            "name": profile_data.get("name", "N/A"),
            "client_id": profile_data.get("clientcode", client_id),
            "email": profile_data.get("email", ""),
            "phone": profile_data.get("mobileno", ""),
            "broker": profile_data.get("broker", "ANGEL"),
            "balance": float(rms_data.get("availablecash", 0)),
            "net": float(rms_data.get("net", 0)),
            "available_margin": float(rms_data.get("availableintradaypayin", 0)),
            "utilized_margin": float(rms_data.get("utiliseddebits", 0)),
            "credentials_set": creds,
        }
    except ImportError:
        return {
            "status": "missing_package",
            "message": "Install smartapi-python and pyotp in this service image.",
            "credentials_set": creds,
        }
    except Exception:
        logger.exception("Account verification failed")
        return {
            "status": "error",
            "message": "Internal server error while verifying broker credentials.",
            "credentials_set": creds,
        }
