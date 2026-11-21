"""
Импорт/экспорт палитр: .ase (Adobe Swatch Exchange), .aco (Photoshop), .cls (Clip Studio Paint),
.gpl (GIMP/Krita), .json, .txt/.hex.

import_palettes(path)            -> [(name, ["#RRGGBB", ...]), ...]   (в .ase может быть несколько групп)
export_palette(path, name, cols)  -> формат по расширению
"""
import json
import os
import struct

import numpy as np

from dcp_core import parse_palette, write_palette, lab2rgb, to_hex, from_hex, clip3


def _rgb8(hx):
    hx = hx.lstrip("#")
    return int(hx[0:2], 16), int(hx[2:4], 16), int(hx[4:6], 16)


def _hex8(r, g, b):
    return "#%02X%02X%02X" % (max(0, min(255, round(r))), max(0, min(255, round(g))), max(0, min(255, round(b))))


def _from_cmyk(c, m, y, k):
    return _hex8(255 * (1 - c) * (1 - k), 255 * (1 - m) * (1 - k), 255 * (1 - y) * (1 - k))


def _from_lab(L, a, b):
    return to_hex(clip3(lab2rgb(np.array([L, a, b]))))


# ------------------------------------------------------------------ CLS (Clip Studio Paint color set)
def read_cls(data: bytes, fallback):
    if data[:4] != b"SLCC":
        raise ValueError("не файл набора цветов CSP (нет сигнатуры SLCC)")
    off = 6
    hlen = struct.unpack_from("<I", data, off)[0]
    off += 4
    alen = struct.unpack_from("<H", data, off)[0]
    off += 2
    ascii_name = data[off:off + alen].decode("ascii", "replace")
    off += alen + 4
    ulen = struct.unpack_from("<H", data, off)[0]
    off += 2
    utf8_name = data[off:off + ulen].decode("utf-8", "replace")
    off += ulen
    _channels, count, _blen = struct.unpack_from("<III", data, off)
    off += 12
    cols = []
    for _ in range(min(count, 4096)):
        bl = struct.unpack_from("<I", data, off)[0]
        off += 4
        blk = data[off:off + bl]
        off += bl
        if len(blk) >= 3:
            cols.append(_hex8(blk[0], blk[1], blk[2]))
    return [(utf8_name or ascii_name or fallback, cols)]


def write_cls(name, colors) -> bytes:
    name = name[:64]
    an = "".join(c if ord(c) < 128 else "?" for c in name).encode("ascii")
    un = name.encode("utf-8")
    out = bytearray(b"SLCC")
    out += struct.pack("<H", 256)
    out += struct.pack("<I", len(an) + len(un) + 8)
    out += struct.pack("<H", len(an)) + an + struct.pack("<I", 0)
    out += struct.pack("<H", len(un)) + un
    out += struct.pack("<III", 4, len(colors), len(colors) * 12)
    for hx in colors:
        r, g, b = _rgb8(hx)
        out += struct.pack("<I", 8) + bytes([r, g, b, 255]) + struct.pack("<I", 0)
    return bytes(out)


# ------------------------------------------------------------------ ACO (Photoshop color swatches)
def _aco_color(space, w, x, y, z):
    if space == 0:
        return _hex8(w / 257, x / 257, y / 257)
    if space == 1:
        import colorsys
        r, g, b = colorsys.hsv_to_rgb(w / 65536, x / 65535, y / 65535)
        return _hex8(r * 255, g * 255, b * 255)
    if space == 2:
        return _from_cmyk(1 - w / 65535, 1 - x / 65535, 1 - y / 65535, 1 - z / 65535)
    if space == 7:
        a = x - 65536 if x > 32767 else x
        b = y - 65536 if y > 32767 else y
        return _from_lab(w / 100, a / 100, b / 100)
    if space == 8:
        v = 255 * (1 - w / 10000)
        return _hex8(v, v, v)
    return None


def read_aco(data: bytes, fallback):
    off = 0
    v1 = []
    names = []
    v2 = []
    while off + 4 <= len(data):
        ver, count = struct.unpack_from(">HH", data, off)
        off += 4
        if ver == 1:
            for _ in range(count):
                sp, w, x, y, z = struct.unpack_from(">HHHHH", data, off)
                off += 10
                c = _aco_color(sp, w, x, y, z)
                if c:
                    v1.append(c)
        elif ver == 2:
            for _ in range(count):
                sp, w, x, y, z = struct.unpack_from(">HHHHH", data, off)
                off += 10
                _zero, ln = struct.unpack_from(">HH", data, off)
                off += 4
                nm = data[off:off + ln * 2].decode("utf-16-be", "replace").rstrip("\x00")
                off += ln * 2
                c = _aco_color(sp, w, x, y, z)
                if c:
                    v2.append(c)
                    names.append(nm)
        else:
            break
    return [(fallback, v2 or v1)]


