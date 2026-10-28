"""Tests for BomClient."""

from __future__ import annotations

from datetime import UTC, date, datetime
from unittest.mock import patch

import aiohttp
from aiointercept import aiointercept
import pytest

from bom_weather_api import (
    BomClient,
    BomConnectionError,
    BomNotFoundError,
    BomParseError,
    BomRateLimitError,
    BomResponseError,
    BomTimeoutError,
    Coordinate,
    ForecastLocation,
)

from .conftest import BRISBANE_GEOHASH, FakeTransport, load_json, url

BRISBANE = Coordinate(latitude=-27.4808, longitude=153.0389)


async def _brisbane(client: BomClient) -> ForecastLocation:
    locations = await client.get_forecast_locations()
    return next(loc for loc in locations if loc.aac == "QLD_PT001")


async def test_get_forecast_locations(client: BomClient) -> None:
    locations = await client.get_forecast_locations()
    # TAS_PT014 is a fire-weather-only point (PRECIS_FLG=0) and is excluded.
    assert [loc.aac for loc in locations] == [
        "QLD_PT045",
        "QLD_PT001",
        "QLD_PT021",
        "NSW_PT027",
    ]
    brisbane = locations[1]
    assert brisbane.name == "Brisbane"
    assert brisbane.state == "QLD"
    assert brisbane.coordinate == BRISBANE
    assert brisbane.timezone == "Australia/Brisbane"
    assert brisbane.public_district == "QLD_PW015"
    assert brisbane.fire_district == "QLD_FW015"
    canberra = locations[3]
    assert canberra.state == "ACT"
    assert canberra.product_state == "NSW"


async def test_nearest(client: BomClient) -> None:
    locations = await client.get_forecast_locations()
    ranked = BomClient.nearest(
        Coordinate(latitude=-27.47, longitude=153.02), locations, limit=2
    )
    assert [(loc.name, distance) for loc, distance in ranked] == [
        ("Brisbane", 2.2),
        ("Boonah", 66.8),
    ]
    assert len(BomClient.nearest(BRISBANE, locations)) == 4


async def test_get_stations(client: BomClient, transport: FakeTransport) -> None:
    stations = await client.get_stations("qld")
    assert {s.id for s in stations} == {"040913", "040211", "040842", "041529"}
    brisbane = next(s for s in stations if s.id == "040913")
    assert brisbane.name == "Brisbane"
    assert brisbane.state == "QLD"
    assert brisbane.wmo_id == "94576"
    assert brisbane.coordinate == BRISBANE
    assert transport.requests == ["/anon/gen/fwo/IDQ60920.xml"]


async def test_get_observation(client: BomClient) -> None:
    obs = await client.get_observation("QLD", "040913")
    assert obs.station_id == "040913"
    assert obs.station_name == "Brisbane"
    assert obs.observed_at == datetime(2026, 10, 28, 1, 40, tzinfo=UTC)
    assert obs.temperature == 28.6
    assert obs.apparent_temperature == 28.4
    assert obs.dew_point == 12.9
    assert obs.delta_t == 9.2
    assert obs.humidity == 38
    assert obs.pressure == 1015.7
    assert obs.wind_speed == 6.0
    assert obs.wind_direction == "WNW"
    assert obs.wind_bearing == 294.0
    assert obs.wind_gust == 13.0
    assert obs.wind_gust_max == 19.0
    assert obs.wind_gust_max_at == datetime(2026, 10, 28, 0, 0, tzinfo=UTC)
    assert obs.rain_since_9am == 0.0
    assert obs.rain_24h == 1.0
    assert obs.temp_max == 28.7
    assert obs.temp_max_at == datetime(2026, 10, 28, 1, 35, tzinfo=UTC)
    assert obs.temp_min == 20.5


async def test_get_observation_unknown_station(client: BomClient) -> None:
    with pytest.raises(BomNotFoundError):
        await client.get_observation("QLD", "999999")


async def test_unknown_state(client: BomClient) -> None:
    with pytest.raises(ValueError, match="Unknown state"):
        await client.get_stations("XX")


