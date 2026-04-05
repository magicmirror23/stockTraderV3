# Downloader resilience tests
"""Tests for rate-limit friendly batch refresh behavior."""

from __future__ import annotations

from backend.services import data_downloader as dl


def test_refresh_all_symbols_stops_after_consecutive_failures(monkeypatch, tmp_path):
    calls: list[str] = []

    def _always_fail(symbol, data_dir):
        calls.append(symbol)
        return False

    monkeypatch.setattr(dl, "download_symbol", _always_fail)
    monkeypatch.setenv("DATA_REFRESH_MAX_CONSEC_FAILS", "2")
    monkeypatch.setenv("DATA_REFRESH_REQUEST_PAUSE_S", "0")
    monkeypatch.setenv("DATA_REFRESH_FAIL_PAUSE_S", "0")

    symbols = ["A", "B", "C", "D"]
    results = dl.refresh_all_symbols(symbols, data_dir=tmp_path, force=True)

    # Only two real download attempts should occur, then the batch short-circuits.
    assert calls == ["A", "B"]
    assert results == {"A": False, "B": False, "C": False, "D": False}


def test_refresh_all_symbols_resets_failure_streak_on_success(monkeypatch, tmp_path):
    seq = iter([False, True, False, False])
    calls: list[str] = []

    def _mixed(symbol, data_dir):
        calls.append(symbol)
        return next(seq)

    monkeypatch.setattr(dl, "download_symbol", _mixed)
    monkeypatch.setenv("DATA_REFRESH_MAX_CONSEC_FAILS", "2")
    monkeypatch.setenv("DATA_REFRESH_REQUEST_PAUSE_S", "0")
    monkeypatch.setenv("DATA_REFRESH_FAIL_PAUSE_S", "0")

    symbols = ["A", "B", "C", "D"]
    results = dl.refresh_all_symbols(symbols, data_dir=tmp_path, force=True)

    # Success on B resets the streak, so all symbols get attempted.
    assert calls == symbols
    assert results == {"A": False, "B": True, "C": False, "D": False}
