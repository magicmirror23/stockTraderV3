"""AngelOne credential/account verification helpers.

Shared by market-data and trading routers so frontend gets a consistent
credential status regardless of which microservice handles the request.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


_ANGEL_KEY_ALIASES: dict[str, tuple[str, ...]] = {
    "ANGEL_API_KEY": (
        "ANGEL_API_KEY",
        "SMARTAPI_API_KEY",
        "ANGELONE_API_KEY",
        "ANGEL_ONE_API_KEY",
        "SMARTAPI_KEY",
        "ANGEL_APIKEY",
    ),
    "ANGEL_CLIENT_ID": (
        "ANGEL_CLIENT_ID",
        "SMARTAPI_CLIENT_ID",
        "ANGEL_CLIENT_CODE",
        "ANGEL_CLIENTID",
        "ANGEL_USER_ID",
        "ANGEL_USERID",
    ),
    "ANGEL_MPIN": (
        "ANGEL_MPIN",
        "ANGEL_CLIENT_PIN",
        "SMARTAPI_MPIN",
        "ANGEL_PIN",
    ),
    "ANGEL_TOTP_SECRET": (
        "ANGEL_TOTP_SECRET",
        "SMARTAPI_TOTP_SECRET",
        "ANGEL_TOTP",
        "ANGEL_TOTP_KEY",
        "ANGEL_OTP_SECRET",
    ),
}


def _env_first_non_empty(*keys: str) -> tuple[str, str | None]:
    for key in keys:
        value = os.getenv(key, "")
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text, key
    return "", None


def _resolve_angel_env() -> tuple[dict[str, str], dict[str, bool], dict[str, str], list[str]]:
    resolved_values: dict[str, str] = {}
    resolved_flags: dict[str, bool] = {}
    resolved_sources: dict[str, str] = {}
    missing: list[str] = []

    for canonical_key, aliases in _ANGEL_KEY_ALIASES.items():
        value, source = _env_first_non_empty(*aliases)
        resolved_values[canonical_key] = value
        resolved_flags[canonical_key] = bool(value)
        if source:
            resolved_sources[canonical_key] = source
        else:
            missing.append(canonical_key)

    return resolved_values, resolved_flags, resolved_sources, missing


def _common_payload(
    *,
    status: str,
    message: str,
    creds: dict[str, bool],
    sources: dict[str, str],
    missing: list[str],
) -> dict[str, Any]:
    return {
        "status": status,
        "message": message,
        "paper_mode": os.getenv("PAPER_MODE", "true").strip().lower() == "true",
        "service": os.getenv("SERVICE_NAME", "trading"),
        "credentials_set": creds,
        "credentials_source": sources,
        "missing_credentials": missing,
    }


def get_angel_profile_sync(force_live: bool = False) -> dict[str, Any]:
    """Verify AngelOne credential presence and optionally fetch account profile.

    Parameters
    ----------
    force_live:
        When True, bypasses paper-mode shortcut and attempts broker login.
    """
    values, creds, sources, missing = _resolve_angel_env()
    api_key = values["ANGEL_API_KEY"]
    client_id = values["ANGEL_CLIENT_ID"]
    mpin = values["ANGEL_MPIN"]
    totp_secret = values["ANGEL_TOTP_SECRET"]

    paper_mode = os.getenv("PAPER_MODE", "true").strip().lower() == "true"
    if paper_mode and not force_live:
        paper_balance = float(os.getenv("PAPER_BALANCE", "100000"))
        if all(creds.values()):
            msg = (
                "Running in paper mode. AngelOne credentials are present. "
                "Use mode=live to verify broker session."
            )
        else:
            msg = (
                "Running in paper mode. Live broker credentials are optional in paper mode. "
                "Set PAPER_MODE=false and configure Angel env vars to verify live session."
            )
        response = _common_payload(
            status="paper_mode",
            message=msg,
            creds=creds,
            sources=sources,
            missing=missing,
        )
        response.update(
            {
                "name": "Paper Trader",
                "client_id": client_id or "paper",
                "email": "paper@demo.local",
                "balance": paper_balance,
                "net": paper_balance,
                "available_margin": paper_balance,
                "utilized_margin": 0.0,
            }
        )
        return response

    if not all(creds.values()):
        return _common_payload(
            status="not_configured",
            message=(
                "AngelOne credentials are not set for this service. "
                "Set ANGEL_API_KEY, ANGEL_CLIENT_ID, ANGEL_MPIN, ANGEL_TOTP_SECRET."
            ),
            creds=creds,
            sources=sources,
            missing=missing,
        )

    try:
        from SmartApi import SmartConnect
        import pyotp

        totp = pyotp.TOTP(totp_secret).now()
        api = SmartConnect(api_key=api_key)
        session = api.generateSession(client_id, mpin, totp)

        if not session or session.get("status") is False:
            payload = _common_payload(
                status="login_failed",
                message=f"AngelOne login failed: {session.get('message', 'Unknown error')}",
                creds=creds,
                sources=sources,
                missing=missing,
            )
            return payload

        profile = api.getProfile(session["data"]["refreshToken"])
        rms = api.rmsLimit()

        profile_data = profile.get("data", {}) if profile else {}
        rms_data = rms.get("data", {}) if rms else {}

        payload = _common_payload(
            status="connected",
            message="Credentials verified and connected to AngelOne.",
            creds=creds,
            sources=sources,
            missing=missing,
        )
        payload.update(
            {
                "name": profile_data.get("name", "N/A"),
                "client_id": profile_data.get("clientcode", client_id),
                "email": profile_data.get("email", ""),
                "phone": profile_data.get("mobileno", ""),
                "broker": profile_data.get("broker", "ANGEL"),
                "balance": float(rms_data.get("availablecash", 0)),
                "net": float(rms_data.get("net", 0)),
                "available_margin": float(rms_data.get("availableintradaypayin", 0)),
                "utilized_margin": float(rms_data.get("utiliseddebits", 0)),
            }
        )
        return payload
    except ImportError:
        return _common_payload(
            status="missing_package",
            message="Install smartapi-python and pyotp in this service image.",
            creds=creds,
            sources=sources,
            missing=missing,
        )
    except Exception:
        logger.exception("Account verification failed")
        return _common_payload(
            status="error",
            message="Internal server error while verifying broker credentials.",
            creds=creds,
            sources=sources,
            missing=missing,
        )
