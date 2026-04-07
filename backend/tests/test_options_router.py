from __future__ import annotations


def test_options_recommend_returns_frontend_compatible_shape(client):
    payload = {
        "underlying": "RELIANCE",
        "spot": 2500,
        "expiry": "2026-04-30",
        "direction": "bullish",
        "confidence": 0.8,
        "iv": 0.2,
        "iv_percentile": 45,
        "lot_size": 25,
    }

    res = client.post("/api/v1/options/recommend", json=payload)
    assert res.status_code == 200
    body = res.json()

    assert isinstance(body.get("strategy_type"), str)
    assert isinstance(body.get("rationale"), str)
    assert isinstance(body.get("breakeven"), list)
    assert isinstance(body.get("legs"), list)
    assert body["legs"], "recommendation should include at least one leg"

    leg = body["legs"][0]
    assert isinstance(leg.get("instrument"), str) and leg["instrument"]
    assert leg.get("option_type") in {"CE", "PE"}
    assert "strike" in leg
    assert "premium" in leg


def test_options_payoff_accepts_frontend_legs_and_returns_payoff_alias(client):
    legs = [
        {
            "instrument": "RELIANCE-2026-04-30-2500-CE",
            "option_type": "CE",
            "strike": 2500,
            "expiry": "2026-04-30",
            "side": "buy",
            "quantity": 25,
            "premium": 40,
        }
    ]

    res = client.post("/api/v1/options/payoff", json={"legs": legs, "points": 10})
    assert res.status_code == 200
    body = res.json()
    assert isinstance(body, list)
    assert body
    point = body[0]
    assert "spot" in point
    assert "pnl" in point
    assert "payoff" in point
    assert float(point["pnl"]) == float(point["payoff"])
