# bom-weather-api

Async Python client for Australian [Bureau of Meteorology](https://www.bom.gov.au/)
(BoM) weather data: town forecasts, station observations, hourly forecasts and
warnings. Built for the [Home Assistant integration](https://github.com/tinkerologie/ha-bom-australia),
usable anywhere.

```bash
pip install bom-weather-api
```

Supports Python 3.12 to 3.15.

## Data sources

| Data | Source |
|---|---|
| Forecast towns, daily town (précis) forecasts, station observations | BoM's official [anonymous FTP data feeds](https://www.bom.gov.au/catalogue/data-feeds.shtml) on `ftp.bom.gov.au` |
| Hourly forecasts, warnings, and the extended text, UV, fire danger and sun times in the daily forecast | The undocumented JSON API behind the BoM app (`api.weather.bom.gov.au`) |

The FTP products are free to access for non-commercial use. The app API is not
a public BoM service and may change without notice. When the extras request
fails, `get_daily_forecast` still returns the FTP forecast.

The client always identifies itself with an honest User-Agent. It does not use
the bom.gov.au website API (`api.bom.gov.au`), which blocks automated clients.
Please poll politely: observations change every 10 minutes and town forecasts
a few times a day.

## Usage

```python
import asyncio

from bom_weather_api import BomClient, Coordinate


async def main() -> None:
    async with BomClient() as client:
        home = Coordinate(latitude=-27.47, longitude=153.02)

        locations = await client.get_forecast_locations()
        town, distance = BomClient.nearest(home, locations, limit=1)[0]

        stations = await client.get_stations(town.product_state)
        station, _ = BomClient.nearest(town.coordinate, stations, limit=1)[0]

        observation = await client.get_observation(town.product_state, station.id)
        daily = await client.get_daily_forecast(town)
        hourly = await client.get_hourly_forecast(town.coordinate)
        warnings = await client.get_warnings(town.coordinate, details=True)

        print(town.name, observation.temperature, daily.days[0].short_text)
        print(len(hourly.hours), "hours,", len(warnings), "warnings")


asyncio.run(main())
```

Pass an existing `aiohttp.ClientSession` as the first argument to share
connections; the client never closes a session it did not create.

### API

| Method | Returns |
|---|---|
| `get_forecast_locations()` | Every BoM forecast town (`ForecastLocation`, about 680) |
| `get_stations(state)` | Observation stations in a state (`NSW`, `VIC`, `QLD`, `SA`, `WA`, `TAS`, `NT`; ACT is in `NSW`) |
| `get_observation(state, station_id)` | Latest `Observation` |
| `get_daily_forecast(location, extras=True)` | 7-day `DailyForecast` |
| `get_hourly_forecast(coordinate)` | `HourlyForecast` (about 72 hours) |
| `get_warnings(coordinate, details=False)` | Current `WeatherWarning`s (cancellations excluded) |
| `get_warning(warning_id)` | `WarningDetails` with the plain-text message |
| `BomClient.nearest(coordinate, items, limit=None)` | Items sorted by distance in km |

Every model field is optional: BoM regularly omits values, such as today's
minimum temperature after the morning or today's icon late in the evening.

### Errors

All errors derive from `BomError`:

- `BomConnectionError`, with subclass `BomTimeoutError`
- `BomResponseError` (has `.status`), with subclasses:
  - `BomNotFoundError`
  - `BomRateLimitError` (has `.retry_after`)
- `BomParseError`

## Development

```bash
uv sync
uv run pytest --cov
uv run ruff format . && uv run ruff check . && uv run mypy
```

Test fixtures are real BoM responses captured on 2026-10-28.

## Licence

Apache-2.0. Data © Commonwealth of Australia, Bureau of Meteorology. This
project is not affiliated with or endorsed by the Bureau of Meteorology.
