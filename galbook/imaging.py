"""把书里的图变成能直接塞给多模态模型的格式（只用标准库）。

  load_for_model(path, max_side=1280) -> (mime, bytes) 或 (None, 原因)
PNG / JPEG / GIF / WebP 原样给；BMP（QLIE 等老引擎常见）转成 PNG，太大时按整数倍缩小；
SVG 和其他格式不转（模型多半不认），返回原因，调用方改给路径。"""
import struct
import zlib

PASS = ((b"\x89PNG\r\n\x1a\n", "image/png"), (b"\xff\xd8\xff", "image/jpeg"), (b"GIF87a", "image/gif"),
        (b"GIF89a", "image/gif"))
MAX_BYTES = 8 * 1024 * 1024


def sniff(head):
    for magic, mime in PASS:
        if head.startswith(magic):
            return mime
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if head[:2] == b"BM":
        return "image/bmp"
    if b"<svg" in head[:512].lower():
        return "image/svg+xml"
    return None


def load_for_model(path, max_side=1280):
    try:
        with open(path, "rb") as f:
            data = f.read(MAX_BYTES + 1)
    except OSError as e:
        return None, "读不到图 / cannot read: %s" % e.__class__.__name__
    if len(data) > MAX_BYTES:
        return None, "图太大（>8MB）/ too large"
    mime = sniff(data[:600])
    if mime in ("image/png", "image/jpeg", "image/gif", "image/webp"):
        return mime, data
    if mime == "image/bmp":
        try:
            return "image/png", bmp_to_png(data, max_side)
        except ValueError as e:
            return None, "BMP 转不了 / unsupported BMP: %s" % e
    if mime == "image/svg+xml":
        return None, "SVG 不能直接当图片发 / SVG is not sent as an image"
    return None, "不认识的图片格式 / unknown image format"


def bmp_to_png(data, max_side=1280):
    """未压缩 BMP（1/4/8 位调色板、16/24/32 位）→ PNG（RGB）。"""
    if data[:2] != b"BM" or len(data) < 54:
        raise ValueError("not a BMP")
    off = struct.unpack_from("<I", data, 10)[0]
    hsize = struct.unpack_from("<I", data, 14)[0]
    if hsize == 12:
        w, h, _, bpp = struct.unpack_from("<HHHH", data, 18)
        comp, ncol, palsz = 0, 0, 3
    else:
        w, h, _, bpp, comp = struct.unpack_from("<iiHHI", data, 18)
        ncol = struct.unpack_from("<I", data, 46)[0] if hsize >= 40 else 0
        palsz = 4
    if comp not in (0, 3) or (comp == 3 and bpp not in (16, 32)):
        raise ValueError("compressed (%d)" % comp)
    top_down = h < 0
    h = abs(h)
    if not (0 < w <= 10000 and 0 < h <= 10000):
        raise ValueError("bad size")
    stride = ((w * bpp + 31) // 32) * 4
    if off + stride * h > len(data):
        raise ValueError("truncated")
    pal = None
    if bpp <= 8:
        n = ncol or (1 << bpp)
        p0 = 14 + hsize
        pal = [data[p0 + i * palsz:p0 + i * palsz + 3][::-1] for i in range(n)]   # BGR → RGB
        pal += [b"\0\0\0"] * (256 - len(pal))
    step = 1
    while max(w, h) // step > max_side:
        step += 1
    ow, oh = (w + step - 1) // step, (h + step - 1) // step
    rows = []
    for oy in range(oh):
        y = oy * step
        src = y if top_down else h - 1 - y
        row = data[off + src * stride: off + src * stride + stride]
        if bpp == 24:
            px = bytearray(w * 3)
            px[0::3], px[1::3], px[2::3] = row[2:w * 3:3], row[1:w * 3:3], row[0:w * 3:3]
        elif bpp == 32:
            px = bytearray(w * 3)
            px[0::3], px[1::3], px[2::3] = row[2:w * 4:4], row[1:w * 4:4], row[0:w * 4:4]
        elif bpp == 16:
            px = bytearray()
            for x in range(w):
                v = row[2 * x] | (row[2 * x + 1] << 8)
                px += bytes(((v >> 10 & 31) * 255 // 31, (v >> 5 & 31) * 255 // 31, (v & 31) * 255 // 31))
        elif bpp == 8:
            px = b"".join(pal[b] for b in row[:w])
        elif bpp in (4, 1):
            per = 8 // bpp
            mask = (1 << bpp) - 1
            idx = [(row[x // per] >> (8 - bpp * (x % per + 1))) & mask for x in range(w)]
            px = b"".join(pal[i] for i in idx)
        else:
            raise ValueError("%d bpp" % bpp)
        if step > 1:
            px = b"".join(bytes(px[x * 3:x * 3 + 3]) for x in range(0, w, step))
        rows.append(b"\0" + bytes(px))
    return _png(ow, oh, b"".join(rows))


def _png(w, h, raw):
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def png_size(data):
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return struct.unpack(">II", data[16:24])
    return None
