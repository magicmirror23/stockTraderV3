"""Tests for providers."""

import pytest
from datetime import datetime, timezone

from app.providers.factory import MockProvider


@pytest.fixture
def mock_provider():
    return MockProvider()


def test_mock_provider_name(mock_provider):
    assert mock_provider.name == "mock"
    assert mock_provider.is_available is True


def test_mock_historical(mock_provider):
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    end = datetime(2024, 3, 1, tzinfo=timezone.utc)
    bars = mock_provider.get_historical("RELIANCE", start, end)
    assert len(bars) > 0
    assert bars[0].symbol == "RELIANCE"
    assert bars[0].open > 0


def test_mock_ltp(mock_provider):
    ticks = mock_provider.get_ltp(["RELIANCE", "TCS"])
    assert len(ticks) == 2
    assert "RELIANCE" in ticks
    assert ticks["RELIANCE"].price > 0


def test_mock_option_chain(mock_provider):
    chain = mock_provider.get_option_chain("RELIANCE")
    assert chain is None  # Mock returns None
