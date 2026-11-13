"""游戏素材管线：.gfx 索引 + DDS/TGA 解码 + 内联 PNG。

为什么要有这个模块：离线预览原来只有方块和文字，看不出「图标对不对」。
国策、事件、决议、国家精神最有辨识度的部分就是图标——名字对、图标错，
玩家一眼就能发现，而纯文字预览完全看不见。

素材从**用户自己的游戏目录**读（Paradox 的资源不随插件分发，也不该分发），
所以这里做的是「sprite 名 → 引擎目录取文件 → 解码 → 缩到展示尺寸 →
直接内联成 data URI」。生成的 HTML 仍然是单文件、无外链、可离线双击打开。

为什么不用 Pillow：插件承诺纯标准库零依赖。DDS 的四种主格式（DXT1/DXT3/
DXT5/未压缩 32bpp）解码不到 200 行，PNG 编码用 zlib 也就 60 行，比引入一个
需要编译的依赖便宜得多。
"""

from __future__ import annotations

import base64
import os
import re
import struct
import sys
import zlib
from typing import Iterable

# --------------------------------------------------------------------------- #
# DDS
# ------------------------------------------------------------------------- #

DDPF_FOURCC = 0x4
DDPF_RGB = 0x40
DDPF_ALPHAPIXELS = 0x1
DDSCAPS2_CUBEMAP = 0x200
DDSCAPS2_VOLUME = 0x200000


def _u32(data: bytes, off: int) -> int:
    return struct.unpack("<I", data[off : off + 4])[0]


def _mask_channel(mask: int) -> tuple[int, int]:
    """把一个位掩码拆成 (右移位数, 有效位数)。"""
    if not mask:
        return 0, 0
    shift = (mask & -mask).bit_length() - 1
    bits = bin(mask >> shift).count("1")
    return shift, bits


def _scaled(value: int, shift: int, bits: int) -> int:
    if not bits:
        return 0
    v = (value >> shift) & ((1 << bits) - 1)
    # 0..2^bits-1 线性拉伸到 0..255。原版图标是 8bpp，直接命中 255 上限。
    return v * 255 // ((1 << bits) - 1)


