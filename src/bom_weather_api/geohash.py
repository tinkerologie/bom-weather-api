"""Geohash encoding, used to address locations in the BoM app API."""

from __future__ import annotations

_BASE32 = "0123456789bcdefghjkmnpqrstuvwxyz"


def geohash_encode(latitude: float, longitude: float, precision: int = 6) -> str:
    """Encode a coordinate as a geohash of the given precision."""
    lat_range = [-90.0, 90.0]
    lon_range = [-180.0, 180.0]
    chars: list[str] = []
    value = bits = 0
    even = True
    while len(chars) < precision:
        bounds, coord = (lon_range, longitude) if even else (lat_range, latitude)
        mid = (bounds[0] + bounds[1]) / 2
        value <<= 1
        if coord > mid:
            value |= 1
            bounds[0] = mid
        else:
            bounds[1] = mid
        even = not even
        bits += 1
        if bits == 5:
            chars.append(_BASE32[value])
            value = bits = 0
    return "".join(chars)
