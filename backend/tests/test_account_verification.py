# Account verification tests
"""Tests for shared AngelOne credential verification flow."""

from backend.services.account_verification import get_angel_profile_sync


def test_account_verification_not_configured(monkeypatch):
    monkeypatch.delenv("ANGEL_API_KEY", raising=False)
    monkeypatch.delenv("ANGEL_CLIENT_ID", raising=False)
    monkeypatch.delenv("ANGEL_MPIN", raising=False)
    monkeypatch.delenv("ANGEL_CLIENT_PIN", raising=False)
    monkeypatch.delenv("ANGEL_TOTP_SECRET", raising=False)
    monkeypatch.setenv("PAPER_MODE", "false")

    res = get_angel_profile_sync()
    assert res["status"] == "not_configured"
    assert res["credentials_set"]["ANGEL_API_KEY"] is False
    assert res["credentials_set"]["ANGEL_CLIENT_ID"] is False
    assert res["credentials_set"]["ANGEL_MPIN"] is False
    assert res["credentials_set"]["ANGEL_TOTP_SECRET"] is False


def test_account_verification_paper_mode_with_aliases(monkeypatch):
    monkeypatch.delenv("ANGEL_API_KEY", raising=False)
    monkeypatch.delenv("ANGEL_CLIENT_ID", raising=False)
    monkeypatch.delenv("ANGEL_MPIN", raising=False)
    monkeypatch.delenv("ANGEL_TOTP_SECRET", raising=False)
    monkeypatch.setenv("SMARTAPI_API_KEY", "demo_api")
    monkeypatch.setenv("SMARTAPI_CLIENT_ID", "demo_client")
    monkeypatch.setenv("ANGEL_CLIENT_PIN", "1234")
    monkeypatch.setenv("SMARTAPI_TOTP_SECRET", "demo_totp")
    monkeypatch.setenv("PAPER_MODE", "true")
    monkeypatch.setenv("PAPER_BALANCE", "250000")

    res = get_angel_profile_sync()
    assert res["status"] == "paper_mode"
    assert res["client_id"] == "demo_client"
    assert res["balance"] == 250000.0
    assert all(res["credentials_set"].values())
