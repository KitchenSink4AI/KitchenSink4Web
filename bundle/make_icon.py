"""Generate bundle/icon.png for the KitchenSink4Web .mcpb bundle.

Pure stdlib (zlib + struct): 512x512 RGB PNG (Claude Desktop's recommended
icon size), deep-green square with a white sprout, rendered with 4x4
supersampling for smooth edges. The green is the Garden aisle's own
`--live-ink`, so the extension tile matches the product page, and the sprout
is the aisle's fixture.

Deterministic: same input, same bytes, so a rebuild produces no spurious diff.

Usage: python -X utf8 make_icon.py
"""

import math
import struct
import zlib
from pathlib import Path

SIZE = 512          # output pixels
SS = 4              # supersample factor
BG = (55, 109, 58)      # garden  #376d3a
FG = (247, 251, 253)    # near-white sprout

# Everything below is in normalized (0..1) coordinates, y down.

#: The stem: a tapered vertical bar from the soil line up to the crown.
STEM_X = 0.500
STEM_TOP = 0.360
STEM_BOTTOM = 0.880
STEM_HALF_TOP = 0.022
STEM_HALF_BOTTOM = 0.038

#: The two cotyledons, as ellipses rotated about their own centres, each
#: attached to the stem at its inner end and lifted at its outer tip.
#: (cx, cy, semi-major, semi-minor, rotation in degrees)
LEAVES = (
    (0.335, 0.400, 0.190, 0.082, 27.0),
    (0.665, 0.400, 0.190, 0.082, -27.0),
)


def inside_stem(x: float, y: float) -> bool:
    if not (STEM_TOP <= y <= STEM_BOTTOM):
        return False
    t = (y - STEM_TOP) / (STEM_BOTTOM - STEM_TOP)
    half = STEM_HALF_TOP + (STEM_HALF_BOTTOM - STEM_HALF_TOP) * t
    return abs(x - STEM_X) <= half


def inside_leaves(x: float, y: float) -> bool:
    for cx, cy, a, b, deg in LEAVES:
        rad = math.radians(deg)
        cos, sin = math.cos(rad), math.sin(rad)
        dx, dy = x - cx, y - cy
        u = dx * cos + dy * sin
        v = -dx * sin + dy * cos
        if (u / a) ** 2 + (v / b) ** 2 <= 1.0:
            return True
    return False


def inside_sprout(x: float, y: float) -> bool:
    return inside_stem(x, y) or inside_leaves(x, y)


def render() -> bytes:
    scale = 1.0 / (SIZE * SS)
    rows = []
    for oy in range(SIZE):
        row = bytearray()
        row.append(0)  # PNG filter type 0 (None)
        for ox in range(SIZE):
            hit = 0
            for sy in range(SS):
                for sx in range(SS):
                    x = (ox * SS + sx + 0.5) * scale
                    y = (oy * SS + sy + 0.5) * scale
                    if inside_sprout(x, y):
                        hit += 1
            cov = hit / (SS * SS)
            row.extend(
                round(BG[i] + (FG[i] - BG[i]) * cov) for i in range(3)
            )
        rows.append(bytes(row))
    return b"".join(rows)


def write_png(path: Path, raw: bytes) -> None:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", SIZE, SIZE, 8, 2, 0, 0, 0)  # 8-bit RGB
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )
    path.write_bytes(png)


if __name__ == "__main__":
    # Two bundles, one icon. `mcpb pack` packs a DIRECTORY, and both
    # manifests declare `"icon": "icon.png"`, so the field-test directory
    # needs its own copy of the same bytes rather than a reference to the
    # shipped one.
    raw = render()
    here = Path(__file__).parent
    for out in (here / "icon.png", here / "dev" / "icon.png"):
        write_png(out, raw)
        print(f"wrote {out} ({out.stat().st_size} bytes)")