async def test_get_daily_forecast(client: BomClient, mock_api: aiointercept) -> None:
    mock_api.get(
        url(f"/locations/{BRISBANE_GEOHASH}/forecasts/daily"),
        payload=load_json("daily.json"),
    )
    forecast = await client.get_daily_forecast(await _brisbane(client))

    assert forecast.issued_at == datetime(2026, 10, 28, 1, 30, 41, tzinfo=UTC)
    assert forecast.next_issue_at == datetime(2026, 10, 28, 5, 10, tzinfo=UTC)
    assert len(forecast.days) == 7
    today = forecast.days[0]
    assert today.date == date(2026, 10, 28)
    assert today.temp_max == 29.0
    assert today.temp_min is None
    assert today.icon_code == 11
    assert today.icon_descriptor == "shower"
    assert today.short_text == "Shower or two."
    assert today.rain_chance == 50
    # The précis has no range for Brisbane today; the app API supplies it.
    assert today.rain_amount_range == "1 to 6 mm"
    assert (
        today.extended_text
        == "Partly cloudy. Medium chance of showers, becoming less likely in the evening. Light winds."
    )
    assert today.uv_index == 11
    assert today.uv_category == "extreme"
    assert today.uv_start == datetime(2026, 10, 27, 21, 30, tzinfo=UTC)
    assert today.fire_danger == "Moderate"
    assert today.sunrise == datetime(2026, 10, 27, 19, 0, 17, tzinfo=UTC)
    assert forecast.now is not None
    assert forecast.now.now_label == "Max"
    assert forecast.now.later_temp == 17.0
    tomorrow = forecast.days[1]
    assert tomorrow.date == date(2026, 10, 29)
    assert tomorrow.temp_min == 17.0
    assert tomorrow.extended_text is not None


async def test_get_daily_forecast_extras_unavailable(
    client: BomClient, mock_api: aiointercept
) -> None:
    mock_api.get(url(f"/locations/{BRISBANE_GEOHASH}/forecasts/daily"), status=500)
    forecast = await client.get_daily_forecast(await _brisbane(client))
    assert forecast.days[0].short_text == "Shower or two."
    assert forecast.days[0].extended_text is None
    assert forecast.now is None


async def test_get_daily_forecast_without_extras(client: BomClient) -> None:
    forecast = await client.get_daily_forecast(await _brisbane(client), extras=False)
    assert forecast.days[0].temp_max == 29.0


async def test_get_daily_forecast_ftp_failure(
    client: BomClient, transport: FakeTransport, mock_api: aiointercept
) -> None:
    location = await _brisbane(client)
    transport.files["/anon/gen/fwo/IDQ11295.xml"] = BomConnectionError("down")
    mock_api.get(
        url(f"/locations/{BRISBANE_GEOHASH}/forecasts/daily"),
        payload=load_json("daily.json"),
    )
    with pytest.raises(BomConnectionError):
        await client.get_daily_forecast(location)


async def test_get_daily_forecast_unexpected_error(client: BomClient) -> None:
    location = await _brisbane(client)
    with (
        patch.object(client, "_legacy", side_effect=RuntimeError("boom")),
        pytest.raises(RuntimeError),
    ):
        await client.get_daily_forecast(location)


async def test_get_daily_forecast_location_missing(client: BomClient) -> None:
    location = ForecastLocation(
        aac="QLD_PT999", name="Nowhere", state="QLD", coordinate=BRISBANE
    )
    with pytest.raises(BomParseError, match="not found"):
        await client.get_daily_forecast(location, extras=False)


async def test_get_hourly_forecast(client: BomClient, mock_api: aiointercept) -> None:
    mock_api.get(
        url(f"/locations/{BRISBANE_GEOHASH}/forecasts/hourly"),
        payload=load_json("hourly.json"),
    )
    forecast = await client.get_hourly_forecast(BRISBANE)
    assert len(forecast.hours) == 73
    first = forecast.hours[0]
    assert first.time == datetime(2026, 10, 28, 1, 0, tzinfo=UTC)
    assert first.temperature == 27.0
    assert first.apparent_temperature == 28.0
    assert first.dew_point == 16.0
    assert first.humidity == 50
    assert first.wind_speed == 9.0
    assert first.wind_gust == 17.0
    assert first.wind_direction == "WSW"
    assert first.wind_bearing == 247.5
    assert first.rain_chance == 30
    assert first.rain_amount_max == 1.0
    assert first.uv_index == 11.0
    assert first.icon_descriptor == "shower"
    assert first.is_night is False
    assert any(hour.is_night for hour in forecast.hours)


async def test_get_warnings(client: BomClient, mock_api: aiointercept) -> None:
    mock_api.get(
        url("/locations/r75t3u/warnings"), payload=load_json("warnings_active.json")
    )
    warnings = await client.get_warnings(Coordinate(latitude=-27.18, longitude=151.25))
    assert len(warnings) == 1
    warning = warnings[0]
    assert warning.id == "QLD_RC170_IDQ20829"
    assert warning.type == "flood_warning"
    assert warning.short_title == "Flood Warning"
    assert warning.group_type == "major"
    assert warning.phase == "new"
    assert warning.message is None


