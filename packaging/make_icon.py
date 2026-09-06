"""Generate assets/rgboff.ico without any third-party imaging library.

Pure stdlib (zlib + struct) so it runs anywhere, including a CI box with no
Pillow. Run it from the repo root:  python packaging/make_icon.py
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

SIZES = (256, 128, 64, 48, 32, 16)
SS = 4  # supersampling factor for cheap antialiasing

BG = (24, 26, 31, 255)
RIM = (139, 144, 152, 255)
GLASS = (44, 48, 56, 255)
SLASH = (224, 92, 92, 255)


def _blend(dst: tuple, src: tuple) -> tuple:
    a = src[3] / 255.0
    return (
        round(dst[0] * (1 - a) + src[0] * a),
        round(dst[1] * (1 - a) + src[1] * a),
        round(dst[2] * (1 - a) + src[2] * a),
        max(dst[3], src[3]),
    )


def draw(size: int) -> list[list[tuple]]:
    """A dark bulb with a red slash: 'lighting, off'."""
    n = size * SS
    px = [[(0, 0, 0, 0) for _ in range(n)] for _ in range(n)]

    cx = cy = n / 2
    radius = n * 0.46
    corner = n * 0.22

    def rounded_square(x: float, y: float) -> bool:
        half = n * 0.47
        dx = abs(x - cx) - (half - corner)
        dy = abs(y - cy) - (half - corner)
        if dx <= 0 and dy <= 0:
            return abs(x - cx) <= half and abs(y - cy) <= half
        dx = max(dx, 0.0)
        dy = max(dy, 0.0)
        return (dx * dx + dy * dy) ** 0.5 <= corner

    bulb_cy = cy - n * 0.06
    bulb_r = n * 0.24

    for y in range(n):
        for x in range(n):
            fx, fy = x + 0.5, y + 0.5

            if not rounded_square(fx, fy):
                continue
            px[y][x] = BG

            # bulb glass
            d = ((fx - cx) ** 2 + (fy - bulb_cy) ** 2) ** 0.5
            if d <= bulb_r:
                px[y][x] = _blend(px[y][x], GLASS)
            elif d <= bulb_r + n * 0.022:
                px[y][x] = _blend(px[y][x], RIM)

            # screw base
            if (abs(fx - cx) <= n * 0.10
                    and bulb_cy + bulb_r * 0.80 <= fy <= bulb_cy + bulb_r * 1.42):
                px[y][x] = _blend(px[y][x], RIM)

            # diagonal slash, from lower-left to upper-right
            # distance from the line x + y = n (i.e. the anti-diagonal)
            dist = abs((fx - cx) + (fy - cy)) / (2 ** 0.5)
            if dist <= n * 0.042 and ((fx - cx) ** 2 + (fy - cy) ** 2) ** 0.5 <= radius:
                px[y][x] = _blend(px[y][x], SLASH)

    # box-filter down to the requested size
    out = [[(0, 0, 0, 0) for _ in range(size)] for _ in range(size)]
    for y in range(size):
        for x in range(size):
            r = g = b = a = 0
            for sy in range(SS):
                for sx in range(SS):
                    p = px[y * SS + sy][x * SS + sx]
                    r += p[0] * p[3]
                    g += p[1] * p[3]
                    b += p[2] * p[3]
                    a += p[3]
            if a:
                out[y][x] = (round(r / a), round(g / a), round(b / a),
                             round(a / (SS * SS)))
    return out


def to_png(pixels: list[list[tuple]]) -> bytes:
    h = len(pixels)
    w = len(pixels[0])
    raw = bytearray()
    for row in pixels:
        raw.append(0)  # filter type 0
        for r, g, b, a in row:
            raw += bytes((r, g, b, a))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + chunk(b"IEND", b""))


def build_ico(path: Path) -> None:
    images = [(s, to_png(draw(s))) for s in SIZES]

    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries = bytearray()
    body = bytearray()
    for size, png in images:
        dim = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(png), offset)
        body += png
        offset += len(png)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + bytes(entries) + bytes(body))


if __name__ == "__main__":
    target = Path(__file__).resolve().parent.parent / "assets" / "rgboff.ico"
    build_ico(target)
    print(f"wrote {target} ({target.stat().st_size} bytes)")
