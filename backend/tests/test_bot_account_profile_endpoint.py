# Bot account profile endpoint tests
"""Tests for /api/v1/bot/account/profile endpoint."""


def test_bot_account_profile_endpoint_returns_payload(client, monkeypatch):
    payload = {
        "status": "paper_mode",
        "message": "ok",
        "credentials_set": {
            "ANGEL_API_KEY": True,
            "ANGEL_CLIENT_ID": True,
            "ANGEL_MPIN": True,
            "ANGEL_TOTP_SECRET": True,
        },
    }
    monkeypatch.setattr("backend.api.routers.bot.get_angel_profile_sync", lambda: payload)

    res = client.get("/api/v1/bot/account/profile")
    assert res.status_code == 200
    assert res.json() == payload