async def test_get_warnings_none(client: BomClient, mock_api: aiointercept) -> None:
    mock_api.get(
        url(f"/locations/{BRISBANE_GEOHASH}/warnings"),
        payload=load_json("warnings.json"),
    )
    assert await client.get_warnings(BRISBANE, details=True) == []


async def test_get_warnings_with_details(
    client: BomClient, mock_api: aiointercept
) -> None:
    mock_api.get(
        url(f"/locations/{BRISBANE_GEOHASH}/warnings"),
        payload={
            "data": [
                {"id": "QLD_RC170_IDQ20829", "phase": "new"},
                {"id": "missing", "phase": "update"},
                {"id": "gone", "phase": "cancelled"},
            ]
        },
    )
    mock_api.get(
        url("/warnings/QLD_RC170_IDQ20829"), payload=load_json("warning_detail.json")
    )
    mock_api.get(url("/warnings/missing"), status=404)
    warnings = await client.get_warnings(BRISBANE, details=True)
    assert [w.id for w in warnings] == ["QLD_RC170_IDQ20829", "missing"]
    assert warnings[0].message is not None
    assert "Initial Minor Flood Warning" in warnings[0].message
    assert "<" not in warnings[0].message
    assert warnings[1].message is None


async def test_get_warnings_details_unexpected_error(
    client: BomClient, mock_api: aiointercept
) -> None:
    mock_api.get(
        url(f"/locations/{BRISBANE_GEOHASH}/warnings"), payload={"data": [{"id": "a"}]}
    )
    with (
        patch.object(client, "get_warning", side_effect=RuntimeError("boom")),
        pytest.raises(RuntimeError),
    ):
        await client.get_warnings(BRISBANE, details=True)


async def test_get_warning_invalid(client: BomClient, mock_api: aiointercept) -> None:
    mock_api.get(url("/warnings/x"), payload={"data": None})
    with pytest.raises(BomParseError):
        await client.get_warning("x")


@pytest.mark.parametrize(
    ("kwargs", "error"),
    [
        ({"status": 404}, BomNotFoundError),
        ({"status": 503}, BomResponseError),
        ({"exception": True}, BomConnectionError),
        ({"body": "<html>"}, BomParseError),
        ({"payload": ["not", "an", "object"]}, BomParseError),
    ],
)
async def test_legacy_errors(
    client: BomClient, mock_api: aiointercept, kwargs: dict, error: type[Exception]
) -> None:
    mock_api.get(url(f"/locations/{BRISBANE_GEOHASH}/forecasts/hourly"), **kwargs)
    with pytest.raises(error):
        await client.get_hourly_forecast(BRISBANE)


async def test_legacy_timeout(client: BomClient) -> None:
    with (
        patch.object(aiohttp.ClientSession, "get", side_effect=TimeoutError),
        pytest.raises(BomTimeoutError),
    ):
        await client.get_hourly_forecast(BRISBANE)


async def test_rate_limit(client: BomClient, mock_api: aiointercept) -> None:
    path = url(f"/locations/{BRISBANE_GEOHASH}/warnings")
    mock_api.get(path, status=429, headers={"Retry-After": "120"})
    with pytest.raises(BomRateLimitError) as exc:
        await client.get_warnings(BRISBANE)
    assert exc.value.retry_after == 120
    assert exc.value.status == 429
    mock_api.get(path, status=429)
    with pytest.raises(BomRateLimitError) as exc:
        await client.get_warnings(BRISBANE)
    assert exc.value.retry_after is None


async def test_invalid_ftp_content(client: BomClient, transport: FakeTransport) -> None:
    transport.files["/anon/gen/fwo/IDQ60920.xml"] = b"<not xml"
    with pytest.raises(BomParseError):
        await client.get_stations("QLD")
    transport.files["/anon/home/adfd/spatial/IDM00013.dbf"] = b"\x03"
    with pytest.raises(BomParseError):
        await client.get_forecast_locations()


async def test_owned_session(transport: FakeTransport, mock_api: aiointercept) -> None:
    mock_api.get(url(f"/locations/{BRISBANE_GEOHASH}/warnings"), payload={"data": []})
    async with BomClient(transport=transport, user_agent="test-agent/1.0") as client:
        await client.get_warnings(BRISBANE)
        session = client._session
        assert session is not None
    assert session.closed
    ((_, calls),) = mock_api.requests.items()
    assert calls[0].headers["User-Agent"] == "test-agent/1.0"


async def test_external_session_not_closed(transport: FakeTransport) -> None:
    async with aiohttp.ClientSession() as session:
        client = BomClient(session, transport=transport)
        await client.close()
        assert not session.closed


def test_default_transport() -> None:
    client = BomClient()
    assert type(client._transport).__name__ == "FtpTransport"
