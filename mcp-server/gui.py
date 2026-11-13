"""Clausewitz .gui 读取：把窗口树抽出来，让预览按游戏的真实几何摆控件。

为什么需要这个：HOI4 的事件窗不是「图片 + 文字」的自由排版，而是三块拼起来的——
顶栏 581×121（夹纸板 + 纸张）、可伸缩的中段（描述）、底栏 581×206（图片 + 选项）。
标题在 (14,70)、描述从 (31,0) 起宽 512、选项格子从 (215,-1) 起每格 300×47。
照着 .gui 摆，预览才能反映「这一屏和游戏里像不像」；自己拍脑袋的版式永远差一点，
而且游戏一改间距就彻底对不上。

这个模块只做读取，不写不改；解析失败或文件不在本机时退回内置的原版几何，不抛异常。
"""

from __future__ import annotations

import os
from typing import Any

import cw

WINDOW_KEYS = ("containerwindowtype", "windowtype")
ELEMENT_KINDS = {
    "icontype": "icon",
    "buttontype": "button",
    "guibuttontype": "button",
    "instanttextboxtype": "text",
    "textboxtype": "text",
    "gridboxtype": "grid",
}

EVENT_GUI = "interface/eventwindow.gui"

# 原版 1.19.4.2 的 interface/eventwindow.gui 实测结果。游戏目录不在本机时用它：
# 贴图拿不到（预览自动退回纯色），但版式仍然是游戏里的那一套。
EVENT_DEFAULT = {
    "width": 581,
    "top": {"height": 121, "bg": "GFX_event_report_top_win"},
    "mid": {"height": 100, "bg": "GFX_event_report_tileable_midsection",
            "tile": (580, 66)},
    "bottom": {"height": 206, "bg": "GFX_event_report_bottom_win"},
    "title": {"x": 14, "y": 70, "w": 551, "h": 32, "font": "hoi4_typewriter22",
              "align": "centre"},
    "desc": {"x": 31, "y": 0, "w": 512, "h": 230, "font": "hoi4_typewriter16"},
    "picture": {"x": 5, "y": 5, "w": 209, "h": 176},
    "clip": {"x": -3, "y": 35, "sprite": "GFX_event_pic_clip"},
    "options": {"x": 215, "y": -1, "w": 300, "h": 30,
                "slot": (300, 47), "max_h": 1,
                "bg": "GFX_event_option_entry"},
}


def _num(text: str, default: int = 0) -> int:
    text = (text or "").strip().rstrip("%")
    try:
        return int(float(text))
    except ValueError:
        return default


def _xy(node: Any) -> tuple[int, int]:
    out = {"x": 0, "y": 0}
    if isinstance(node, cw.Block):
        for s in cw.stmts(node):
            k = s.key.lower()
            if k in out:
                out[k] = _num(cw.as_text(s.value))
    return out["x"], out["y"]


def _wh(node: Any) -> tuple[int, int]:
    out = {"width": 0, "height": 0}
    if isinstance(node, cw.Block):
        for s in cw.stmts(node):
            k = s.key.lower()
            if k in out:
                out[k] = _num(cw.as_text(s.value))
    return out["width"], out["height"]


def _node(stmt: cw.Stmt, kind: str) -> dict:
    """一个控件：只留排版用得上的字段，其余忽略。"""
    node = {
        "kind": kind,
        "name": "",
        "pos": (0, 0),
        "size": (0, 0),
        "sprite": "",
        "bg": "",
        "font": "",
        "align": "",
        "text": "",
        "line": stmt.line,
        "children": [],
    }
    block = stmt.value if isinstance(stmt.value, cw.Block) else None
    if block is None:
        return node
    for s in cw.stmts(block):
        key = s.key.lower()
        if key == "name":
            node["name"] = cw.as_text(s.value).strip()
        elif key in ("spritetype", "quadtexturesprite"):
            if not node["sprite"]:
                node["sprite"] = cw.as_text(s.value).strip()
        elif key == "position":
            node["pos"] = _xy(s.value)
        elif key == "size":
            node["size"] = _wh(s.value)
        elif key == "slotsize":
            node["slot"] = _wh(s.value)
        elif key == "max_slots_horizontal":
            node["max_h"] = _num(cw.as_text(s.value), 1)
        elif key == "font":
            node["font"] = cw.as_text(s.value).strip()
        elif key == "format":
            node["align"] = cw.as_text(s.value).strip().lower()
        elif key == "text":
            node["text"] = cw.as_text(s.value)
        elif key == "background":
            # background 块没有 name，只有 spriteType；单独收一层。
            for bs in cw.stmts(s.value):
                bk = bs.key.lower()
                if bk in ("spritetype", "quadtexturesprite", "texturefile"):
                    node["bg"] = cw.as_text(bs.value).strip()
                    break
    for s in cw.stmts(block):
        k = s.key.lower()
        if k in WINDOW_KEYS:
            node["children"].append(_node(s, "container"))
        elif k in ELEMENT_KINDS:
            node["children"].append(_node(s, ELEMENT_KINDS[k]))
    return node


