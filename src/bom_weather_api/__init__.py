"""Async client for Australian Bureau of Meteorology weather data."""

from ._version import __version__
from .client import BomClient
from .const import ICON_DESCRIPTORS
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
from .geohash import geohash_encode
from .models import (
    Coordinate,
    DailyForecast,
    DailyForecastDay,
    ForecastLocation,
    HourlyForecast,
    HourlyForecastPoint,
    NowForecast,
    Observation,
    Station,
    WarningDetails,
    WeatherWarning,
    bearing_to_compass,
    compass_to_bearing,
    icon_descriptor,
    strip_html,
)

__all__ = [
    "ICON_DESCRIPTORS",
    "BomClient",
    "BomConnectionError",
    "BomError",
    "BomNotFoundError",
    "BomParseError",
    "BomRateLimitError",
    "BomResponseError",
    "BomTimeoutError",
    "Coordinate",
    "DailyForecast",
    "DailyForecastDay",
    "FileTransport",
    "ForecastLocation",
    "FtpTransport",
    "HourlyForecast",
    "HourlyForecastPoint",
    "NowForecast",
    "Observation",
    "Station",
    "WarningDetails",
    "WeatherWarning",
    "__version__",
    "bearing_to_compass",
    "compass_to_bearing",
    "geohash_encode",
    "icon_descriptor",
    "strip_html",
]
