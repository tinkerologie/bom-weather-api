"""Async client for Bureau of Meteorology weather data.

Daily forecasts, observations and forecast locations come from the BoM's
official anonymous FTP products. Hourly forecasts, warnings and forecast
extras (extended text, UV, fire danger, sun times) come from the JSON API
that backs the BoM app.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable, Mapping
from dataclasses import replace
from functools import partial
import logging
from typing import TYPE_CHECKING, Any, Self

import aiohttp

from .const import (
    DEFAULT_TIMEOUT,
    DEFAULT_USER_AGENT,
    FTP_FORECAST_DIR,
    FTP_LOCATIONS_PATH,
    LEGACY_BASE_URL,
    PRECIS_PRODUCTS,
    STATE_PREFIXES,
)
from .exceptions import (
    BomConnectionError,
    BomError,
    BomNotFoundError,
    BomParseError,
    BomRateLimitError,
    BomResponseError,
    BomTimeoutError,
)
from .ftp import FileTransport, FtpTransport
from .models import (
    Coordinate,
    DailyForecast,
    ForecastLocation,
    HourlyForecast,
    Observation,
    Station,
    WarningDetails,
    WeatherWarning,
)
from .parsers import (
    merge_legacy_daily,
    parse_legacy_hourly,
    parse_legacy_warning,
    parse_legacy_warnings,
    parse_locations,
    parse_observation,
    parse_precis,
    parse_stations,
)

if TYPE_CHECKING:
    from types import TracebackType

_LOGGER = logging.getLogger(__name__)


def _state_prefix(state: str) -> str:
    try:
        return STATE_PREFIXES[state.upper()]
    except KeyError as err:
        raise ValueError(f"Unknown state: {state}") from err


class BomClient:
    """Client for Bureau of Meteorology weather data."""

    def __init__(
        self,
        session: aiohttp.ClientSession | None = None,
        *,
        transport: FileTransport | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        user_agent: str = DEFAULT_USER_AGENT,
        legacy_base_url: str = LEGACY_BASE_URL,
    ) -> None:
        """Initialise the client.

        Pass an existing ``aiohttp.ClientSession`` to share connections; it is
        never closed by the client.
        """
        self._session = session
        self._owns_session = session is None
        self._transport = transport or FtpTransport(timeout=timeout)
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._headers = {"User-Agent": user_agent, "Accept": "application/json"}
        self._legacy_base_url = legacy_base_url.rstrip("/")

    async def __aenter__(self) -> Self:
        """Enter the async context manager."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close the session if the client created it."""
        await self.close()

    async def close(self) -> None:
        """Close the HTTP session if it is owned by the client."""
        if self._owns_session and self._session is not None:
            await self._session.close()
            self._session = None

    # --- Transport helpers -------------------------------------------------

    async def _ftp[T](self, path: str, parser: Callable[[bytes], T]) -> T:
        """Download an FTP product and parse it in a worker thread."""
        content = await self._transport.fetch(path)
        return await asyncio.to_thread(_parse, lambda: parser(content))

    async def _legacy(self, path: str) -> Mapping[str, Any]:
        """GET a BoM app API path and return the decoded JSON object."""
        if self._session is None:
            self._session = aiohttp.ClientSession()
        try:
            async with self._session.get(
                f"{self._legacy_base_url}{path}",
                headers=self._headers,
                timeout=self._timeout,
            ) as response:
                if response.status == 404:
                    raise BomNotFoundError(f"Not found: {path}", status=404)
                if response.status == 429:
                    raise BomRateLimitError(
                        "Rate limited by the BoM API",
                        status=429,
                        retry_after=_retry_after(response.headers),
                    )
                if response.status >= 400:
                    raise BomResponseError(
                        f"Unexpected status {response.status} for {path}",
                        status=response.status,
                    )
                try:
                    data = await response.json(content_type=None)
                except ValueError as err:
                    raise BomParseError(f"Invalid JSON returned for {path}") from err
        except TimeoutError as err:
            raise BomTimeoutError(f"Timeout requesting {path}") from err
        except aiohttp.ClientError as err:
            raise BomConnectionError(f"Error requesting {path}: {err}") from err
        if not isinstance(data, Mapping):
            raise BomParseError(f"Unexpected response for {path}")
        return data

    # --- Locations and stations --------------------------------------------

    async def get_forecast_locations(self) -> list[ForecastLocation]:
        """Return every town BoM issues a précis forecast for (~860 places)."""
        return await self._ftp(FTP_LOCATIONS_PATH, parse_locations)

    async def get_stations(self, state: str) -> list[Station]:
        """Return the observation stations reporting in a state.

        ``state`` is an AAC prefix (``NSW``, ``VIC``, ``QLD``, ``SA``, ``WA``,
        ``TAS`` or ``NT``); ACT stations are included in ``NSW``.
        """
        product = f"ID{_state_prefix(state)}60920.xml"
        return await self._ftp(
            f"{FTP_FORECAST_DIR}/{product}",
            partial(parse_stations, state=state.upper()),
        )

    @staticmethod
    def nearest(
        coordinate: Coordinate,
        items: Iterable[Any],
        *,
        limit: int | None = None,
    ) -> list[tuple[Any, float]]:
        """Sort locations or stations by distance (km) from a coordinate."""
        ranked = sorted(
            (
                (item, round(coordinate.distance_to(item.coordinate), 1))
                for item in items
                if item.coordinate is not None
            ),
            key=lambda pair: pair[1],
        )
        return ranked[:limit] if limit is not None else ranked

    # --- Observations ------------------------------------------------------

    async def get_observation(self, state: str, station_id: str) -> Observation:
        """Return the latest observation for a station."""
        product = f"ID{_state_prefix(state)}60920.xml"
        observation = await self._ftp(
            f"{FTP_FORECAST_DIR}/{product}",
            partial(parse_observation, station_id=station_id),
        )
        if observation is None:
            raise BomNotFoundError(f"Station {station_id} is not reporting", status=404)
        return observation

    # --- Forecasts ---------------------------------------------------------

    async def get_daily_forecast(
        self, location: ForecastLocation, *, extras: bool = True
    ) -> DailyForecast:
        """Return the daily town forecast for a location.

        With ``extras=True`` the forecast is enriched with extended text, UV,
        fire danger and sun times from the BoM app API. If that request fails
        the base forecast is still returned.
        """
        product = PRECIS_PRODUCTS[location.product_state]
        forecast_task = self._ftp(
            f"{FTP_FORECAST_DIR}/{product}.xml",
            partial(parse_precis, aac=location.aac),
        )
        if not extras:
            return await forecast_task
        forecast: DailyForecast | BaseException
        legacy: Mapping[str, Any] | BaseException
        forecast, legacy = await asyncio.gather(
            forecast_task,
            self._legacy(f"/locations/{location.coordinate.geohash}/forecasts/daily"),
            return_exceptions=True,
        )
        if isinstance(forecast, BaseException):
            raise forecast
        if isinstance(legacy, BomError):
            _LOGGER.debug("Forecast extras unavailable: %s", legacy)
            return forecast
        if isinstance(legacy, BaseException):
            raise legacy
        return merge_legacy_daily(forecast, legacy)

    async def get_hourly_forecast(self, coordinate: Coordinate) -> HourlyForecast:
        """Return the hourly forecast for a coordinate (BoM app API)."""
        data = await self._legacy(f"/locations/{coordinate.geohash}/forecasts/hourly")
        return _parse(lambda: parse_legacy_hourly(data))

    # --- Warnings ----------------------------------------------------------

    async def get_warnings(
        self, coordinate: Coordinate, *, details: bool = False
    ) -> list[WeatherWarning]:
        """Return current warnings for a coordinate (BoM app API).

        Cancellations are excluded. With ``details=True`` the plain-text
        message of each warning is fetched as well.
        """
        data = await self._legacy(f"/locations/{coordinate.geohash}/warnings")
        warnings = _parse(lambda: parse_legacy_warnings(data))
        if not details or not warnings:
            return warnings
        results = await asyncio.gather(
            *(self.get_warning(warning.id) for warning in warnings),
            return_exceptions=True,
        )
        enriched: list[WeatherWarning] = []
        for warning, result in zip(warnings, results, strict=True):
            if isinstance(result, BaseException) and not isinstance(result, BomError):
                raise result
            enriched.append(
                replace(warning, message=result.message)
                if isinstance(result, WarningDetails)
                else warning
            )
        return enriched

    async def get_warning(self, warning_id: str) -> WarningDetails:
        """Return the full text of a warning (BoM app API)."""
        data = await self._legacy(f"/warnings/{warning_id}")
        return _parse(lambda: parse_legacy_warning(data))


def _retry_after(headers: Mapping[str, str]) -> int | None:
    try:
        return int(headers["Retry-After"])
    except (KeyError, ValueError):
        return None


def _parse[T](builder: Callable[[], T]) -> T:
    """Run a parser, converting unexpected response shapes to BomParseError."""
    try:
        return builder()
    except (KeyError, TypeError, AttributeError, ValueError) as err:
        raise BomParseError(f"Unexpected response format: {err}") from err
