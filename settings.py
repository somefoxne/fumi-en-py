"""
Centralized Configuration.

Loads environment variables from .env and provides active configuration
for both Production and Testbooru environments.
"""

import os
import re as _re
from dotenv import load_dotenv

load_dotenv()

# ── Version ────────────────────────────────────────────────────────────────────
PROGRAM_VERSION = "2.0.0"

# ── Standard User-Agent according to Danbooru API guidelines ───────────────────
# Format: "BotName/version (by user #id)"
BOORU_USER_ID = os.getenv("BOORU_USER_ID", "")
_uid = f" (by user #{BOORU_USER_ID})" if BOORU_USER_ID else ""
USERAGENT = os.getenv(
    "BOORU_USER_AGENT",
    f"fumi-en-py/{PROGRAM_VERSION}{_uid}"
)

# ── Danbooru Production ────────────────────────────────────────────────────────
BOORU_URL   = os.getenv("BOORU_URL",   "https://danbooru.donmai.us")
LOGIN       = os.getenv("BOORU_USER",  "")
APIKEY      = os.getenv("BOORU_API_KEY", "")

# ── Danbooru Testbooru ─────────────────────────────────────────────────────────
TEST_URL    = os.getenv("TEST_BOORU_URL",     "https://testbooru.donmai.us")
TEST_LOGIN  = os.getenv("TEST_BOORU_USER",    "")
TEST_APIKEY = os.getenv("TEST_BOORU_API_KEY", "")

# ── Discord ────────────────────────────────────────────────────────────────────
DISCORD_TOKEN     = os.getenv("DISCORD_TOKEN", "")
DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID", "")
DISCORD_REPORT_CHANNEL_ID = os.getenv("DISCORD_REPORT_CHANNEL_ID", "")

# ── Bot behavior ───────────────────────────────────────────────────────────────
TEST_MODE = os.getenv("TEST_MODE", "false").lower() in ("true", "1", "yes")

# Domains parsed for auto-embed links
_raw_domains  = os.getenv("BOORU_DOMAINS", "")
_default_domain = _re.sub(r"https?://", "", BOORU_URL)
BOORU_DOMAINS = _raw_domains.split() if _raw_domains else [_default_domain]

# ── Mode resolution ───────────────────────────────────────────────────────────
def get_active_booru_url() -> str:
    return TEST_URL if TEST_MODE else BOORU_URL

def get_active_login() -> str:
    return TEST_LOGIN if TEST_MODE else LOGIN

def get_active_apikey() -> str:
    return TEST_APIKEY if TEST_MODE else APIKEY

# ── Optional overrides from usersettings.py ───────────────────────────────────
try:
    from usersettings import *  # type: ignore # noqa: F401, F403
except ImportError:
    pass
