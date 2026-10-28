<div align="center">

# BoM Weather API

**Async Python client for Australian Bureau of Meteorology weather data**

[![PyPI](https://img.shields.io/pypi/v/bom-weather-api?style=flat-square)](https://pypi.org/project/bom-weather-api/)
[![Python](https://img.shields.io/pypi/pyversions/bom-weather-api?style=flat-square)](https://pypi.org/project/bom-weather-api/)
[![CI](https://img.shields.io/github/actions/workflow/status/tinkerologie/bom-weather-api/ci.yml?branch=main&style=flat-square&label=CI)](https://github.com/tinkerologie/bom-weather-api/actions/workflows/ci.yml)
[![Coverage](https://img.shields.io/codecov/c/github/tinkerologie/bom-weather-api?style=flat-square)](https://codecov.io/gh/tinkerologie/bom-weather-api)
[![License](https://img.shields.io/github/license/tinkerologie/bom-weather-api?style=flat-square)](LICENSE)

</div>

BoM Weather API gives Python code typed, async access to Australian
[Bureau of Meteorology](https://www.bom.gov.au/) (BoM) data: station
observations, 7-day town forecasts, hourly forecasts and weather warnings.
It was built for the [Bureau of Meteorology integration for Home Assistant](https://github.com/tinkerologie/ha-bom-australia),
and works in any asyncio application.

## Contents

- [Features](#features)
- [Installation](#installation)
- [Quick start](#quick-start)
- [Data sources](#data-sources)
- [API reference](#api-reference)
- [Error handling](#error-handling)
- [Responsible use](#responsible-use)
- [Development](#development)
- [Licence and attribution](#licence-and-attribution)

## Features

- **Async throughout**: built on `aiohttp` and `aioftp`, and accepts your own `aiohttp.ClientSession`.
- **Fully typed**: frozen dataclass models, ships `py.typed`, and passes `mypy --strict`.
- **Tolerates missing data**: BoM regularly omits values, such as today's minimum temperature after the morning or today's icon late in the evening. Every field is optional, and a missing value is `None` rather than an exception.
- **Built on official feeds**: forecasts and observations come from BoM's sanctioned anonymous FTP products.
- **Location helpers**: find the nearest forecast towns and observation stations to any coordinate.
- **Predictable errors**: a single exception hierarchy; transport exceptions never leak.
- **Tested**: 100% line and branch coverage against real BoM responses, on Python 3.12, 3.13, 3.14 and 3.15.

## Installation

```bash
pip install bom-weather-api
```

or with [uv](https://docs.astral.sh/uv/):

```bash
uv add bom-weather-api
```

Requires Python 3.12 or later, and outbound FTP access (port 21) to `ftp.bom.gov.au`.

## Quick start

```python
import asyncio

from bom_weather_api import BomClient, Coordinate


async def main() -> None:
    home = Coordinate(latitude=-27.47, longitude=153.02)

    async with BomClient() as client:
        # Find the nearest forecast town and observation station.
        towns = await client.get_forecast_locations()
        town, distance = BomClient.nearest(home, towns, limit=1)[0]

        stations = await client.get_stations(town.product_state)
        station, _ = BomClient.nearest(town.coordinate, stations, limit=1)[0]

        # Fetch current conditions, forecasts and warnings.
        observation = await client.get_observation(town.product_state, station.id)
        daily = await client.get_daily_forecast(town)
        hourly = await client.get_hourly_forecast(town.coordinate)
        warnings = await client.get_warnings(town.coordinate, details=True)

    today = daily.days[0]
    print(f"{town.name} ({distance} km away), station {station.name}")
    print(
        f"Now: {observation.temperature} °C, feels like {observation.apparent_temperature} °C"
    )
    print(
        f"Today: {today.short_text} Max {today.temp_max} °C, {today.rain_chance}% chance of rain"
    )
    print(f"{len(hourly.hours)} hourly forecasts, {len(warnings)} active warnings")


asyncio.run(main())
```

### Sharing a session

Pass an existing `aiohttp.ClientSession` to reuse its connections. The client
never closes a session it did not create.

```python
import aiohttp

async with aiohttp.ClientSession() as session:
    client = BomClient(session)
    forecast = await client.get_daily_forecast(town)
```

## Data sources

| Data | Source |
|---|---|
| Forecast towns, daily town (précis) forecasts, station observations | BoM's official [anonymous FTP data feeds](https://www.bom.gov.au/catalogue/data-feeds.shtml) on `ftp.bom.gov.au` |
| Hourly forecasts, warnings, and the extended text, UV, fire danger and sun times in the daily forecast | The undocumented JSON API behind the BoM app (`api.weather.bom.gov.au`) |

The FTP products are free to access for non-commercial use. The app API is not
a public BoM service and may change without notice. If its daily extras are
unavailable, `get_daily_forecast` still returns the FTP forecast without them.

## API reference

### `BomClient`

```python
BomClient(
    session: aiohttp.ClientSession | None = None,
    *,
    transport: FileTransport | None = None,  # defaults to FtpTransport()
    timeout: float = 30.0,
    user_agent: str = DEFAULT_USER_AGENT,
)
```

| Method | Returns | Description |
|---|---|---|
| `get_forecast_locations()` | `list[ForecastLocation]` | Every town BoM issues a forecast for (about 680) |
| `get_stations(state)` | `list[Station]` | Observation stations in a state: `NSW`, `VIC`, `QLD`, `SA`, `WA`, `TAS` or `NT` (ACT stations are in `NSW`) |
| `get_observation(state, station_id)` | `Observation` | Latest observation from a station |
| `get_daily_forecast(location, *, extras=True)` | `DailyForecast` | 7-day town forecast; `extras` adds extended text, UV, fire danger and sun times |
| `get_hourly_forecast(coordinate)` | `HourlyForecast` | Hourly forecast for about the next 72 hours |
| `get_warnings(coordinate, *, details=False)` | `list[WeatherWarning]` | Current warnings, excluding cancellations; `details` adds each warning's full message |
| `get_warning(warning_id)` | `WarningDetails` | The full plain-text message of a warning |
| `BomClient.nearest(coordinate, items, *, limit=None)` | `list[tuple[item, float]]` | Towns or stations sorted by distance in km |

`BomClient` is an async context manager; `close()` releases a session the client created itself.

### Models

All models are frozen dataclasses exported from `bom_weather_api`.

| Model | Key fields |
|---|---|
| `Coordinate` | `latitude`, `longitude`, `geohash`, `distance_to()` |
| `ForecastLocation` | `aac`, `name`, `state`, `coordinate`, `timezone`, `product_state` |
| `Station` | `id`, `name`, `state`, `coordinate`, `wmo_id` |
| `Observation` | `temperature`, `apparent_temperature`, `dew_point`, `humidity`, `pressure`, `wind_speed`, `wind_direction`, `wind_gust`, `rain_since_9am`, `observed_at`, … |
| `DailyForecast` | `issued_at`, `next_issue_at`, `days`, `now` |
| `DailyForecastDay` | `date`, `temp_max`, `temp_min`, `short_text`, `extended_text`, `rain_chance`, `rain_amount_range`, `uv_index`, `fire_danger`, `sunrise`, `sunset`, … |
| `HourlyForecast` / `HourlyForecastPoint` | `time`, `temperature`, `humidity`, `wind_speed`, `wind_direction`, `rain_chance`, `uv_index`, `is_night`, … |
| `WeatherWarning` / `WarningDetails` | `id`, `type`, `title`, `phase`, `issued_at`, `expires_at`, `message` |

Units are metric: °C, km/h, hPa, mm and km. Times are timezone-aware `datetime` objects.

## Error handling

Every error raised by the client derives from `BomError`:

```text
BomError
├── BomConnectionError        the service could not be reached
│   └── BomTimeoutError       the request timed out
├── BomResponseError          unexpected HTTP or FTP status (.status)
│   ├── BomNotFoundError      unknown station, warning or file
│   └── BomRateLimitError     slow down (.retry_after, in seconds)
└── BomParseError             the response had an unexpected format
```

```python
from bom_weather_api import BomError, BomNotFoundError, BomRateLimitError

try:
    observation = await client.get_observation("QLD", "040913")
except BomNotFoundError:
    ...  # the station is not reporting; choose another one
except BomRateLimitError as err:
    ...  # retry after err.retry_after seconds
except BomError:
    ...  # any other failure
```

## Responsible use

- The client identifies itself with an honest User-Agent. Please keep one that identifies your application.
- Poll no more often than the data changes: observations update every 10 minutes, and town forecasts a few times a day.
- This library does not use the bom.gov.au website API (`api.bom.gov.au`), which blocks automated clients.
- The BoM FTP products are free for non-commercial use. For commercial use, see BoM's [data services](https://www.bom.gov.au/resources/data-services).

## Development

```bash
git clone https://github.com/tinkerologie/bom-weather-api.git
cd bom-weather-api
uv sync

uv run pytest --cov                                         # tests, 100% coverage required
uv run ruff format . && uv run ruff check . && uv run mypy  # format, lint, type-check
uvx bandit --recursive src                                  # security scan
```

Test fixtures in `tests/fixtures/` are real BoM responses captured on
2026-10-28. Releases are published to PyPI from GitHub releases using trusted
publishing; see [CHANGELOG.md](CHANGELOG.md) for the release history.

## Licence and attribution

Released under the [Apache License 2.0](LICENSE).

Weather data © Commonwealth of Australia, Bureau of Meteorology. This project
is not affiliated with or endorsed by the Bureau of Meteorology.