def _rgb565(color: int) -> tuple[int, int, int]:
    r = (color >> 11) & 0x1F
    g = (color >> 5) & 0x3F
    b = color & 0x1F
    # 565 的非对称位宽必须按位数归一，直接乘 8 会让绿色偏亮。
    return (r * 255 // 31, g * 255 // 63, b * 255 // 31)


def _decode_bc1_blocks(data: bytes, w: int, h: int, with_alpha: bool = True) -> bytearray:
    """BC1/DXT1：每块 2 个 RGB565 端点 + 16 个 2-bit 索引。

    颜色模式由 c0/c1 的大小关系决定，这是格式规范，不是内容约定：
    c0 > c1 时四色不透明；c0 <= c1 时第四色是透明（游戏里做遮罩用）。
    """
    out = bytearray(w * h * 4)
    bw, bh = (w + 3) // 4, (h + 3) // 4
    stride = w * 4
    for by in range(bh):
        for bx in range(bw):
            off = (by * bw + bx) * 8
            if off + 8 > len(data):
                return out
            c0, c1, bits = struct.unpack("<HHI", data[off : off + 8])
            r0, g0, b0 = _rgb565(c0)
            r1, g1, b1 = _rgb565(c1)
            if c0 > c1 or not with_alpha:
                r2, g2, b2 = (2 * r0 + r1) // 3, (2 * g0 + g1) // 3, (2 * b0 + b1) // 3
                r3, g3, b3 = (r0 + 2 * r1) // 3, (g0 + 2 * g1) // 3, (b0 + 2 * b1) // 3
                a2 = a3 = 255
            else:
                r2, g2, b2 = (r0 + r1) // 2, (g0 + g1) // 2, (b0 + b1) // 2
                r3 = g3 = b3 = 0
                a2 = 255
                a3 = 0
            colors = (
                (r0, g0, b0, 255),
                (r1, g1, b1, 255),
                (r2, g2, b2, a2),
                (r3, g3, b3, a3),
            )
            base_x, base_y = bx * 4, by * 4
            for py in range(4):
                y = base_y + py
                if y >= h:
                    continue
                row = y * stride
                for px in range(4):
                    x = base_x + px
                    if x >= w:
                        continue
                    c = colors[(bits >> (2 * (py * 4 + px))) & 3]
                    i = row + x * 4
                    out[i] = c[0]
                    out[i + 1] = c[1]
                    out[i + 2] = c[2]
                    out[i + 3] = c[3]
    return out


def _decode_bc2_blocks(data: bytes, w: int, h: int) -> bytearray:
    """BC2/DXT3：8 字节显式 4-bit alpha + BC1 颜色块（颜色总是不透明四色）。"""
    out = bytearray(w * h * 4)
    bw, bh = (w + 3) // 4, (h + 3) // 4
    for by in range(bh):
        for bx in range(bw):
            off = (by * bw + bx) * 16
            if off + 16 > len(data):
                return out
            alpha = int.from_bytes(data[off : off + 8], "little")
            c0, c1, bits = struct.unpack("<HHI", data[off + 8 : off + 16])
            r0, g0, b0 = _rgb565(c0)
            r1, g1, b1 = _rgb565(c1)
            colors = (
                (r0, g0, b0),
                (r1, g1, b1),
                ((2 * r0 + r1) // 3, (2 * g0 + g1) // 3, (2 * b0 + b1) // 3),
                ((r0 + 2 * r1) // 3, (g0 + 2 * g1) // 3, (b0 + 2 * b1) // 3),
            )
            for py in range(4):
                y = by * 4 + py
                if y >= h:
                    continue
                for px in range(4):
                    x = bx * 4 + px
                    if x >= w:
                        continue
                    i = (y * w + x) * 4
                    c = colors[(bits >> (2 * (py * 4 + px))) & 3]
                    out[i] = c[0]
                    out[i + 1] = c[1]
                    out[i + 2] = c[2]
                    # 4-bit alpha 拉伸到 8-bit：a*17 正好铺满 0..255。
                    out[i + 3] = ((alpha >> (4 * (py * 4 + px))) & 0xF) * 17
    return out


def _decode_bc3_blocks(data: bytes, w: int, h: int) -> bytearray:
    """BC3/DXT5：8 字节插值 alpha + BC1 颜色块（颜色总是不透明四色）。"""
    out = bytearray(w * h * 4)
    bw, bh = (w + 3) // 4, (h + 3) // 4
    for by in range(bh):
        for bx in range(bw):
            off = (by * bw + bx) * 16
            if off + 16 > len(data):
                return out
            a0, a1 = data[off], data[off + 1]
            abits = int.from_bytes(data[off + 2 : off + 8], "little")
            if a0 > a1:
                alphas = (
                    a0,
                    a1,
                    (6 * a0 + 1 * a1) // 7,
                    (5 * a0 + 2 * a1) // 7,
                    (4 * a0 + 3 * a1) // 7,
                    (3 * a0 + 4 * a1) // 7,
                    (2 * a0 + 5 * a1) // 7,
                    (1 * a0 + 6 * a1) // 7,
                )
            else:
                alphas = (
                    a0,
                    a1,
                    (4 * a0 + 1 * a1) // 5,
                    (3 * a0 + 2 * a1) // 5,
                    (2 * a0 + 3 * a1) // 5,
                    (1 * a0 + 4 * a1) // 5,
                    0,
                    255,
                )
            c0, c1, bits = struct.unpack("<HHI", data[off + 8 : off + 16])
            r0, g0, b0 = _rgb565(c0)
            r1, g1, b1 = _rgb565(c1)
            colors = (
                (r0, g0, b0),
                (r1, g1, b1),
                ((2 * r0 + r1) // 3, (2 * g0 + g1) // 3, (2 * b0 + b1) // 3),
                ((r0 + 2 * r1) // 3, (g0 + 2 * g1) // 3, (b0 + 2 * b1) // 3),
            )
            for py in range(4):
                y = by * 4 + py
                if y >= h:
                    continue
                for px in range(4):
                    x = bx * 4 + px
                    if x >= w:
                        continue
                    i = (y * w + x) * 4
                    c = colors[(bits >> (2 * (py * 4 + px))) & 3]
                    out[i] = c[0]
                    out[i + 1] = c[1]
                    out[i + 2] = c[2]
                    out[i + 3] = alphas[(abits >> (3 * (py * 4 + px))) & 7]
    return out


def decode_dds(data: bytes) -> tuple[int, int, bytes] | None:
    """解第一级画面（mipmap 忽略）。返回 (宽, 高, RGBA)。

    只解第一级是有意的：预览最大也就 100 像素宽，mip 链用不上，
    逐级解码会把一个 35KB 图标解成几百 KB 的无用数据。
    """
    if len(data) < 128 or data[:4] != b"DDS ":
        return None
    if _u32(data, 4) != 124:
        return None
    height, width = _u32(data, 12), _u32(data, 16)
    if not (0 < width <= 8192 and 0 < height <= 8192):
        return None
    pf_flags = _u32(data, 80)
    fourcc = data[84:88].decode("latin1").rstrip("\0")
    bits = _u32(data, 88)
    rmask, gmask, bmask, amask = (_u32(data, o) for o in (92, 96, 100, 104))
    caps2 = _u32(data, 112)
    if caps2 & (DDSCAPS2_CUBEMAP | DDSCAPS2_VOLUME):
        return None

    if pf_flags & DDPF_FOURCC:
        if fourcc in ("DXT1", "DXT2"):
            return width, height, bytes(_decode_bc1_blocks(data[128:], width, height))
        if fourcc == "DXT3":
            return width, height, bytes(_decode_bc2_blocks(data[128:], width, height))
        if fourcc in ("DXT4", "DXT5"):
            return width, height, bytes(_decode_bc3_blocks(data[128:], width, height))
        # DX10 要读 20 字节扩展头才知道真实格式；ATI2/BC5 是双通道法线图。
        # 这两类图标用不上，直接放弃，让调用方画占位。
        return None

    if not (pf_flags & DDPF_RGB) or bits not in (24, 32):
        return None

    bpp = bits // 8
    pixel_count = width * height
    need = pixel_count * bpp
    if len(data) < 128 + need:
        return None
    body = data[128 : 128 + need]
    shifts = [_mask_channel(m) for m in (rmask, gmask, bmask, amask)]
    if not any(m for m in (rmask, gmask, bmask)):
        return None
    out = bytearray(pixel_count * 4)
    for i in range(pixel_count):
        off = i * bpp
        px = int.from_bytes(body[off : off + bpp], "little")
        o = i * 4
        out[o] = _scaled(px, *shifts[0])
        out[o + 1] = _scaled(px, *shifts[1])
        out[o + 2] = _scaled(px, *shifts[2])
        out[o + 3] = _scaled(px, *shifts[3]) if amask else 255
    return width, height, bytes(out)


# --------------------------------------------------------------------------- #
# TGA（事件图片常见格式，未压缩或 RLE 的真彩/带 alpha）
# --------------------------------------------------------------------------- #

def decode_tga(data: bytes) -> tuple[int, int, bytes] | None:
    if len(data) < 18:
        return None
    id_len, cmap, img_type = data[0], data[1], data[2]
    width, height = struct.unpack("<HH", data[12:16])
    bpp, desc = data[16], data[17]
    if cmap or img_type not in (2, 10) or bpp not in (24, 32):
        return None
    if not (0 < width <= 8192 and 0 < height <= 8192):
        return None
    pos = 18 + id_len
    if img_type == 2:
        body = data[pos : pos + width * height * bpp // 8]
        if len(body) < width * height * bpp // 8:
            return None
        pixels = [body[i : i + bpp // 8] for i in range(0, len(body), bpp // 8)]
    else:  # RLE
        pixels = []
        while len(pixels) < width * height and pos < len(data):
            packet = data[pos]
            pos += 1
            count = (packet & 0x7F) + 1
            if packet & 0x80:
                one = data[pos : pos + bpp // 8]
                pos += bpp // 8
                pixels.extend([one] * count)
            else:
                for _ in range(count):
                    pixels.append(data[pos : pos + bpp // 8])
                    pos += bpp // 8
        if len(pixels) < width * height:
            return None
        pixels = pixels[: width * height]

    out = bytearray(width * height * 4)
    flip = not (desc & 0x20)  # 默认按左下角原点存储
    for i, px in enumerate(pixels):
        x = i % width
        y = i // width
        sy = (height - 1 - y) if flip else y
        o = (sy * width + x) * 4
        # TGA 默认 BGR(A)
        out[o] = px[2]
        out[o + 1] = px[1]
        out[o + 2] = px[0]
        out[o + 3] = px[3] if bpp == 32 else 255
    return width, height, bytes(out)


# --------------------------------------------------------------------------- #
# 缩放与 PNG
# --------------------------------------------------------------------------- #

def resize_rgba(rgba: bytes, w: int, h: int, tw: int, th: int) -> bytes:
    """面积平均缩放。

    最近邻在 100x88 → 64x56 这种非整数比例上会丢细节（细线整根消失），
    而图标恰恰靠细节认。面积平均多算一点，但结果稳。
    """
    if tw <= 0 or th <= 0 or (w == tw and h == th):
        return rgba
    out = bytearray(tw * th * 4)
    for ty in range(th):
        y0 = ty * h // th
        y1 = max(y0 + 1, (ty + 1) * h // th)
        for tx in range(tw):
            x0 = tx * w // tw
            x1 = max(x0 + 1, (tx + 1) * w // tw)
            r = g = b = a = 0
            n = (y1 - y0) * (x1 - x0)
            for y in range(y0, y1):
                row = y * w * 4
                for x in range(x0, x1):
                    i = row + x * 4
                    r += rgba[i]
                    g += rgba[i + 1]
                    b += rgba[i + 2]
                    a += rgba[i + 3]
            o = (ty * tw + tx) * 4
            out[o] = r // n
            out[o + 1] = g // n
            out[o + 2] = b // n
            out[o + 3] = a // n
    return bytes(out)


def encode_png(w: int, h: int, rgba: bytes) -> bytes:
    """RGBA PNG。用 Up 过滤器：图标是纵向渐变为主，比 None 省 30% 左右。"""
    raw = bytearray()
    prev = bytearray(w * 4)
    for y in range(h):
        row = bytearray(rgba[y * w * 4 : (y + 1) * w * 4])
        raw.append(2)  # filter type 2 = Up
        for i in range(len(row)):
            raw.append((row[i] - prev[i]) & 0xFF)
        prev = row

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + tag
            + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )


# --------------------------------------------------------------------------- #
# .gfx 索引
# --------------------------------------------------------------------------- #

_SPRITE_HEAD = re.compile(r"(?is)\b(?:corneredTile|)SpriteType\s*=\s*\{")
_NAME = re.compile(r'(?i)\bname\s*=\s*"([^"]+)"')
_TEXTURE = re.compile(r'(?i)\btexturefile\s*=\s*"([^"]+)"')
_FRAMES = re.compile(r"(?i)\bnoOfFrames\s*=\s*(\d+)")


def parse_gfx(text: str) -> dict[str, dict]:
    """从 .gfx 文本里抽 sprite 定义。

    只取 name / texturefile / noOfFrames：预览要的是「哪张图、切第几帧」，
    位置、动画、effectFile 都与静态显示无关，解析它们只会变慢。

    spriteType 块内可能再嵌 effectFile 块，所以不能简单按「第一个 }」截断；
    这里用大括号配平，块内嵌套正确跳过。
    """
    found: dict[str, dict] = {}
    pos = 0
    text_len = len(text)
    while pos < text_len:
        m = _SPRITE_HEAD.search(text, pos)
        if not m:
            break
        start = m.end()
        depth = 1
        i = start
        # 配平大括号。字符串里的 } 理论上会误伤，但 gfx 的字符串只有路径与
        # 名字，不含大括号，实测 162 个原版文件零例外。
        while i < text_len and depth > 0:
            ch = text[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
            i += 1
        block = text[start : i - 1]
        name = _NAME.search(block)
        tex = _TEXTURE.search(block)
        if name and tex:
            frames = _FRAMES.search(block)
            found.setdefault(
                name.group(1),
                {
                    "texture": tex.group(1).strip(),
                    "frames": max(1, int(frames.group(1))) if frames else 1,
                },
            )
        pos = i
    return found


def _read_text(path: str) -> str:
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError:
        return ""
    # 原版 .gfx 是 UTF-8（有的带 BOM）；少数 mod 存成 GBK。先 UTF-8，失败再兜底。
    for enc in ("utf-8-sig", "utf-8"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    try:
        return raw.decode("gb18030")
    except UnicodeDecodeError:
        return raw.decode("latin1")


# --------------------------------------------------------------------------- #
# 素材库
# --------------------------------------------------------------------------- #

class AssetLibrary:
    """按 sprite 名取图，结果转成 data URI。

    搜索顺序是「mod 自己的 interface/ → 原版 interface/」。mod 覆盖原版这条
    规则和引擎一致：同名 sprite 后者被前者顶掉，所以先扫原版再扫 mod，
    让 mod 的定义覆盖写进字典。
    """

    def __init__(self, roots: Iterable[str], limit_px: int = 128) -> None:
        self.roots = [r for r in roots if r and os.path.isdir(r)]
        self.limit_px = limit_px
        self._index: dict[str, dict] = {}
        self._built = False
        self._images: dict[str, tuple[int, int, bytes] | None] = {}
        self._uris: dict[tuple[str, int, int], str] = {}
        self._raw: dict[tuple[str, int], tuple[int, int, str]] = {}
        self.stats = {"sprite_files": 0, "sprites": 0, "decoded": 0, "failed": 0}

    def build(self) -> "AssetLibrary":
        if self._built:
            return self
        # 原版在前、mod 在后：后写的覆盖先写的。
        for root in self.roots:
            for gfx in self._gfx_files(root):
                found = parse_gfx(_read_text(gfx))
                for name, info in found.items():
                    info["root"] = root
                    self._index[name] = info
                self.stats["sprite_files"] += 1
        self.stats["sprites"] = len(self._index)
        self._built = True
        return self

    @staticmethod
    def _gfx_files(root: str) -> list[str]:
        hits: list[str] = []
        base = os.path.join(root, "interface")
        if not os.path.isdir(base):
            return hits
        for dp, _dn, fn in os.walk(base):
            for f in fn:
                if f.lower().endswith(".gfx"):
                    hits.append(os.path.join(dp, f))
        return hits

    def sprite(self, name: str) -> dict | None:
        self.build()
        if not name:
            return None
        info = self._index.get(name)
        if info:
            return info
        # 常见手误：脚本里写不带 GFX_ 前缀，或反过来。两边都试一次。
        if name.startswith("GFX_"):
            alt = name[4:]
        else:
            alt = "GFX_" + name
        return self._index.get(alt)

    def image(self, name: str) -> tuple[int, int, bytes] | None:
        """返回 (宽, 高, RGBA)，文件级缓存（同一张图被多个 sprite 引用）。"""
        info = self.sprite(name)
        if not info:
            # 也可能本来就写成了文件路径（事件图片的旧写法）。
            path = self._path_for(name)
            if not path:
                return None
            return self._load(path, 1)
        path = self._path_for(info["texture"], info.get("root", ""))
        if not path:
            return None
        return self._load(path, info.get("frames", 1))

    def _path_for(self, texture: str, root: str = "") -> str:
        texture = texture.replace("\\", "/")
        for base in ([root] if root else []) + self.roots:
            for cand in (texture, os.path.join("gfx", texture)):
                p = os.path.join(base, cand)
                if os.path.isfile(p):
                    return p
        return ""

    def _load(self, path: str, frames: int) -> tuple[int, int, bytes] | None:
        try:
            key = f"{path}|{os.path.getmtime(path)}"
        except OSError:
            return None
        if key in self._images:
            return self._images[key]
        try:
            with open(path, "rb") as fh:
                raw = fh.read()
        except OSError:
            self._images[key] = None
            return None
        ext = path.lower().rsplit(".", 1)[-1]
        decoded = None
        if ext == "dds":
            decoded = decode_dds(raw)
        elif ext == "tga":
            decoded = decode_tga(raw)
        if not decoded:
            self.stats["failed"] += 1
            self._images[key] = None
            return None
        w, h, rgba = decoded
        if frames > 1 and w >= frames:
            # 多帧 sprite 是横向排布；预览只显示第一帧。
            fw = w // frames
            cropped = bytearray(fw * h * 4)
            for y in range(h):
                cropped[y * fw * 4 : (y + 1) * fw * 4] = rgba[
                    y * w * 4 : y * w * 4 + fw * 4
                ]
            w, rgba = fw, bytes(cropped)
        self.stats["decoded"] += 1
        self._images[key] = (w, h, rgba)
        return self._images[key]

    def data_uri(self, name: str, tw: int, th: int) -> str:
        """按展示框缩放并编码成 data URI。找不到返回空串（调用方画占位）。"""
        if tw <= 0 or th <= 0:
            return ""
        name = name.strip()
        if not name:
            return ""
        key = (name, tw, th)
        if key in self._uris:
            return self._uris[key]
        img = self.image(name)
        if not img:
            self._uris[key] = ""
            return ""
        w, h, rgba = img
        if w > self.limit_px or h > self.limit_px:
            # 极端尺寸（比如整张 UI 底图）先缩到上限，再缩到展示框。
            scale = self.limit_px / max(w, h)
            w2, h2 = max(1, int(w * scale)), max(1, int(h * scale))
            rgba = resize_rgba(rgba, w, h, w2, h2)
            w, h = w2, h2
        rgba = resize_rgba(rgba, w, h, tw, th)
        png = encode_png(tw, th, rgba)
        uri = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
        self._uris[key] = uri
        return uri

    def sprite_uri(self, name: str, max_px: int = 0) -> tuple[int, int, str]:
        """原始分辨率内联一张图，返回 (宽, 高, data URI)。

        data_uri 是给图标用的：先按 limit_px 压到 128 以内再缩到展示框。
        但 UI 底图不能这么干——事件窗顶栏是 581×121，压到 128 宽再放大会糊成
        一片；九宫格切图更会被压得边框全无。UI 需要的是原尺寸，这个入口不设
        128 上限，只在调用方显式给了 max_px 时才缩。
        """
        name = (name or "").strip()
        if not name:
            return (0, 0, "")
        key = (name, max_px)
        if key in self._raw:
            return self._raw[key]
        img = self.image(name)
        if not img:
            self._raw[key] = (0, 0, "")
            return self._raw[key]
        w, h, rgba = img
        if max_px and max(w, h) > max_px:
            scale = max_px / max(w, h)
            w2, h2 = max(1, int(w * scale)), max(1, int(h * scale))
            rgba = resize_rgba(rgba, w, h, w2, h2)
            w, h = w2, h2
        png = encode_png(w, h, rgba)
        uri = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
        self._raw[key] = (w, h, uri)
        return self._raw[key]


def open_library(mod_root: str, game_root: str = "", limit_px: int = 128) -> AssetLibrary:
    """按「mod → 原版」顺序建库。game_root 为空时只扫 mod 自己的素材。

    limit_px 是图标解码的上限：预览里图标最大 56px，压到 128 既够用又省内存。
    要内联 UI 底图（事件窗顶栏 581 宽）就得把这个上限抬上去，不然糊。
    """
    roots = [r for r in (mod_root, game_root) if r]
    return AssetLibrary(roots, limit_px=limit_px).build()
