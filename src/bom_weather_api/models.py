"""Typed models for Bureau of Meteorology data.

Every value BoM publishes can be missing or ``null`` (for example the day-0
icon late in the evening, or UV times around daylight-saving changes), so
model fields are optional and parsing never raises on missing values.
"""

from __future__ import annotations

from dataclasses import dataclass
import html
import math
import re
from typing import TYPE_CHECKING, Any

from .const import COMPASS_POINTS, ICON_DESCRIPTORS
from .geohash import geohash_encode

if TYPE_CHECKING:
    from datetime import date, datetime

_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"[ \t\r\f\v]+")
_BLANK_LINES_RE = re.compile(r"\n\s*\n+")
_EARTH_RADIUS_KM = 6371.0


def strip_html(value: Any) -> str | None:
    """Convert a BoM HTML fragment to plain text, keeping paragraph breaks."""
    if not isinstance(value, str):
        return None
    text = html.unescape(_TAG_RE.sub("\n", value)).replace("\xa0", " ")
    text = _SPACE_RE.sub(" ", text)
    lines = "\n".join(line.strip() for line in text.split("\n"))
    return _BLANK_LINES_RE.sub("\n\n", lines).strip() or None


def bearing_to_compass(bearing: float | None) -> str | None:
    """Convert a bearing in degrees to a 16-point compass direction."""
    if bearing is None:
        return None
    return COMPASS_POINTS[int((bearing % 360 + 11.25) // 22.5) % 16]


def compass_to_bearing(direction: str | None) -> float | None:
    """Convert a 16-point compass direction to a bearing in degrees."""
    if direction is None:
        return None
    try:
        return COMPASS_POINTS.index(direction.upper()) * 22.5
    except ValueError:
        return None


def icon_descriptor(icon_code: int | None) -> str | None:
    """Return the BoM descriptor (e.g. ``mostly_sunny``) for an icon code."""
    return ICON_DESCRIPTORS.get(icon_code) if icon_code is not None else None


@dataclass(frozen=True, slots=True, kw_only=True)
class Coordinate:
    """A WGS84 coordinate."""

    latitude: float
    longitude: float

    @property
    def geohash(self) -> str:
        """Return the 6-character geohash used by the BoM app API."""
        return geohash_encode(self.latitude, self.longitude, 6)

    def distance_to(self, other: Coordinate) -> float:
        """Return the great-circle distance to another coordinate in km."""
        lat1, lon1, lat2, lon2 = map(
            math.radians,
            (self.latitude, self.longitude, other.latitude, other.longitude),
        )
        a = (
            math.sin((lat2 - lat1) / 2) ** 2
            + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
        )
        return 2 * _EARTH_RADIUS_KM * math.asin(math.sqrt(a))


@dataclass(frozen=True, slots=True, kw_only=True)
class ForecastLocation:
    """A town or suburb BoM issues a précis (town) forecast for."""

    aac: str
    """Area code, e.g. ``QLD_PT001``."""
    name: str
    state: str
    """State or territory, e.g. ``QLD`` or ``ACT``."""
    coordinate: Coordinate
    timezone: str | None = None
    elevation: float | None = None
    public_district: str | None = None
    fire_district: str | None = None

    @property
    def product_state(self) -> str:
        """Return the state whose products cover this location (ACT uses NSW)."""
        return self.aac.split("_", 1)[0]


@dataclass(frozen=True, slots=True, kw_only=True)
class Station:
    """A BoM observation station."""

    id: str
    """BoM station number, e.g. ``040913``."""
    name: str
    state: str
    coordinate: Coordinate | None = None
    wmo_id: str | None = None
    height: float | None = None
    observes: frozenset[str] = frozenset()
    """Measurements in the station's latest observation: ``temperature``,
    ``humidity``, ``wind``, ``pressure`` and ``rain``. Beacons and portable
    stations often report only some of them."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Observation:
    """Latest observation from a BoM weather station."""

    station_id: str
    station_name: str | None = None
    observed_at: datetime | None = None
    temperature: float | None = None
    apparent_temperature: float | None = None
    dew_point: float | None = None
    delta_t: float | None = None
    humidity: int | None = None
    pressure: float | None = None
    """Mean sea level pressure (hPa)."""
    wind_speed: float | None = None
    """10-minute average wind speed (km/h)."""
    wind_direction: str | None = None
    wind_bearing: float | None = None
    wind_gust: float | None = None
    """Current wind gust (km/h)."""
    wind_gust_max: float | None = None
    """Maximum wind gust today (km/h)."""
    wind_gust_max_at: datetime | None = None
    rain_since_9am: float | None = None
    rain_24h: float | None = None
    """Rainfall in the 24 hours to 9am today (mm)."""
    temp_max: float | None = None
    temp_max_at: datetime | None = None
    temp_min: float | None = None
    temp_min_at: datetime | None = None
    visibility: float | None = None
    """Visibility (km)."""
    cloud: str | None = None
    cloud_oktas: int | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class DailyForecastDay:
    """Forecast for a single local day."""

    date: date
    """The local date."""
    start: datetime
    """Start of the forecast period. Day 0 starts at the issue time."""
    temp_max: float | None = None
    temp_min: float | None = None
    icon_code: int | None = None
    short_text: str | None = None
    extended_text: str | None = None
    rain_chance: int | None = None
    rain_amount_min: float | None = None
    """Lower end of the forecast rain range (mm)."""
    rain_amount_max: float | None = None
    """Upper end of the forecast rain range (mm)."""
    uv_index: float | None = None
    uv_category: str | None = None
    uv_start: datetime | None = None
    uv_end: datetime | None = None
    fire_danger: str | None = None
    sunrise: datetime | None = None
    sunset: datetime | None = None

    @property
    def icon_descriptor(self) -> str | None:
        """Return the BoM descriptor for the icon."""
        return icon_descriptor(self.icon_code)

    @property
    def rain_amount_range(self) -> str | None:
        """Return the rain range as BoM displays it, e.g. ``1 to 6 mm``."""
        low, high = self.rain_amount_min, self.rain_amount_max
        if low is None:
            return None
        if high is None or high == low:
            return f"{low:g} mm"
        return f"{low:g} to {high:g} mm"


@dataclass(frozen=True, slots=True, kw_only=True)
class NowForecast:
    """The "now and later" temperatures shown at the top of the BoM app."""

    is_night: bool | None = None
    now_label: str | None = None
    now_temp: float | None = None
    later_label: str | None = None
    later_temp: float | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class DailyForecast:
    """Daily town forecast for a location."""

    issued_at: datetime | None
    next_issue_at: datetime | None
    days: tuple[DailyForecastDay, ...]
    now: NowForecast | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class HourlyForecastPoint:
    """Forecast for a single hour."""

    time: datetime
    temperature: float | None = None
    apparent_temperature: float | None = None
    dew_point: float | None = None
    humidity: int | None = None
    wind_speed: float | None = None
    """Average wind speed (km/h)."""
    wind_gust: float | None = None
    """Wind gust (km/h)."""
    wind_direction: str | None = None
    rain_chance: int | None = None
    rain_amount_min: float | None = None
    rain_amount_max: float | None = None
    uv_index: float | None = None
    icon_descriptor: str | None = None
    is_night: bool | None = None

    @property
    def wind_bearing(self) -> float | None:
        """Return the wind direction in degrees."""
        return compass_to_bearing(self.wind_direction)


@dataclass(frozen=True, slots=True, kw_only=True)
class HourlyForecast:
    """Hourly forecast for a location."""

    issued_at: datetime | None
    hours: tuple[HourlyForecastPoint, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class WeatherWarning:
    """A current BoM warning affecting a location."""

    id: str
    type: str | None = None
    """Warning type, e.g. ``flood_warning``."""
    title: str | None = None
    short_title: str | None = None
    state: str | None = None
    group_type: str | None = None
    """``major`` or ``minor``."""
    phase: str | None = None
    """For example ``new``, ``update``, ``renewal``, ``final`` or ``cancelled``."""
    issued_at: datetime | None = None
    expires_at: datetime | None = None
    message: str | None = None
    """Plain-text warning message, set by ``get_warnings(details=True)``."""

    @property
    def is_cancelled(self) -> bool:
        """Return True if this is a cancellation notice."""
        return self.phase == "cancelled"


@dataclass(frozen=True, slots=True, kw_only=True)
class WarningDetails:
    """The full text of a BoM warning."""

    id: str
    title: str | None = None
    message: str | None = None
    issued_at: datetime | None = None
    expires_at: datetime | None = None
