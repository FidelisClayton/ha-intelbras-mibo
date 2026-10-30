"""Pinned static application metadata, privately cached through Home Assistant."""

import hashlib
import re
import urllib.error
import urllib.request

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .protocol import LIMIT, MiboError, NoRedirect, safe_text

SOURCE_URL = "https://raw.githubusercontent.com/Saeger/MiboMac/9ef8108e3992b60ff4ef0d9e1d84b8fc6e8e020f/Sources/App/MiboAPI.swift"
SOURCE_SHA256 = "be30e1c992a73a1d35515e084cf418e8e8a82b10a4e9d8228b08b5b5e0c394f4"
APP_FIELDS = ("appId", "defaultAK", "defaultSK", "clientVersion", "project", "protocolVersion")
STORAGE_KEY = "intelbras_mibo.bootstrap"


def download_source():
    """Download only the immutable upstream source with bounded transport."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(SOURCE_URL, timeout=20) as response:
            raw = response.read(LIMIT + 1)
    except (OSError, ValueError, urllib.error.URLError, MiboError):
        raise MiboError("bootstrap_download_failed") from None
    if len(raw) > LIMIT:
        raise MiboError("bootstrap_source_too_large")
    return raw


def extract_constants(raw):
    """Verify bytes before extracting exactly six string literals; execute nothing."""
    if (not isinstance(raw, bytes) or len(raw) > LIMIT
            or hashlib.sha256(raw).hexdigest() != SOURCE_SHA256):
        raise MiboError("bootstrap_digest_mismatch")
    try:
        source = raw.decode("utf-8")
    except UnicodeError:
        raise MiboError("bootstrap_source_invalid") from None
    constants = {}
    for key in APP_FIELDS:
        declarations = re.findall(r"\b(?:let|var)\s+" + key + r"\b", source)
        matches = re.findall(r'\b(?:let|var)\s+' + key + r'\s*(?::\s*String\s*)?=\s*"([^"\\\r\n]+)"', source)
        if len(declarations) != 1 or len(matches) != 1 or not safe_text(matches[0]):
            raise MiboError("bootstrap_constants_invalid")
        constants[key] = matches[0]
    return constants


def valid_cache(value):
    """Require exact pinned provenance and a bounded literal-only cache shape."""
    return (isinstance(value, dict)
            and set(value) == {"version", "source_url", "sha256", "constants"}
            and type(value["version"]) is int and value["version"] == 1
            and value["source_url"] == SOURCE_URL and value["sha256"] == SOURCE_SHA256
            and isinstance(value["constants"], dict)
            and set(value["constants"]) == set(APP_FIELDS)
            and all(safe_text(item) for item in value["constants"].values()))


def _fetch_cache():
    """Run download, hashing, and source parsing together in an executor."""
    try:
        constants = extract_constants(download_source())
    except MiboError:
        raise
    except (OSError, ValueError):
        raise MiboError("bootstrap_download_failed") from None
    return {"version": 1, "source_url": SOURCE_URL,
            "sha256": SOURCE_SHA256, "constants": constants}


async def async_load_app(hass: HomeAssistant) -> dict[str, str]:
    """Load validated cached metadata, fetching only when absent or invalid."""
    store = Store(hass, 1, STORAGE_KEY, private=True)
    try:
        value = await store.async_load()
        if not valid_cache(value):
            value = await hass.async_add_executor_job(_fetch_cache)
            await store.async_save(value)
    except MiboError:
        raise
    except (OSError, ValueError):
        raise MiboError("bootstrap_storage_failed") from None
    return dict(value["constants"])