def parse(text: str) -> dict[str, dict]:
    """顶层窗口清单，键是小写窗口名（同名多份保留第一份）。"""
    root, _errors = cw.parse(text)
    out: dict[str, dict] = {}
    holders = [s.value for s in cw.stmts(root) if isinstance(s.value, cw.Block)]
    # guiTypes = { ... } 是标准写法；少数文件把窗口直接写在根上，一并收。
    queues: list[Any] = []
    for block in holders:
        kids = [s for s in cw.stmts(block) if s.key.lower() in WINDOW_KEYS]
        if kids:
            queues.append(block)
    if not queues:
        queues.append(root)
    for block in queues:
        for s in cw.stmts(block):
            if s.key.lower() not in WINDOW_KEYS:
                continue
            w = _node(s, "container")
            name = (w["name"] or "").lower()
            if name and name not in out:
                out[name] = w
    return out


def child(node: dict | None, name: str) -> dict | None:
    if not node:
        return None
    low = name.lower()
    for c in node.get("children") or []:
        if (c.get("name") or "").lower() == low:
            return c
    return None


def deep(node: dict | None, *names: str) -> dict | None:
    for name in names:
        node = child(node, name)
        if node is None:
            return None
    return node


def load(path: str) -> dict[str, dict]:
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as fh:
            return parse(fh.read())
    except OSError:
        return {}


def windows_for(mod_root: str, game_root: str = "", rel: str = EVENT_GUI) -> dict[str, dict]:
    """mod 覆盖原版这条规则同样适用于 .gui：先看 mod 自己的，再看原版。"""
    for base in (mod_root, game_root):
        if not base:
            continue
        path = os.path.join(base, rel)
        if os.path.isfile(path):
            got = load(path)
            if got:
                return got
    return {}


def _fill(node: dict | None, default: dict) -> dict:
    """把 .gui 里读到的几何盖到默认值上，缺的字段保留默认。"""
    out = dict(default)
    if node:
        (x, y) = node.get("pos", (0, 0))
        (w, h) = node.get("size", (0, 0))
        if x or y or default.get("x", 0) or default.get("y", 0):
            out["x"], out["y"] = x, y
        if w:
            out["w"] = w
        if h:
            out["h"] = h
        if node.get("font"):
            out["font"] = node["font"]
        if node.get("align"):
            out["align"] = node["align"]
        if node.get("sprite"):
            out["sprite"] = node["sprite"]
    return out


def event_layout(windows: dict[str, dict] | None = None, kind: str = "country") -> dict:
    """事件窗几何。kind=country 是弹给玩家的那张（新闻另有一套，暂不渲染）。"""
    out = {
        "width": EVENT_DEFAULT["width"],
        "top": dict(EVENT_DEFAULT["top"]),
        "mid": dict(EVENT_DEFAULT["mid"]),
        "bottom": dict(EVENT_DEFAULT["bottom"]),
        "title": dict(EVENT_DEFAULT["title"]),
        "desc": dict(EVENT_DEFAULT["desc"]),
        "picture": dict(EVENT_DEFAULT["picture"]),
        "clip": dict(EVENT_DEFAULT["clip"]),
        "options": dict(EVENT_DEFAULT["options"]),
        "source": "内置几何（原版 1.19）",
        "width_total": 581,
        "height_total": 427,
    }
    win = (windows or {}).get("eventwindow")
    if not win:
        return out
    out["source"] = "interface/eventwindow.gui"
    (w, h) = win.get("size", (0, 0))
    if w:
        out["width"] = out["width_total"] = w
    if h:
        out["height_total"] = h
    top = child(win, "top_Window")
    mid = child(win, "midsection")
    bot = child(win, "bottom_Window")
    for key, node in (("top", top), ("mid", mid), ("bottom", bot)):
        if not node:
            continue
        (bh, mh) = node.get("size", (0, 0))[1], None
        if bh:
            out[key]["height"] = bh
        if node.get("bg"):
            out[key]["bg"] = node["bg"]
    title = child(top, "Title")
    if title:
        (x, y) = title.get("pos", (0, 0))
        (mw, mh) = title.get("size", (0, 0))
        out["title"]["x"], out["title"]["y"] = x, y
        if title.get("font"):
            out["title"]["font"] = title["font"]
        if title.get("align"):
            out["title"]["align"] = title["align"]
    desc = child(mid, "Description")
    if desc:
        (x, y) = desc.get("pos", (0, 0))
        out["desc"]["x"], out["desc"]["y"] = x, y
        if desc.get("font"):
            out["desc"]["font"] = desc["font"]
    pic = child(bot, "event_picture")
    if pic:
        (x, y) = pic.get("pos", (0, 0))
        out["picture"]["x"], out["picture"]["y"] = x, y
    clip = child(bot, "event_pic_clip")
    if clip:
        (x, y) = clip.get("pos", (0, 0))
        out["clip"]["x"], out["clip"]["y"] = x, y
        if clip.get("sprite"):
            out["clip"]["sprite"] = clip["sprite"]
    grid = child(bot, "options_grid")
    if grid:
        (x, y) = grid.get("pos", (0, 0))
        out["options"]["x"], out["options"]["y"] = x, y
        (sw, sh) = grid.get("slot", (0, 0))
        if sw and sh:
            out["options"]["slot"] = (sw, sh)
        if grid.get("max_h"):
            out["options"]["max_h"] = grid["max_h"]
    # 选项按钮的尺寸与底图来自独立的 event_option_entry 窗口（原版里
    # 是一个 300×47 的 containerWindowType），不是 options_grid 自己写的。
    entry = (windows or {}).get("event_option_entry")
    if entry:
        (sw, sh) = entry.get("size", (0, 0))
        if sw and sh:
            out["options"]["slot"] = (sw, sh)
        if entry.get("bg"):
            out["options"]["bg"] = entry["bg"]
    return out