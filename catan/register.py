"""
catan.register — CLI to upload a bot zip to the tournament server.

Two authentication modes:

  API token (recommended for CI/automation)::

    python -m catan.register \\
      --url https://tournament.example.com \\
      --token ctn_abc123...  \\
      --zip MyBot.zip

    Generate a token at the tournament site: Settings → API Tokens.
    Tokens do not expire and can be revoked at any time.

  Username/password (interactive sessions)::

    python -m catan.register \\
      --url https://tournament.example.com \\
      --username player1 \\
      --zip MyBot.zip

    Prompts for your password once, caches the 24-hour JWT so subsequent
    calls within the same day don't prompt again.

  JWT cache: ~/.catan/tokens.json

Package your bot first::

    python -m catan.submit submissions.my_bot:MyBot   # → MyBot.zip
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

TOKEN_DIR = Path.home() / ".catan"
TOKEN_FILE = TOKEN_DIR / "tokens.json"

# ---------------------------------------------------------------------------
# JWT session-token cache  (username/password flow only)
# ---------------------------------------------------------------------------


def _load_tokens() -> dict:
    if TOKEN_FILE.exists():
        try:
            return json.loads(TOKEN_FILE.read_text())
        except Exception:
            print(
                f"Warning: token cache at {TOKEN_FILE} is corrupted and will be ignored. "
                "Delete it to suppress this warning.",
                file=sys.stderr,
            )
            return {}
    return {}


def _save_tokens(tokens: dict) -> None:
    TOKEN_DIR.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(json.dumps(tokens, indent=2))
    try:
        TOKEN_FILE.chmod(0o600)  # owner-only on Unix-like systems
    except Exception:
        pass


def _cache_key(url: str, username: str) -> str:
    return f"{url.rstrip('/')}@{username}"


def load_token(url: str, username: str) -> Optional[str]:
    """Return a cached, non-expired JWT for *url* + *username*, or None."""
    tokens = _load_tokens()
    entry = tokens.get(_cache_key(url, username))
    if entry is None:
        return None
    expires_at = entry.get("expires_at")
    if expires_at:
        try:
            exp = datetime.fromisoformat(expires_at)
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) >= exp:
                return None
        except Exception:
            return None
    return entry.get("token")


def save_token(url: str, token: str, username: str, expires_at: str) -> None:
    tokens = _load_tokens()
    tokens[_cache_key(url, username)] = {
        "token": token,
        "username": username,
        "expires_at": expires_at,
    }
    _save_tokens(tokens)


# ---------------------------------------------------------------------------
# HTTP helpers (requires httpx)
# ---------------------------------------------------------------------------


def _httpx():
    """Lazily import httpx with a friendly error if missing."""
    try:
        import httpx
        return httpx
    except ImportError:
        print(
            "Error: 'httpx' is required for catan.register.\n"
            "Install it with: pip install httpx",
            file=sys.stderr,
        )
        sys.exit(1)


def login(url: str, username: str) -> str:
    """Prompt for password, POST /auth/login, cache and return the JWT."""
    httpx = _httpx()
    password = getpass.getpass(f"Password for {username}@{url.rstrip('/')}: ")
    base = url.rstrip("/")
    try:
        resp = httpx.post(
            f"{base}/auth/login",
            json={"username": username, "password": password},
            timeout=15,
        )
    except httpx.RequestError as e:
        print(f"Error: Could not connect to {base}: {e}", file=sys.stderr)
        sys.exit(1)

    if resp.status_code == 401:
        print("Error: Invalid username or password.", file=sys.stderr)
        sys.exit(1)
    if not resp.is_success:
        print(f"Error: Login failed (HTTP {resp.status_code}): {resp.text}", file=sys.stderr)
        sys.exit(1)

    data = resp.json()
    token = data.get("access_token")
    if not token:
        print("Error: Server did not return an access_token.", file=sys.stderr)
        sys.exit(1)

    # Tokens expire in 24 h — store that as an absolute timestamp
    from datetime import timedelta
    expires_at = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
    save_token(base, token, username, expires_at)
    return token


def upload_bot(url: str, token: str, zip_path: str, name: str) -> dict:
    """POST /bots with the zip file; return the created bot metadata."""
    httpx = _httpx()
    base = url.rstrip("/")
    if not os.path.exists(zip_path):
        print(f"Error: Zip file not found: {zip_path}", file=sys.stderr)
        sys.exit(1)

    with open(zip_path, "rb") as f:
        zip_bytes = f.read()

    zip_filename = os.path.basename(zip_path)
    try:
        resp = httpx.post(
            f"{base}/bots",
            params={"name": name},
            files={"file": (zip_filename, zip_bytes, "application/zip")},
            headers={"Authorization": f"Bearer {token}"},
            timeout=60,
        )
    except httpx.RequestError as e:
        print(f"Error: Could not connect to {base}: {e}", file=sys.stderr)
        sys.exit(1)

    if resp.status_code == 401:
        print(
            "Error: Authentication failed. "
            "Check that your token is valid and has not been revoked.",
            file=sys.stderr,
        )
        sys.exit(1)
    if not resp.is_success:
        try:
            detail = resp.json().get("detail", resp.text)
        except Exception:
            detail = resp.text
        print(f"Error: Upload failed (HTTP {resp.status_code}): {detail}", file=sys.stderr)
        sys.exit(1)

    return resp.json()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m catan.register",
        description="Upload a bot zip to the tournament server.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--url", required=True,
        help="Base URL of the tournament server (e.g. https://tournament.example.com).",
    )
    parser.add_argument(
        "--zip", required=True, dest="zip_path",
        help="Path to the bot zip produced by 'python -m catan.submit'.",
    )
    parser.add_argument(
        "--name", default=None,
        help="Display name for the bot (default: zip filename stem).",
    )

    # ── Authentication: token OR username (mutually exclusive) ───────────────
    auth_group = parser.add_mutually_exclusive_group()
    auth_group.add_argument(
        "--token",
        default=None,
        help=(
            "Long-lived API token (starts with 'ctn_'). "
            "Generate one at the tournament site under Settings → API Tokens. "
            "Preferred for CI/automation — no password prompt."
        ),
    )
    auth_group.add_argument(
        "--username",
        default=None,
        help=(
            "Your account username. Triggers an interactive password prompt "
            "unless a valid cached JWT is found in ~/.catan/tokens.json."
        ),
    )

    args = parser.parse_args(argv)

    # Validate: at least one auth method must be supplied.
    if args.token is None and args.username is None:
        parser.error("Supply either --token or --username.")

    bot_name = args.name or Path(args.zip_path).stem
    base_url = args.url.rstrip("/")

    # ── Resolve bearer token ─────────────────────────────────────────────────
    if args.token is not None:
        bearer = args.token
        if not bearer.startswith("ctn_"):
            print(
                "Warning: token does not start with 'ctn_' — is this an API token? "
                "For JWT session tokens, use --username instead.",
                file=sys.stderr,
            )
    else:
        # Username/password flow with JWT cache
        bearer = load_token(base_url, args.username)
        if bearer is None:
            print(f"No valid cached token for {base_url}. Logging in...")
            bearer = login(base_url, args.username)
        else:
            print(f"Using cached token for {args.username}@{base_url}")

    # ── Upload ───────────────────────────────────────────────────────────────
    print(f"Uploading {args.zip_path!r} as {bot_name!r}...")
    bot = upload_bot(base_url, bearer, args.zip_path, bot_name)

    bot_id = bot.get("id") or bot.get("uuid") or bot.get("bot_id", "?")
    print(f'Bot registered: "{bot_name}" (id: {bot_id})')


if __name__ == "__main__":
    main()
