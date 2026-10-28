"""Parsers for BoM FTP products and BoM app API responses.

The parsers are synchronous and side-effect free; ``BomClient`` runs the XML
and DBF parsers in a worker thread.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import replace
from datetime import datetime, timedelta
import re
import struct
from typing import TYPE_CHECKING, Any

from defusedxml import ElementTree

from .exceptions import BomParseError
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
    strip_html,
)

if TYPE_CHECKING:
    # Type annotation only: all parsing goes through defusedxml.
    from xml.etree.ElementTree import Element  # nosec B405

_RANGE_RE = re.compile(r"(\d+(?:\.\d+)?)(?:\s*to\s*(\d+(?:\.\d+)?))?\s*mm")
_PERCENT_RE = re.compile(r"(\d+)\s*%")
_DBF_TERMINATOR = 0x0D


def _float(value: Any, ndigits: int | None = None) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        try:
            value = float(value)
        except ValueError:
            return None
    if not isinstance(value, int | float) or value != value:  # noqa: PLR0124 (NaN)
        return None
    return round(float(value), ndigits) if ndigits is not None else float(value)


def _int(value: Any) -> int | None:
    number = _float(value)
    return round(number) if number is not None else None


def _str(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return value.strip() or None


def _datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _get(data: Any, *path: str) -> Any:
    for key in path:
        if not isinstance(data, Mapping):
            return None
        data = data.get(key)
    return data


def _xml(content: bytes) -> Element:
    try:
        root: Element = ElementTree.fromstring(content)
    except ElementTree.ParseError as err:
        raise BomParseError(f"Invalid XML: {err}") from err
    return root


# --- Forecast locations (IDM00013.dbf) ---------------------------------------


def _dbf_records(content: bytes) -> Iterator[dict[str, str]]:
    """Yield the records of a dBase III file as dicts of stripped strings."""
    try:
        count, header_len, record_len = struct.unpack_from("<IHH", content, 4)
        fields: list[tuple[str, int]] = []
        offset = 32
        while content[offset] != _DBF_TERMINATOR:
            name = content[offset : offset + 11].split(b"\0", 1)[0].decode("ascii")
            fields.append((name, content[offset + 16]))
            offset += 32
    except (struct.error, IndexError, UnicodeDecodeError) as err:
        raise BomParseError("Invalid DBF header") from err

    for index in range(count):
        start = header_len + index * record_len
        record = content[start : start + record_len]
        if len(record) < record_len or record[:1] == b"*":
            continue
        position = 1
        values: dict[str, str] = {}
        for name, length in fields:
            raw = record[position : position + length]
            try:
                values[name] = raw.decode("utf-8").strip()
            except UnicodeDecodeError:
                values[name] = raw.decode("latin-1").strip()
            position += length
        yield values


def parse_locations(content: bytes) -> list[ForecastLocation]:
    """Parse the précis forecast locations file (IDM00013.dbf)."""
    locations: list[ForecastLocation] = []
    for record in _dbf_records(content):
        latitude = _float(record.get("LAT"))
        longitude = _float(record.get("LON"))
        aac = record.get("AAC")
        if (
            record.get("PRECIS_FLG") != "1"
            or not aac
            or latitude is None
            or longitude is None
        ):
            continue
        locations.append(
            ForecastLocation(
                aac=aac,
                name=record.get("PT_NAME") or aac,
                state=record.get("STATE_CODE") or aac.split("_", 1)[0],
                coordinate=Coordinate(
                    latitude=round(latitude, 4), longitude=round(longitude, 4)
                ),
                timezone=_str(record.get("TIME_ZONE")),
                elevation=_float(record.get("ELEVATION"), 1),
                public_district=_str(record.get("AAC_PW")),
                fire_district=_str(record.get("AAC_FW")),
            )
        )
    return locations


# --- Town forecasts (précis XML) ---------------------------------------------


def _typed(period: Element, tag: str) -> dict[str, str]:
    return {
        item.get("type", ""): (item.text or "").strip() for item in period.iter(tag)
    }


def _rain_range(value: str | None) -> tuple[float | None, float | None]:
    if not value or not (match := _RANGE_RE.search(value)):
        return None, None
    low = float(match.group(1))
    return low, float(match.group(2)) if match.group(2) else low


def parse_precis(content: bytes, aac: str) -> DailyForecast:
    """Parse a state précis forecast product for one location."""
    root = _xml(content)
    area = next((a for a in root.iter("area") if a.get("aac") == aac), None)
    if area is None:
        raise BomParseError(f"Location {aac} not found in forecast product")

    days: list[DailyForecastDay] = []
    for period in area.iter("forecast-period"):
        start = _datetime(period.get("start-time-local"))
        if start is None:
            continue
        elements = _typed(period, "element")
        texts = _typed(period, "text")
        low, high = _rain_range(elements.get("precipitation_range"))
        chance = _PERCENT_RE.search(texts.get("probability_of_precipitation", ""))
        days.append(
            DailyForecastDay(
                date=start.date(),
                start=start,
                temp_max=_float(elements.get("air_temperature_maximum")),
                temp_min=_float(elements.get("air_temperature_minimum")),
                icon_code=_int(elements.get("forecast_icon_code")),
                short_text=_str(texts.get("precis")),
                rain_chance=int(chance.group(1)) if chance else None,
                rain_amount_min=low,
                rain_amount_max=high,
            )
        )

    return DailyForecast(
        issued_at=_datetime(root.findtext("amoc/issue-time-utc")),
        next_issue_at=_datetime(root.findtext("amoc/next-routine-issue-time-utc")),
        days=tuple(days),
    )


# --- Observations (state observation XML) ------------------------------------


def _station(element: Element, state: str) -> Station | None:
    station_id = _str(element.get("bom-id"))
    if not station_id:
        return None
    latitude = _float(element.get("lat"))
    longitude = _float(element.get("lon"))
    return Station(
        id=station_id,
        name=_str(element.get("description"))
        or _str(element.get("stn-name"))
        or station_id,
        state=state,
        coordinate=Coordinate(latitude=latitude, longitude=longitude)
        if latitude is not None and longitude is not None
        else None,
        wmo_id=_str(element.get("wmo-id")),
        height=_float(element.get("stn-height")),
    )


def parse_stations(content: bytes, state: str) -> list[Station]:
    """Parse the stations listed in a state observation product."""
    return [
        station
        for element in _xml(content).iter("station")
        if (station := _station(element, state))
    ]


def parse_observation(content: bytes, station_id: str) -> Observation | None:
    """Parse the latest observation for a station from a state product.

    Returns None if the station is not in the product.
    """
    for element in _xml(content).iter("station"):
        if element.get("bom-id") == station_id:
            return _observation(element, station_id)
    return None


def _observation(station: Element, station_id: str) -> Observation:
    period = station.find("period")
    items: dict[str, Element] = {}
    if period is not None:
        items = {item.get("type", ""): item for item in period.iter("element")}

    def value(name: str, ndigits: int | None = 1) -> float | None:
        item = items.get(name)
        return _float(item.text, ndigits) if item is not None else None

    def text(name: str) -> str | None:
        item = items.get(name)
        return _str(item.text) if item is not None else None

    def time(name: str) -> datetime | None:
        item = items.get(name)
        return _datetime(item.get("time-utc")) if item is not None else None

    humidity = value("rel-humidity", None)
    oktas = value("cloud_oktas", None)
    return Observation(
        station_id=station_id,
        station_name=_str(station.get("description")) or _str(station.get("stn-name")),
        observed_at=_datetime(period.get("time-utc")) if period is not None else None,
        temperature=value("air_temperature"),
        apparent_temperature=value("apparent_temp"),
        dew_point=value("dew_point"),
        delta_t=value("delta_t"),
        humidity=round(humidity) if humidity is not None else None,
        pressure=value("msl_pres"),
        wind_speed=value("wind_spd_kmh"),
        wind_direction=text("wind_dir"),
        wind_bearing=value("wind_dir_deg", 0),
        wind_gust=value("gust_kmh"),
        wind_gust_max=value("maximum_gust_kmh"),
        wind_gust_max_at=time("maximum_gust_kmh"),
        rain_since_9am=value("rainfall"),
        rain_24h=value("rainfall_24hr"),
        temp_max=value("maximum_air_temperature"),
        temp_max_at=time("maximum_air_temperature"),
        temp_min=value("minimum_air_temperature"),
        temp_min_at=time("minimum_air_temperature"),
        visibility=value("vis_km"),
        cloud=text("cloud"),
        cloud_oktas=round(oktas) if oktas is not None else None,
    )


# --- BoM app API (JSON) ------------------------------------------------------


def _local_date_key(value: datetime, offset: timedelta | None) -> Any:
    # BoM app API dates are local midnight expressed in UTC. Shift to local noon
    # first so a daylight-saving change can never move the date.
    local = value + (offset or timedelta()) + timedelta(hours=12)
    return local.date()


def _uv_category(value: Any) -> str | None:
    category = _str(value)
    if category is None:
        return None
    return {"veryhigh": "very_high", "very high": "very_high"}.get(
        category.lower(), category.lower()
    )


def merge_legacy_daily(
    forecast: DailyForecast, data: Mapping[str, Any]
) -> DailyForecast:
    """Add extended text, UV, fire danger and sun times from the BoM app API."""
    offset = forecast.days[0].start.utcoffset() if forecast.days else None
    extras: dict[Any, Mapping[str, Any]] = {}
    now: NowForecast | None = None
    for item in data.get("data") or ():
        if (
            not isinstance(item, Mapping)
            or (when := _datetime(item.get("date"))) is None
        ):
            continue
        extras[_local_date_key(when, offset)] = item
        if now is None and isinstance(item.get("now"), Mapping):
            now_data = item["now"]
            now = NowForecast(
                is_night=now_data.get("is_night")
                if isinstance(now_data.get("is_night"), bool)
                else None,
                now_label=_str(now_data.get("now_label")),
                now_temp=_float(now_data.get("temp_now")),
                later_label=_str(now_data.get("later_label")),
                later_temp=_float(now_data.get("temp_later")),
            )

    days = []
    for day in forecast.days:
        extra = extras.get(day.date)
        if extra is None:
            days.append(day)
            continue
        legacy_min = _float(_get(extra, "rain", "amount", "min"))
        legacy_max = _float(_get(extra, "rain", "amount", "max"))
        has_range = day.rain_amount_min is not None
        days.append(
            replace(
                day,
                rain_amount_min=day.rain_amount_min if has_range else legacy_min,
                rain_amount_max=day.rain_amount_max if has_range else legacy_max,
                extended_text=_str(extra.get("extended_text")),
                uv_index=_float(_get(extra, "uv", "max_index")),
                uv_category=_uv_category(_get(extra, "uv", "category")),
                uv_start=_datetime(_get(extra, "uv", "start_time")),
                uv_end=_datetime(_get(extra, "uv", "end_time")),
                fire_danger=_str(extra.get("fire_danger")),
                sunrise=_datetime(_get(extra, "astronomical", "sunrise_time")),
                sunset=_datetime(_get(extra, "astronomical", "sunset_time")),
            )
        )
    return replace(forecast, days=tuple(days), now=now)


def parse_legacy_hourly(data: Mapping[str, Any]) -> HourlyForecast:
    """Parse a BoM app API hourly forecast."""
    hours: list[HourlyForecastPoint] = []
    for item in data.get("data") or ():
        if (
            not isinstance(item, Mapping)
            or (time := _datetime(item.get("time"))) is None
        ):
            continue
        is_night = item.get("is_night")
        hours.append(
            HourlyForecastPoint(
                time=time,
                temperature=_float(item.get("temp")),
                apparent_temperature=_float(item.get("temp_feels_like")),
                dew_point=_float(item.get("dew_point")),
                humidity=_int(item.get("relative_humidity")),
                wind_speed=_float(_get(item, "wind", "speed_kilometre")),
                wind_gust=_float(_get(item, "wind", "gust_speed_kilometre")),
                wind_direction=_str(_get(item, "wind", "direction")),
                rain_chance=_int(_get(item, "rain", "chance")),
                rain_amount_min=_float(_get(item, "rain", "amount", "min")),
                rain_amount_max=_float(_get(item, "rain", "amount", "max")),
                uv_index=_float(item.get("uv")),
                icon_descriptor=_str(item.get("icon_descriptor")),
                is_night=is_night if isinstance(is_night, bool) else None,
            )
        )
    return HourlyForecast(
        issued_at=_datetime(_get(data, "metadata", "issue_time")),
        hours=tuple(hours),
    )


def parse_legacy_warnings(data: Mapping[str, Any]) -> list[WeatherWarning]:
    """Parse a BoM app API warnings list, excluding cancellations."""
    warnings: list[WeatherWarning] = []
    for item in data.get("data") or ():
        if not isinstance(item, Mapping) or not item.get("id"):
            continue
        warning = WeatherWarning(
            id=str(item["id"]),
            type=_str(item.get("type")),
            title=_str(item.get("title")),
            short_title=_str(item.get("short_title")),
            state=_str(item.get("state")),
            group_type=_str(item.get("warning_group_type")),
            phase=_str(item.get("phase")),
            issued_at=_datetime(item.get("issue_time")),
            expires_at=_datetime(item.get("expiry_time")),
        )
        if not warning.is_cancelled:
            warnings.append(warning)
    return warnings


def parse_legacy_warning(data: Mapping[str, Any]) -> WarningDetails:
    """Parse a BoM app API warning detail response."""
    item = data.get("data")
    if not isinstance(item, Mapping) or not item.get("id"):
        raise BomParseError("Warning response has no data")
    return WarningDetails(
        id=str(item["id"]),
        title=_str(item.get("title")),
        message=strip_html(item.get("message")),
        issued_at=_datetime(item.get("issue_time")),
        expires_at=_datetime(item.get("expiry_time")),
    )
