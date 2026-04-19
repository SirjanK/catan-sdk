"""
Tests for catan.register — token cache functions.

These tests are pure unit tests that do not make any network calls.
They exercise _load_tokens, _save_tokens, load_token, and save_token
using a patched TOKEN_FILE path so they do not touch ~/.catan.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

import catan.register as reg


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _patch_token_file(tmp_path: Path):
    """Return a context manager that redirects TOKEN_FILE to a temp path."""
    fake_dir = tmp_path / "catan"
    fake_file = fake_dir / "tokens.json"
    return (
        patch.object(reg, "TOKEN_DIR", fake_dir),
        patch.object(reg, "TOKEN_FILE", fake_file),
    )


# ---------------------------------------------------------------------------
# _load_tokens
# ---------------------------------------------------------------------------


class TestLoadTokens:
    def test_returns_empty_when_file_absent(self, tmp_path, monkeypatch):
        monkeypatch.setattr(reg, "TOKEN_FILE", tmp_path / "notexist.json")
        assert reg._load_tokens() == {}

    def test_returns_parsed_json(self, tmp_path, monkeypatch):
        f = tmp_path / "tokens.json"
        f.write_text(json.dumps({"https://example.com": {"token": "abc"}}))
        monkeypatch.setattr(reg, "TOKEN_FILE", f)
        result = reg._load_tokens()
        assert result == {"https://example.com": {"token": "abc"}}

    def test_returns_empty_on_corrupted_file(self, tmp_path, monkeypatch, capsys):
        f = tmp_path / "tokens.json"
        f.write_text("not valid json {{{{")
        monkeypatch.setattr(reg, "TOKEN_FILE", f)
        result = reg._load_tokens()
        assert result == {}
        # Should have printed a warning to stderr
        captured = capsys.readouterr()
        assert "corrupted" in captured.err.lower() or "warning" in captured.err.lower()

    def test_returns_empty_on_empty_file(self, tmp_path, monkeypatch):
        f = tmp_path / "tokens.json"
        f.write_text("")
        monkeypatch.setattr(reg, "TOKEN_FILE", f)
        result = reg._load_tokens()
        assert result == {}


# ---------------------------------------------------------------------------
# _save_tokens
# ---------------------------------------------------------------------------


class TestSaveTokens:
    def test_creates_directory(self, tmp_path, monkeypatch):
        token_dir = tmp_path / "deep" / "nested" / "catan"
        token_file = token_dir / "tokens.json"
        monkeypatch.setattr(reg, "TOKEN_DIR", token_dir)
        monkeypatch.setattr(reg, "TOKEN_FILE", token_file)
        reg._save_tokens({"url": "data"})
        assert token_file.exists()

    def test_writes_valid_json(self, tmp_path, monkeypatch):
        token_dir = tmp_path / "catan"
        token_file = token_dir / "tokens.json"
        monkeypatch.setattr(reg, "TOKEN_DIR", token_dir)
        monkeypatch.setattr(reg, "TOKEN_FILE", token_file)
        data = {"https://example.com": {"token": "xyz", "username": "alice"}}
        reg._save_tokens(data)
        assert json.loads(token_file.read_text()) == data

    def test_roundtrip(self, tmp_path, monkeypatch):
        token_dir = tmp_path / "catan"
        token_file = token_dir / "tokens.json"
        monkeypatch.setattr(reg, "TOKEN_DIR", token_dir)
        monkeypatch.setattr(reg, "TOKEN_FILE", token_file)
        original = {"https://a.com": {"token": "tok", "username": "u"}}
        reg._save_tokens(original)
        assert reg._load_tokens() == original


# ---------------------------------------------------------------------------
# load_token / save_token
# ---------------------------------------------------------------------------


class TestLoadToken:
    def _future_iso(self, hours: int = 24) -> str:
        return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()

    def _past_iso(self, hours: int = 1) -> str:
        return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()

    def test_returns_none_when_no_entry(self, tmp_path, monkeypatch):
        f = tmp_path / "tokens.json"
        f.write_text("{}")
        monkeypatch.setattr(reg, "TOKEN_FILE", f)
        assert reg.load_token("https://example.com") is None

    def test_returns_valid_token(self, tmp_path, monkeypatch):
        url = "https://example.com"
        f = tmp_path / "tokens.json"
        f.write_text(json.dumps({
            url: {"token": "mytoken", "username": "alice", "expires_at": self._future_iso()}
        }))
        monkeypatch.setattr(reg, "TOKEN_FILE", f)
        assert reg.load_token(url) == "mytoken"

    def test_returns_none_for_expired_token(self, tmp_path, monkeypatch):
        url = "https://example.com"
        f = tmp_path / "tokens.json"
        f.write_text(json.dumps({
            url: {"token": "expired", "username": "alice", "expires_at": self._past_iso()}
        }))
        monkeypatch.setattr(reg, "TOKEN_FILE", f)
        assert reg.load_token(url) is None

    def test_strips_trailing_slash_from_url(self, tmp_path, monkeypatch):
        url = "https://example.com"
        f = tmp_path / "tokens.json"
        f.write_text(json.dumps({
            url: {"token": "mytoken", "expires_at": self._future_iso()}
        }))
        monkeypatch.setattr(reg, "TOKEN_FILE", f)
        assert reg.load_token("https://example.com/") == "mytoken"

    def test_returns_none_for_malformed_expires_at(self, tmp_path, monkeypatch):
        url = "https://example.com"
        f = tmp_path / "tokens.json"
        f.write_text(json.dumps({
            url: {"token": "tok", "expires_at": "not-a-date"}
        }))
        monkeypatch.setattr(reg, "TOKEN_FILE", f)
        assert reg.load_token(url) is None

    def test_returns_none_when_file_absent(self, tmp_path, monkeypatch):
        monkeypatch.setattr(reg, "TOKEN_FILE", tmp_path / "missing.json")
        assert reg.load_token("https://example.com") is None


class TestSaveToken:
    def test_saves_and_loads(self, tmp_path, monkeypatch):
        token_dir = tmp_path / "catan"
        token_file = token_dir / "tokens.json"
        monkeypatch.setattr(reg, "TOKEN_DIR", token_dir)
        monkeypatch.setattr(reg, "TOKEN_FILE", token_file)

        url = "https://example.com"
        future = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
        reg.save_token(url, "mytoken", "alice", future)
        assert reg.load_token(url) == "mytoken"

    def test_overwrites_existing_entry(self, tmp_path, monkeypatch):
        token_dir = tmp_path / "catan"
        token_file = token_dir / "tokens.json"
        monkeypatch.setattr(reg, "TOKEN_DIR", token_dir)
        monkeypatch.setattr(reg, "TOKEN_FILE", token_file)

        url = "https://example.com"
        future = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
        reg.save_token(url, "old_token", "alice", future)
        reg.save_token(url, "new_token", "alice", future)
        assert reg.load_token(url) == "new_token"

    def test_multiple_urls_coexist(self, tmp_path, monkeypatch):
        token_dir = tmp_path / "catan"
        token_file = token_dir / "tokens.json"
        monkeypatch.setattr(reg, "TOKEN_DIR", token_dir)
        monkeypatch.setattr(reg, "TOKEN_FILE", token_file)

        future = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
        reg.save_token("https://a.com", "token_a", "alice", future)
        reg.save_token("https://b.com", "token_b", "bob", future)
        assert reg.load_token("https://a.com") == "token_a"
        assert reg.load_token("https://b.com") == "token_b"
