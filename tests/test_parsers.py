"""Tests for parsers and model helpers, focused on missing and malformed data."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone
import struct

import pytest

from bom_weather_api import (
    Coordinate,
    DailyForecastDay,
    bearing_to_compass,
    compass_to_bearing,
    geohash_encode,
    icon_descriptor,
    strip_html,
)
from bom_weather_api.parsers import (
    _float,
    merge_legacy_daily,
    parse_legacy_hourly,
    parse_legacy_warnings,
    parse_locations,
    parse_observation,
    parse_precis,
    parse_stations,
)

AEST = timezone(timedelta(hours=10))


@pytest.mark.parametrize(
    ("latitude", "longitude", "precision", "expected"),
    [
        (-12.463763, 130.844398, 7, "qvv117j"),
        (-27.4808, 153.0389, 6, "r7hgdm"),
        (0, 0, 6, "7zzzzz"),
    ],
)
def test_geohash(
    latitude: float, longitude: float, precision: int, expected: str
) -> None:
    assert geohash_encode(latitude, longitude, precision) == expected


def test_coordinate_helpers() -> None:
    brisbane = Coordinate(latitude=-27.4808, longitude=153.0389)
    sydney = Coordinate(latitude=-33.8688, longitude=151.2093)
    assert brisbane.geohash == "r7hgdm"
    assert brisbane.distance_to(sydney) == pytest.approx(732, abs=5)


@pytest.mark.parametrize(
    ("bearing", "expected"),
    [
        (None, None),
        (0, "N"),
        (11.24, "N"),
        (11.25, "NNE"),
        (180, "S"),
        (359, "N"),
        (720, "N"),
    ],
)
def test_bearing_to_compass(bearing: float | None, expected: str | None) -> None:
    assert bearing_to_compass(bearing) == expected


@pytest.mark.parametrize(
    ("direction", "expected"), [(None, None), ("N", 0.0), ("sw", 225.0), ("CALM", None)]
)
def test_compass_to_bearing(direction: str | None, expected: float | None) -> None:
    assert compass_to_bearing(direction) == expected


def test_icon_descriptor() -> None:
    assert icon_descriptor(3) == "mostly_sunny"
    assert icon_descriptor(18) == "heavy_shower"
    assert icon_descriptor(5) is None
    assert icon_descriptor(None) is None


def test_strip_html() -> None:
    assert strip_html("<p>Arnhem&nbsp;district.</p>\n<p></p>") == "Arnhem district."
    assert (
        strip_html("<h2>Title</h2><p>One</p><p></p><p>Two</p>") == "Title\n\nOne\n\nTwo"
    )
    assert strip_html("<p></p>") is None
    assert strip_html(None) is None


def test_float_rejects_bad_values() -> None:
    assert _float(True) is None
    assert _float("nan") is None
    assert _float("abc") is None
    assert _float(None) is None
    assert _float("1.25", 1) == 1.2


@pytest.mark.parametrize(
    ("low", "high", "expected"),
    [
        (None, None, None),
        (2.0, None, "2 mm"),
        (2.0, 2.0, "2 mm"),
        (0.0, 1.5, "0 to 1.5 mm"),
    ],
)
def test_rain_amount_range(
    low: float | None, high: float | None, expected: str | None
) -> None:
    day = DailyForecastDay(
        date=date(2026, 1, 1),
        start=datetime(2026, 1, 1, tzinfo=AEST),
        rain_amount_min=low,
        rain_amount_max=high,
    )
    assert day.rain_amount_range == expected


PRECIS = b"""<?xml version="1.0"?>
<product><amoc><issue-time-utc>bad</issue-time-utc></amoc><forecast>
<area aac="X_PT001" type="location">
  <forecast-period start-time-local="2026-10-28T05:00:00+10:00">
    <element type="precipitation_range">2 to 10 mm</element>
    <element type="forecast_icon_code">99</element>
    <text type="probability_of_precipitation">n/a</text>
  </forecast-period>
  <forecast-period start-time-local="2026-10-29T00:00:00+10:00">
    <element type="precipitation_range">5 mm</element>
    <element type="air_temperature_maximum">not a number</element>
    <text type="precis"></text>
  </forecast-period>
  <forecast-period start-time-local="garbage"/>
  <forecast-period/>
