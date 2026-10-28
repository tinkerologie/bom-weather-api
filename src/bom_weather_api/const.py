"""Constants for the Bureau of Meteorology API client."""

from __future__ import annotations

from typing import Final

from ._version import __version__

# Official anonymous FTP products ("free to access and are not for commercial
# use", see https://www.bom.gov.au/catalogue/data-feeds.shtml).
FTP_HOST: Final = "ftp.bom.gov.au"
FTP_FORECAST_DIR: Final = "/anon/gen/fwo"
FTP_LOCATIONS_PATH: Final = "/anon/home/adfd/spatial/IDM00013.dbf"

# Undocumented JSON API that backs the BoM app (hourly forecasts and warnings).
LEGACY_BASE_URL: Final = "https://api.weather.bom.gov.au/v1"

DEFAULT_TIMEOUT: Final = 30.0
DEFAULT_USER_AGENT: Final = (
    f"bom-weather-api/{__version__} (+https://github.com/tinkerologie/bom-weather-api)"
)

# AAC prefix -> state product identifier prefix. ACT locations use NSW codes.
STATE_PREFIXES: Final[dict[str, str]] = {
    "NSW": "N",
    "VIC": "V",
    "QLD": "Q",
    "SA": "S",
    "WA": "W",
    "TAS": "T",
    "NT": "D",
}

# Town (précis) forecast product for each state.
PRECIS_PRODUCTS: Final[dict[str, str]] = {
    "NSW": "IDN11060",
    "VIC": "IDV10753",
    "QLD": "IDQ11295",
    "SA": "IDS10044",
    "WA": "IDW14199",
    "TAS": "IDT16710",
    "NT": "IDD10207",
}

# Official icon codes used by the BoM, mapped to the descriptor names used by
# the BoM app API.
ICON_DESCRIPTORS: Final[dict[int, str]] = {
    1: "sunny",
    2: "clear",
    3: "mostly_sunny",
    4: "cloudy",
    6: "hazy",
    8: "light_rain",
    9: "windy",
    10: "fog",
    11: "shower",
    12: "rain",
    13: "dusty",
    14: "frost",
    15: "snow",
    16: "storm",
    17: "light_shower",
    18: "heavy_shower",
    19: "cyclone",
}

COMPASS_POINTS: Final[tuple[str, ...]] = (
    "N",
    "NNE",
    "NE",
    "ENE",
    "E",
    "ESE",
    "SE",
    "SSE",
    "S",
    "SSW",
    "SW",
    "WSW",
    "W",
    "WNW",
    "NW",
    "NNW",
)
