"""Losslessly re-encode 8-bit RGBA PNGs as Adam7-interlaced, max-compressed PNGs.

Home Assistant's brand image rules prefer interlaced, optimized PNGs. Pure
standard library so it runs anywhere: python3 optimize_png.py a.png b.png
"""
import struct
import sys
import zlib

BPP = 4
ADAM7 = [(0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8), (2, 0, 4, 4),
         (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2)]


def paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    return a if pa <= pb and pa <= pc else (b if pb <= pc else c)


def chunks(data):
    pos = 8
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        yield data[pos + 4:pos + 8], data[pos + 8:pos + 8 + length]
        pos += 12 + length


def decode(data):
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"
    idat = b""
    for kind, body in chunks(data):
        if kind == b"IHDR":
            w, h, depth, ctype, _, _, lace = struct.unpack(">IIBBBBB", body)
            assert (depth, ctype, lace) == (8, 6, 0), "expects non-interlaced 8-bit RGBA"
        elif kind == b"IDAT":
            idat += body
    raw = zlib.decompress(idat)
    stride = w * BPP
    rows, prev = [], bytearray(stride)
    for y in range(h):
        base = y * (stride + 1)
        f, cur = raw[base], bytearray(raw[base + 1:base + 1 + stride])
        for i in range(stride):
            a = cur[i - BPP] if i >= BPP else 0
            b = prev[i]
            c = prev[i - BPP] if i >= BPP else 0
            if f == 1:
                cur[i] = (cur[i] + a) & 255
            elif f == 2:
                cur[i] = (cur[i] + b) & 255
            elif f == 3:
                cur[i] = (cur[i] + ((a + b) >> 1)) & 255
            elif f == 4:
                cur[i] = (cur[i] + paeth(a, b, c)) & 255
        rows.append(cur)
        prev = cur
    return w, h, rows


def filter_row(cur, prev):
    """Pick the filter with the smallest sum of absolute residuals."""
    n = len(cur)
    cands = [bytes(cur), bytearray(n), bytearray(n), bytearray(n), bytearray(n)]
    for i in range(n):
        x = cur[i]
        a = cur[i - BPP] if i >= BPP else 0
        b = prev[i]
        c = prev[i - BPP] if i >= BPP else 0
        cands[1][i] = (x - a) & 255
        cands[2][i] = (x - b) & 255
        cands[3][i] = (x - ((a + b) >> 1)) & 255
        cands[4][i] = (x - paeth(a, b, c)) & 255
    best = min(range(5), key=lambda f: sum(v if v < 128 else 256 - v for v in cands[f]))
    return bytes([best]) + bytes(cands[best])


def encode(w, h, rows):
    out = bytearray()
    for x0, y0, dx, dy in ADAM7:
        if x0 >= w or y0 >= h:
            continue
        prev = None
        for y in range(y0, h, dy):
            src = rows[y]
            cur = bytearray()
            for x in range(x0, w, dx):
                cur += src[x * BPP:x * BPP + BPP]
            out += filter_row(cur, prev or bytearray(len(cur)))
            prev = cur

    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 1))
            + chunk(b"IDAT", zlib.compress(bytes(out), 9))
            + chunk(b"IEND", b""))


for path in sys.argv[1:]:
    with open(path, "rb") as fh:
        before = fh.read()
    after = encode(*decode(before))
    with open(path, "wb") as fh:
        fh.write(after)
    print(f"{path}: {len(before)} -> {len(after)} bytes, interlaced")