</area></forecast></product>"""


def test_parse_precis_partial_data() -> None:
    forecast = parse_precis(PRECIS, "X_PT001")
    assert forecast.issued_at is None
    assert len(forecast.days) == 2
    first, second = forecast.days
    assert (first.rain_amount_min, first.rain_amount_max) == (2.0, 10.0)
    assert first.icon_descriptor is None
    assert first.rain_chance is None
    assert (second.rain_amount_min, second.rain_amount_max) == (5.0, 5.0)
    assert second.temp_max is None
    assert second.short_text is None


def test_merge_legacy_daily_handles_gaps() -> None:
    forecast = parse_precis(PRECIS, "X_PT001")
    merged = merge_legacy_daily(
        forecast,
        {
            "data": [
                "junk",
                {"date": None},
                {
                    "date": "2026-10-27T14:00:00Z",
                    "uv": {"category": "veryhigh", "max_index": 9},
                    "rain": {"amount": {"min": 0, "max": 3}},
                    "now": {"is_night": "no", "temp_now": None},
                },
            ]
        },
    )
    first, second = merged.days
    assert first.uv_category == "very_high"
    assert first.uv_index == 9
    # The précis range wins over the app API amounts.
    assert (first.rain_amount_min, first.rain_amount_max) == (2.0, 10.0)
    assert second.uv_category is None
    assert merged.now is not None
    assert merged.now.is_night is None
    assert merged.now.now_temp is None


def test_merge_legacy_daily_empty_forecast() -> None:
    forecast = parse_precis(b"<product><area aac='A' type='location'/></product>", "A")
    merged = merge_legacy_daily(
        forecast, {"data": [{"date": "2026-10-27T14:00:00Z", "uv": None}]}
    )
    assert merged.days == ()
    assert merged.now is None


def test_merge_legacy_daily_across_dst_change() -> None:
    """Dates still match when the UTC offset changes during the forecast."""
    forecast = parse_precis(
        b"""<product><area aac="A" type="location">
        <forecast-period start-time-local="2026-10-04T00:00:00+11:00"/>
        </area></product>""",
        "A",
    )
    merged = merge_legacy_daily(
        forecast, {"data": [{"date": "2026-10-03T14:00:00Z", "fire_danger": "High"}]}
    )
    assert merged.days[0].fire_danger == "High"


OBSERVATIONS = b"""<product><observations>
<station bom-id="1" description="One" lat="-27" lon="153">
  <period time-utc="2026-10-28T01:40:00+00:00"><level>
    <element type="air_temperature">-</element>
    <element type="rel-humidity">55.4</element>
    <element type="cloud_oktas">3</element>
    <element type="wind_dir">CALM</element>
  </level></period>
</station>
<station bom-id="2" stn-name="TWO"/>
<station/>
</observations></product>"""


def test_parse_stations_and_observation_gaps() -> None:
    stations = parse_stations(OBSERVATIONS, "QLD")
    assert [(s.id, s.name, s.coordinate is None) for s in stations] == [
        ("1", "One", False),
        ("2", "TWO", True),
    ]
    one = parse_observation(OBSERVATIONS, "1")
    assert one is not None
    assert one.temperature is None
    assert one.humidity == 55
    assert one.cloud_oktas == 3
    assert one.wind_direction == "CALM"
    assert one.observed_at == datetime(2026, 10, 28, 1, 40, tzinfo=UTC)
    two = parse_observation(OBSERVATIONS, "2")
    assert two is not None
    assert two.station_name == "TWO"
    assert two.observed_at is None
    assert two.humidity is None
    assert parse_observation(OBSERVATIONS, "3") is None


def test_parse_legacy_hourly_gaps() -> None:
    forecast = parse_legacy_hourly(
        {
            "data": [
                None,
                {"time": None},
                {"time": "2026-10-28T01:00:00Z", "is_night": 1, "wind": None},
            ]
        }
    )
    assert len(forecast.hours) == 1
    hour = forecast.hours[0]
    assert hour.is_night is None
    assert hour.wind_speed is None
    assert hour.wind_bearing is None
    assert forecast.issued_at is None


def test_parse_legacy_warnings_gaps() -> None:
    warnings = parse_legacy_warnings({"data": [None, {"id": ""}, {"id": 5}]})
    assert [w.id for w in warnings] == ["5"]
    assert not warnings[0].is_cancelled


def _dbf(records: list[bytes]) -> bytes:
    """Build a dBase III file with PRECIS_FLG, AAC, PT_NAME, LAT and LON fields."""
    fields = [
        (b"PRECIS_FLG", 1),
        (b"AAC", 9),
        (b"PT_NAME", 10),
        (b"LAT", 5),
        (b"LON", 5),
    ]
    header_len = 32 + 32 * len(fields) + 1
    record_len = 1 + sum(length for _, length in fields)
    header = bytearray(32)
    struct.pack_into("<IHH", header, 4, len(records), header_len, record_len)
    for name, length in fields:
        descriptor = bytearray(32)
        descriptor[: len(name)] = name
        descriptor[11] = ord("C")
        descriptor[16] = length
        header += descriptor
    return bytes(header) + b"\x0d" + b"".join(records)


def test_parse_locations_record_handling() -> None:
    def record(flag: bytes, aac: bytes, name: bytes) -> bytes:
        return flag + b"1" + aac.ljust(9) + name.ljust(10) + b"-27.5" + b"153.0"

    content = _dbf(
        [
            record(b" ", b"QLD_PT001", b"Bundaberg"),
            record(b"*", b"QLD_PT002", b"Deleted"),
            record(b" ", b"QLD_PT003", "Gympie é".encode("latin-1")),
            record(b" ", b"QLD_PT004", b"Short")[:10],
        ]
    )
    locations = parse_locations(content)
    assert [(loc.aac, loc.name) for loc in locations] == [
        ("QLD_PT001", "Bundaberg"),
        ("QLD_PT003", "Gympie é"),
    ]
