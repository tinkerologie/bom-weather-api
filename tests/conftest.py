"""Shared fixtures for bom-weather-api tests."""

from __future__ import annotations

from collections.abc import AsyncIterator
import json
from pathlib import Path
import re
from typing import Any

import aiohttp
from aiointercept import aiointercept
import pytest

from bom_weather_api import BomClient, BomNotFoundError
from bom_weather_api.const import LEGACY_BASE_URL

FIXTURES = Path(__file__).parent / "fixtures"
BRISBANE_GEOHASH = "r7hgdm"


def load_json(name: str) -> Any:
    """Load a JSON fixture captured from the BoM app API."""
    return json.loads((FIXTURES / "legacy" / name).read_text(encoding="utf-8"))


def ftp_file(name: str) -> bytes:
    """Load an FTP product fixture."""
    return (FIXTURES / "ftp" / name).read_bytes()


def url(path: str) -> re.Pattern[str]:
    """Match a BoM app API path with any query string."""
    return re.compile(re.escape(f"{LEGACY_BASE_URL}{path}") + r"(\?.*)?$")


class FakeTransport:
    """Serve FTP products from the fixtures directory."""

    def __init__(self) -> None:
        """Initialise with the default fixture files."""
        self.files: dict[str, bytes | Exception] = {
            "/anon/home/adfd/spatial/IDM00013.dbf": ftp_file("IDM00013.dbf"),
            "/anon/gen/fwo/IDQ11295.xml": ftp_file("IDQ11295.xml"),
            "/anon/gen/fwo/IDQ60920.xml": ftp_file("IDQ60920.xml"),
        }
        self.requests: list[str] = []

    async def fetch(self, path: str) -> bytes:
        """Return the fixture for a path."""
        self.requests.append(path)
        value = self.files.get(path)
        if value is None:
            raise BomNotFoundError(f"Not found: {path}", status=550)
        if isinstance(value, Exception):
            raise value
        return value


@pytest.fixture
def transport() -> FakeTransport:
    """Return a fake FTP transport."""
    return FakeTransport()


@pytest.fixture
async def mock_api() -> AsyncIterator[aiointercept]:
    """Intercept aiohttp requests to the BoM app API."""
    async with aiointercept(mock_external_urls=True) as mocked:
        yield mocked


@pytest.fixture
async def client(transport: FakeTransport) -> AsyncIterator[BomClient]:
    """Return a client using the fake FTP transport."""
    async with aiohttp.ClientSession() as session:
        yield BomClient(session, transport=transport)
