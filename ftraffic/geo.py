"""Minimal, dependency-free geohash utilities (encode / decode / rings).

A 6-character geohash is a 0.010986 deg (lon) x 0.005493 deg (lat) cell.
At Istanbul's latitude (~41 N) this is roughly 0.92 km x 0.61 km.
"""
from __future__ import annotations

import math

_BASE32 = "0123456789bcdefghjkmnpqrstuvwxyz"
_DECODE = {c: i for i, c in enumerate(_BASE32)}


def encode(lat: float, lon: float, precision: int = 6) -> str:
    lat_rng, lon_rng = [-90.0, 90.0], [-180.0, 180.0]
    bits, bit, ch, even, out = [16, 8, 4, 2, 1], 0, 0, True, []
    while len(out) < precision:
        rng, val = (lon_rng, lon) if even else (lat_rng, lat)
        mid = (rng[0] + rng[1]) / 2
        if val >= mid:
            ch |= bits[bit]
            rng[0] = mid
        else:
            rng[1] = mid
        even = not even
        if bit < 4:
            bit += 1
        else:
            out.append(_BASE32[ch])
            bit, ch = 0, 0
    return "".join(out)


def bbox(gh: str) -> tuple[float, float, float, float]:
    """Return (lat_min, lat_max, lon_min, lon_max) of a geohash cell."""
    lat_rng, lon_rng, even = [-90.0, 90.0], [-180.0, 180.0], True
    for c in gh:
        cd = _DECODE[c]
        for mask in (16, 8, 4, 2, 1):
            rng = lon_rng if even else lat_rng
            mid = (rng[0] + rng[1]) / 2
            if cd & mask:
                rng[0] = mid
            else:
                rng[1] = mid
            even = not even
    return lat_rng[0], lat_rng[1], lon_rng[0], lon_rng[1]


def decode(gh: str) -> tuple[float, float]:
    """Cell centre (lat, lon)."""
    a, b, c, d = bbox(gh)
    return (a + b) / 2, (c + d) / 2


def cell_size(gh: str) -> tuple[float, float]:
    """(dlat, dlon) in degrees."""
    a, b, c, d = bbox(gh)
    return b - a, d - c


def cell_size_km(gh: str) -> tuple[float, float]:
    """(north-south km, east-west km) of the cell."""
    dlat, dlon = cell_size(gh)
    lat, _ = decode(gh)
    return dlat * 110.574, dlon * 111.320 * math.cos(math.radians(lat))


def ring(gh: str, k: int) -> list[str]:
    """Cells at Chebyshev distance exactly k (k=0 -> the cell itself)."""
    lat, lon = decode(gh)
    dlat, dlon = cell_size(gh)
    if k == 0:
        return [gh]
    cells = []
    for i in range(-k, k + 1):
        for j in range(-k, k + 1):
            if max(abs(i), abs(j)) == k:
                cells.append(encode(lat + i * dlat, lon + j * dlon, len(gh)))
    return cells


def chebyshev_index(center: str, other: str) -> int:
    """Ring index of `other` relative to `center` (same precision)."""
    la0, lo0 = decode(center)
    la1, lo1 = decode(other)
    dlat, dlon = cell_size(center)
    return int(max(round(abs(la1 - la0) / dlat), round(abs(lo1 - lo0) / dlon)))
