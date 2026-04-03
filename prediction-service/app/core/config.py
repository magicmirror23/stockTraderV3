"""Centralised configuration – re-export for convenience."""

from app.core import Settings, get_settings, settings

__all__ = ["Settings", "get_settings", "settings"]
