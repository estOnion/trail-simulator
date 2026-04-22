from __future__ import annotations

import polyline as polyline_lib


def test_polyline_decode_roundtrip():
    pts = [(35.6595, 139.7005), (35.6600, 139.7010), (35.6610, 139.7020)]
    encoded = polyline_lib.encode(pts)
    decoded = polyline_lib.decode(encoded)
    assert len(decoded) == 3
    for a, b in zip(pts, decoded):
        assert abs(a[0] - b[0]) < 1e-4
        assert abs(a[1] - b[1]) < 1e-4