def write_aco(name, colors) -> bytes:
    out = bytearray(struct.pack(">HH", 1, len(colors)))
    for hx in colors:
        r, g, b = _rgb8(hx)
        out += struct.pack(">HHHHH", 0, r * 257, g * 257, b * 257, 0)
    out += struct.pack(">HH", 2, len(colors))
    for hx in colors:
        r, g, b = _rgb8(hx)
        nm = hx.upper() + "\x00"
        out += struct.pack(">HHHHH", 0, r * 257, g * 257, b * 257, 0)
        out += struct.pack(">HH", 0, len(nm)) + nm.encode("utf-16-be")
    return bytes(out)


# ------------------------------------------------------------------ ASE (Adobe Swatch Exchange)
def read_ase(data: bytes, fallback):
    if data[:4] != b"ASEF":
        raise ValueError("не файл ASE (нет сигнатуры ASEF)")
    nblocks = struct.unpack_from(">I", data, 8)[0]
    off = 12
    groups, cur_name, cur = [], None, []
    loose = []
    for _ in range(nblocks):
        if off + 6 > len(data):
            break
        btype, blen = struct.unpack_from(">HI", data, off)
        off += 6
        blk = data[off:off + blen]
        off += blen
        if btype == 0xC001:
            ln = struct.unpack_from(">H", blk, 0)[0]
            cur_name = blk[2:2 + ln * 2].decode("utf-16-be", "replace").rstrip("\x00") or fallback
            cur = []
        elif btype == 0xC002:
            if cur_name is not None:
                groups.append((cur_name, cur))
            cur_name, cur = None, []
        elif btype == 0x0001:
            ln = struct.unpack_from(">H", blk, 0)[0]
            p = 2 + ln * 2
            model = blk[p:p + 4].decode("ascii", "replace")
            p += 4
            if model == "RGB ":
                r, g, b = struct.unpack_from(">fff", blk, p)
                c = _hex8(r * 255, g * 255, b * 255)
            elif model == "CMYK":
                c = _from_cmyk(*struct.unpack_from(">ffff", blk, p))
            elif model == "LAB ":
                L, a, b = struct.unpack_from(">fff", blk, p)
                c = _from_lab(L * 100 if L <= 1.0 else L, a, b)
            elif model == "Gray":
                v = struct.unpack_from(">f", blk, p)[0] * 255
                c = _hex8(v, v, v)
            else:
                continue
            (cur if cur_name is not None else loose).append(c)
    if loose:
        groups.insert(0, (fallback, loose))
    return [g for g in groups if g[1]]


def _ase_name(s):
    s = s + "\x00"
    return struct.pack(">H", len(s)) + s.encode("utf-16-be")


def write_ase(name, colors) -> bytes:
    blocks = []
    blocks.append((0xC001, _ase_name(name)))
    for hx in colors:
        r, g, b = _rgb8(hx)
        body = _ase_name(hx.upper()) + b"RGB " + struct.pack(">fff", r / 255, g / 255, b / 255) + struct.pack(">H", 2)
        blocks.append((0x0001, body))
    blocks.append((0xC002, b""))
    out = bytearray(b"ASEF" + struct.pack(">HHI", 1, 0, len(blocks)))
    for t, body in blocks:
        out += struct.pack(">HI", t, len(body)) + body
    return bytes(out)


# ------------------------------------------------------------------ dispatch
IMPORT_FILTER = "Палитры (*.ase *.aco *.cls *.gpl *.json *.txt *.hex)"
EXPORT_FILTER = ("Clip Studio Paint (*.cls);;Adobe Swatch Exchange (*.ase);;Photoshop Swatches (*.aco);;"
                 "GIMP/Krita (*.gpl);;JSON (*.json);;HEX (*.txt)")


def import_palettes(path):
    ext = os.path.splitext(path)[1].lower()
    fallback = os.path.splitext(os.path.basename(path))[0]
    data = open(path, "rb").read()
    if ext == ".cls":
        return read_cls(data, fallback)
    if ext == ".aco":
        return read_aco(data, fallback)
    if ext == ".ase":
        return read_ase(data, fallback)
    cols = parse_palette(path)
    return [(fallback, cols)] if cols else []


def export_palette(path, name, colors):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".cls":
        open(path, "wb").write(write_cls(name, colors))
    elif ext == ".aco":
        open(path, "wb").write(write_aco(name, colors))
    elif ext == ".ase":
        open(path, "wb").write(write_ase(name, colors))
    else:
        write_palette(path, name, colors)
