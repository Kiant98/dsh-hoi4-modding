"""Static HTML preview of a mod, no game process involved.

Renders focus trees with real coordinates and prerequisite edges, plus cards for
events / decisions / ideas with localisation already resolved. When a local game
install is available the real DDS icons and event pictures are decoded and
inlined, so the preview looks like the thing the player will actually see.

The output is one self-contained file: no CDN, no JS framework, no side files.
"""

from __future__ import annotations

import hashlib
import html
import os
import time
from typing import Any

import gui

COL_W = 208
ROW_H = 116
NODE_W = 176
NODE_H = 96
PAD = 48

# 贴图在卡片里的展示尺寸。icon 走 CSS background-image，尺寸由元素类控制。
ICON_SIZE = {"focus": (56, 49), "decision": (36, 36), "idea": (36, 36)}
EVENT_COVER = (209, 176)   # 事件窗底栏图位（原版 gui 里的 event_picture）
IMAGE_BUDGET = 1_200_000  # data URI 累计字符数上限（约 1.2MB 的 base64）
EVENT_COVER_QUOTA = 10    # 事件大图最贵，单独限张数
# 事件窗底图是整张 UI（顶栏 581×121、底栏 581×206），不可能压到图标那么大。
# 它们按原尺寸内联、所有事件共用一套，所以单独给个上限，免得把图标挤掉。
UI_BUDGET = 900_000

SEV_COLOR = {"error": "#c0392b", "warn": "#b8860b", "info": "#2c6fa8"}


def _esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _loc(loc: dict, key: str, fallback: str = "") -> str:
    if key in loc:
        return loc[key]
    return fallback or key


def _sprite_names(item: dict, first: str = "", prefixes: tuple = ()) -> list[str]:
    """一个定义引用贴图的所有候选名字：标量字段在前，pictures 里的一串在后。

    HOI4 的写法分两种：国策/事件直接写 sprite 名（GFX_focus_x），理念和决议
    却只写裸名（picture = generic_navy_bonus / icon = generic_tank），由游戏
    自己套上 GFX_idea_ / GFX_decision_ 前缀。照着字段原样找会 280 个图标全
    空——预览要判断「图标接错没」，就得跟游戏一样先补前缀。
    """
    names: list[str] = []
    head = item.get(first) if first else None
    if head:
        names.append(str(head))
    for name in item.get("pictures") or []:
        if name and str(name) not in names:
            names.append(str(name))
    if not prefixes:
        return names
    out: list[str] = []
    for name in names:
        if not name.startswith("GFX_"):
            for prefix in prefixes:
                cand = "GFX_%s_%s" % (prefix, name)
                if cand not in out:
                    out.append(cand)
        if name not in out:
            out.append(name)
    return out


# --------------------------------------------------------------------------- #
# 贴图内联
# --------------------------------------------------------------------------- #

class _Sprites:
    """把游戏贴图收集成 CSS 类，同一张图在页面里只内联一次。

    HOI4 的图标是 DDS，浏览器不认，必须先解码成 PNG 再转 data URI。国策树里
    十来个节点常常共用一个通用图标，按 sprite 名去重能把产物体积砍掉一大截。
    """

    def __init__(self, assets=None, budget: int = IMAGE_BUDGET,
                 cover_quota: int = EVENT_COVER_QUOTA) -> None:
        self.assets = assets
        self.budget = budget
        self.cover_quota = cover_quota
        self.rules: list[str] = []
        self.seen: dict[tuple, str] = {}
        self.used = 0        # 已内联的 data URI 字符数
        self.hits = 0        # 成功出图的数量
        self.covers = 0
        self.misses = 0      # 引用了贴图但游戏目录里找不到
        self.skipped = 0     # 有图但预算/配额用完了

    @property
    def enabled(self) -> bool:
        return bool(self.assets) and self.budget > 0

    def _ref(self, names: list[str], w: int, h: int, cover: bool) -> str:
        if not self.enabled:
            return ""
        for name in names:
            if not name or name in {"-", "none", "null"}:
                continue
            key = (name, w, h, cover)
            if key in self.seen:
                return self.seen[key]
            if self.used >= self.budget:
                self.skipped += 1
                return ""
            try:
                uri = self.assets.data_uri(name, w, h)
            except Exception:
                uri = ""
            if not uri:
                continue
            cls = "sp" + hashlib.md5(
                ("%s|%d|%d|%d" % (name, w, h, int(cover))).encode("utf-8")
            ).hexdigest()[:10]
            self.seen[key] = cls
            self.rules.append('.%s{background-image:url("%s")}' % (cls, uri))
            self.used += len(uri)
            self.hits += 1
            return cls
        self.misses += 1
        return ""

    def native(self, names: list[str], w: int, h: int, max_px: int = 0) -> str:
        """UI 底图：按原尺寸内联。

        图标那条路会把图先压到 128px 再缩到展示框——对 56px 的国策图标没问题，
        对 581 宽的窗框就是灾难。这里不走 data_uri，直接要原始分辨率。
        """
        if not self.enabled:
            return ""
        for name in names:
            if not name or name in {"-", "none", "null"}:
                continue
            key = ("ui", name, w, h, max_px)
            if key in self.seen:
                return self.seen[key]
            if self.used >= self.budget:
                self.skipped += 1
                return ""
            uri = ""
            try:
                fn = getattr(self.assets, "sprite_uri", None)
                if callable(fn):
                    _cw, _ch, uri = fn(name, max_px)
                else:
                    # 测试里的假素材库只有 data_uri，退回按展示框取图。
                    uri = self.assets.data_uri(name, w, h)
            except Exception:
                uri = ""
            if not uri:
                continue
            cls = "sp" + hashlib.md5(
                ("%s|ui|%d|%d" % (name, w, h)).encode("utf-8")
            ).hexdigest()[:10]
            self.seen[key] = cls
            self.rules.append('.%s{background-image:url("%s")}' % (cls, uri))
            self.used += len(uri)
            self.hits += 1
            return cls
        self.misses += 1
        return ""

    def icon(self, names: list[str], size: tuple[int, int]) -> str:
        return self._ref(names, size[0], size[1], False)

    def cover(self, names: list[str]) -> str:
        if not self.enabled or not names:
            return ""
        if self.covers >= self.cover_quota:
            self.skipped += 1
            return ""
        cls = self._ref(names, EVENT_COVER[0], EVENT_COVER[1], True)
        if cls:
            self.covers += 1
        return cls

    def css(self) -> str:
        return "".join(self.rules)


# --------------------------------------------------------------------------- #
# Focus trees
# --------------------------------------------------------------------------- #

def resolve_positions(focuses: list[dict]) -> dict[str, tuple[int, int]]:
    """把每个国策的 (x, y) 还原成绝对格子坐标。

    这里的关键是 relative_position_id：它的意思是「我的 x/y 是相对某个锚点的偏移」，
    不是绝对坐标。原版 10625 个国策里有 10984 处用它（103%，超过 100% 是有跨文件
    引用别国国策当锚点的情况），德国、日本这些大树的覆盖率是 100%。

    只读 x/y 直接画会怎样：整棵树的节点仍然各自「有位置」，但行列关系全乱——
    因为一个 x=6 的节点可能是「绝对第 6 列」，也可能是「锚点右边 6 格」，
    两者差着整个锚点的偏移量。表现出来就是节点重叠、连线横穿。

    递归解算，带环检测：mod 里 anchor 互相引用（A 相对 B、B 相对 A）是常见手误，
    不设防会无限递归直接爆栈。
    """
    raw: dict[str, dict] = {}
    for f in focuses:
        fid = f.get("id")
        if fid:
            raw[fid] = f

    memo: dict[str, tuple[int, int]] = {}

    def resolve(fid: str, trail: frozenset[str]) -> tuple[int, int]:
        if fid in memo:
            return memo[fid]
        f = raw.get(fid)
        if f is None:
            return (0, 0)
        x, y = _int(f.get("x")), _int(f.get("y"))
        anchor = f.get("rel") or ""
        # 自引用 / 环：就地当绝对坐标处理，不递归。
        if anchor and anchor != fid and anchor not in trail:
            ax, ay = resolve(anchor, trail | {fid})
            x, y = ax + x, ay + y
        memo[fid] = (x, y)
        return (x, y)

    return {fid: resolve(fid, frozenset()) for fid in raw}


def _render_focus(focuses: list[dict], loc: dict, sprites: _Sprites) -> str:
    usable = [f for f in focuses if f.get("id") and not f.get("shared")]
    if not usable:
        return '<p class="empty">没有国策定义。用 <code>kiant_hoi4_scaffold</code> kind=focus 生成一个。</p>'

    # 解算必须用**全集**（含 shared_focus）：shared_focus 就是给整棵树当公共
    # 锚点设计的（原版大树的主流用法）。之前在这里先过滤再解算，锚定到
    # shared 的国策查不到锚点、全部按 (0,0) 起算，一整片节点挤在画布左上角。
    # 渲染时才把 shared 排除（它自己不画）。
    placed = resolve_positions(focuses)
    xs = [p[0] for p in placed.values()]
    ys = [p[1] for p in placed.values()]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    width = PAD * 2 + (max_x - min_x) * COL_W + NODE_W
    height = PAD * 2 + (max_y - min_y) * ROW_H + NODE_H

    pos: dict[str, tuple[int, int]] = {}
    for fid, (gx, gy) in placed.items():
        px = PAD + (gx - min_x) * COL_W
        py = PAD + (gy - min_y) * ROW_H
        pos[fid] = (px, py)

    edges: list[str] = []
    for f in usable:
        for prereq in f.get("prereq") or []:
            if prereq not in pos:
                continue
            x1, y1 = pos[prereq]
            x2, y2 = pos[f["id"]]
            ax, ay = x1 + NODE_W // 2, y1 + NODE_H
            bx, by = x2 + NODE_W // 2, y2
            mid = (ay + by) // 2
            edges.append(
                f'<path d="M{ax},{ay} C{ax},{mid} {bx},{mid} {bx},{by}" '
                f'fill="none" stroke="#8a6a3a" stroke-width="2"/>'
            )

    nodes: list[str] = []
    for f in usable:
        x, y = pos[f["id"]]
        title = _loc(loc, f["id"], f["id"])
        desc = loc.get(f"{f['id']}_desc", "")
        missing = f["id"] not in loc
        cls = "node missing" if missing else "node"
        icon = sprites.icon(_sprite_names(f, "extra"), ICON_SIZE["focus"])
        nodes.append(
            f'<div class="{cls}" style="left:{x}px;top:{y}px" title="{_esc(desc[:200])}">'
            f'<span class="nid">{_esc(f["id"])}</span>'
            f'<div class="nicon {icon}"></div>'
            f'<div class="ntitle">{_esc(title)}</div>'
            f"</div>"
        )

    legend = (
        '<div class="legend">'
        f'<span><i class="sw" style="background:#8a6a3a"></i>国策 {len(usable)} 个</span>'
        f'<span><i class="sw" style="background:#8c3a30"></i>缺本地化 '
        f'{sum(1 for f in usable if f["id"] not in loc)} 个</span>'
        '<span class="dim">坐标按 x/y 等比还原，缩放比例非游戏内原尺寸</span>'
        "</div>"
    )

    return (
        legend
        + f'<div class="tree" style="width:{width}px;height:{height}px">'
        + f'<svg class="edges" width="{width}" height="{height}">' + "".join(edges) + "</svg>"
        + "".join(nodes)
        + "</div>"
    )


# --------------------------------------------------------------------------- #
# Cards
# --------------------------------------------------------------------------- #

def _event_css(geo: dict) -> str:
    """把 .gui 读到的几何写成一条条 CSS，所有事件窗共用。"""
    w = geo["width"]
    top = geo["top"]["height"]
    mid = geo["mid"]["height"]
    bot = geo["bottom"]["height"]
    ti, de = geo["title"], geo["desc"]
    pi, cl, op = geo["picture"], geo["clip"], geo["options"]
    slot_w, slot_h = op["slot"]
    tile_h = (geo["mid"].get("tile") or (w, 66))[1]
    return (
        f".ewin{{width:{w}px}}"
        f".ewtop{{height:{top}px;background-size:{w}px {top}px}}"
        f".ewtitle{{left:{ti['x']}px;top:{ti['y']}px;width:{ti['w']}px;"
        f"height:{ti['h']}px;line-height:{ti['h']}px;"
        f"text-align:{_ALIGN.get(ti.get('align', ''), 'center')}}}"
        # 中段是可伸缩的：描述长了往下长，纸张纹理跟着平铺。
        f".ewmid{{min-height:{mid}px;padding:{de['y'] + 8}px "
        f"{w - de['x'] - de['w']}px 14px {de['x']}px;"
        f"background-size:{w}px {tile_h}px}}"
        f".ewbot{{height:{bot}px;background-size:{w}px {bot}px}}"
        f".ewpic{{left:{pi['x']}px;top:{pi['y']}px;width:{pi['w']}px;"
        f"height:{pi['h']}px}}"
        f".ewclip{{left:{cl['x']}px;top:{cl['y']}px}}"
        f".ewopts{{left:{op['x']}px;top:{op['y']}px;width:{op['w']}px}}"
        f".ewopt{{width:{slot_w}px;height:{slot_h}px}}"
    )


_ALIGN = {"centre": "center", "center": "center", "left": "left",
          "right": "right", "justified": "justify"}


def _render_events(events: list[dict], loc: dict, sprites: _Sprites,
                   geo: dict | None = None) -> str:
    """按游戏的事件窗版式渲染：顶栏 + 中段描述 + 底栏（图片 / 选项）。

    这不是「凑得像」：几何来自 interface/eventwindow.gui，贴图是原版的
    DDS，摆位和游戏里一致——所以图标接错、描述溢出、选项挤成一团，一眼
    就能看出来。
    """
    if not events:
        return '<p class="empty">没有事件。</p>'
    geo = geo or gui.event_layout()
    w = geo["width"]
    top_h = geo["top"]["height"]
    bot_h = geo["bottom"]["height"]
    mid_tile = (geo["mid"].get("tile") or (w, 66))[1]
    slot_w, slot_h = geo["options"]["slot"]

    top_cls = sprites.native([geo["top"]["bg"]], w, top_h)
    mid_cls = sprites.native([geo["mid"]["bg"]], w, mid_tile)
    bot_cls = sprites.native([geo["bottom"]["bg"]], w, bot_h)
    opt_cls = sprites.native([geo["options"]["bg"]], slot_w, slot_h)
    clip_cls = sprites.native([geo["clip"]["sprite"]], 55, 30)

    cards: list[str] = []
    for ev in events:
        eid = ev.get("id", "")
        title = _loc(loc, ev.get("title") or f"{eid}.t", eid)
        desc = _loc(loc, ev.get("desc") or f"{eid}.d", "")
        opts = ev.get("options") or []
        if opts:
            opt_html = "".join(
                f'<div class="ewopt {opt_cls}">{_esc(_loc(loc, o, o))}</div>'
                for o in opts
            )
        else:
            opt_html = ('<div class="ewopt dimopt">无显式选项'
                        '（回退到 id.a / id.b）</div>')
        pic_cls = sprites.cover(_sprite_names(ev, "extra"))
        pic_html = (f'<div class="ewpic {pic_cls}"></div>' if pic_cls
                    else '<div class="ewpic nop"><span>无配图</span></div>')
        cards.append(
            '<figure class="ewcard">'
            '<article class="ewin">'
            f'<div class="ewtop {top_cls}">'
            f'<div class="ewtitle">{_esc(title)}</div>'
            "</div>"
            f'<div class="ewmid {mid_cls}">'
            f'<div class="ewdesc">{_esc(desc[:420])}</div>'
            "</div>"
            f'<div class="ewbot {bot_cls}">'
            + pic_html
            + (f'<div class="ewclip {clip_cls}"></div>' if clip_cls else "")
            + f'<div class="ewopts">{opt_html}</div>'
            "</div>"
            "</article>"
            f'<figcaption class="ewfoot">{_esc(eid)} · '
            f'{_esc(ev.get("file", ""))}:{_esc(ev.get("line", ""))}</figcaption>'
            "</figure>"
        )
    return '<div class="evcards">' + "".join(cards) + "</div>"


def _render_decisions(decisions: list[dict], categories: list[dict], loc: dict,
                      sprites: _Sprites) -> str:
    if not decisions:
        return '<p class="empty">没有决议。</p>'
    by_cat: dict[str, list[dict]] = {}
    for dec in decisions:
        by_cat.setdefault(dec.get("category", "未分类"), []).append(dec)
    out: list[str] = []
    for cat, items in by_cat.items():
        cat_title = _loc(loc, cat, cat)
        out.append(
            f'<section class="group"><h3>{_esc(cat_title)} <code>{_esc(cat)}</code></h3>'
            '<div class="cards">'
        )
        for dec in items:
            did = dec.get("id", "")
            icon = sprites.icon(_sprite_names(dec, "extra", ("decision",)), ICON_SIZE["decision"])
            out.append(
                '<article class="dec">'
                f'<div class="dico {icon}"></div>'
                '<div class="dbody">'
                f'<div class="dname">{_esc(_loc(loc, did, did))}</div>'
                f'<div class="ddesc">{_esc(loc.get(f"{did}_desc", "")[:300])}</div>'
                f'<div class="dfoot">{_esc(did)} · {_esc(dec.get("file", ""))}:{_esc(dec.get("line", ""))}</div>'
                "</div></article>"
            )
        out.append("</div></section>")
    return "".join(out)


def _render_ideas(ideas: list[dict], loc: dict, sprites: _Sprites) -> str:
    if not ideas:
        return '<p class="empty">没有国家精神。</p>'
    out = ['<div class="ideas">']
    for idea in ideas:
        iid = idea.get("id", "")
        icon = sprites.icon(_sprite_names(idea, "extra", ("idea",)), ICON_SIZE["idea"])
        slot = idea.get("slot", "")
        out.append(
            '<div class="idea">'
            f'<div class="iico {icon}"></div>'
            '<div class="ibody">'
            f'<div class="iname">{_esc(_loc(loc, iid, iid))}'
            + (f' <span class="islot">{_esc(slot)}</span>' if slot else "")
            + "</div>"
            f'<div class="idesc">{_esc(loc.get(f"{iid}_desc", "")[:160]) or "—"}</div>'
            f'<div class="dfoot">{_esc(iid)}</div>'
            "</div></div>"
        )
    out.append("</div>")
    return "".join(out)


def _render_defs_table(kind: str, items: list[dict]) -> str:
    if not items:
        return ""
    rows = "".join(
        f"<tr><td><code>{_esc(i.get('id', ''))}</code></td>"
        f"<td>{_esc(i.get('file', ''))}:{_esc(i.get('line', ''))}</td></tr>"
        for i in items
    )
    return (
        f"<details><summary>{_esc(kind)}（{len(items)}）</summary>"
        f'<table class="tbl"><tbody>{rows}</tbody></table></details>'
    )


def _render_issues(issues: list[dict]) -> str:
    if not issues:
        return '<p class="ok">没有发现结构性问题。</p>'
    out = ['<table class="tbl issues"><thead><tr><th>级别</th><th>位置</th><th>问题</th><th>建议</th></tr></thead><tbody>']
    for i in issues:
        sev = i.get("level", "info")
        where = i.get("file") or ""
        if i.get("line"):
            where += f":{i['line']}"
        out.append(
            "<tr>"
            f'<td><span class="sev" style="background:{SEV_COLOR.get(sev, "#666")}">{_esc(sev)}</span></td>'
            f'<td class="mono">{_esc(where or i.get("kind", ""))}</td>'
            f'<td>{_esc(i.get("message", ""))}</td>'
            f'<td class="dim">{_esc(i.get("hint", ""))}</td>'
            "</tr>"
        )
    out.append("</tbody></table>")
    return "".join(out)


def _render_coverage(defs: dict, loc: dict) -> str:
    rows: list[str] = []
    for kind, items in sorted(defs.items()):
        if not isinstance(items, list):
            continue
        need = 0
        have = 0
        for item in items:
            ident = item.get("id") or ""
            if not ident:
                continue
            keys = [ident]
            if kind in {"focus", "idea", "decision", "decision_category"}:
                keys.append(f"{ident}_desc")
            for key in keys:
                need += 1
                if key in loc:
                    have += 1
        pct = round(have / need * 100) if need else 100
        rows.append(
            f"<tr><td>{_esc(kind)}</td><td>{len(items)}</td>"
            f"<td>{have}/{need}</td>"
            f'<td><div class="bar"><span style="width:{pct}%"></span></div>{pct}%</td></tr>'
        )
    return (
        '<table class="tbl"><thead><tr><th>类型</th><th>数量</th><th>本地化覆盖</th><th></th></tr></thead><tbody>'
        + "".join(rows)
        + "</tbody></table>"
    )


# --------------------------------------------------------------------------- #
# Page shell
# --------------------------------------------------------------------------- #

CSS_BASE = """
:root{--bg:#14110f;--p1:#221e1b;--p2:#181412;--edge:#4a3b28;--edge2:#7a5c33;
      --gold:#e8c97a;--gold2:#f9e3a7;--txt:#d8d2c6;--txt2:#9a9286;--dim:#6f6a60}
*{box-sizing:border-box}
body{margin:0;font:14px/1.6 "Segoe UI","Microsoft YaHei",system-ui,sans-serif;
     color:var(--txt);background:var(--bg);
     background-image:radial-gradient(circle at 22% -10%,rgba(150,110,55,.14),transparent 55%)}
header.top{background:linear-gradient(180deg,#2c2621,#171412);
           border-bottom:2px solid var(--edge2);padding:22px 28px 18px}
header.top h1{margin:0 0 6px;font-size:22px;letter-spacing:.5px;color:var(--gold2);font-weight:600}
header.top .meta{color:var(--txt2);font-size:13px}
.wrap{padding:0 28px 60px;max-width:1320px}
nav{position:sticky;top:0;z-index:6;display:flex;flex-wrap:wrap;gap:6px;padding:12px 0 10px;
    background:var(--bg);border-bottom:1px solid var(--edge);margin-bottom:20px}
nav a{padding:6px 14px;border:1px solid var(--edge);border-radius:2px;color:var(--gold);
      text-decoration:none;font-size:13px;background:linear-gradient(180deg,#241f1b,#161312)}
nav a:hover{border-color:var(--edge2);color:var(--gold2)}
h2{font-size:15px;margin:30px 0 14px;padding:0 0 8px;border-bottom:1px solid var(--edge);
   color:var(--gold);letter-spacing:.6px;font-weight:600}
h2::before{content:"";display:inline-block;width:3px;height:13px;background:var(--edge2);
           margin-right:9px;vertical-align:-1px}
.cards{display:flex;flex-wrap:wrap;gap:14px}
/* 事件窗：顶栏 + 中段 + 底栏三块拼起来，几何与贴图都来自游戏本体。 */
.evcards{display:flex;flex-wrap:wrap;gap:26px;align-items:flex-start}
.ewcard{margin:0}
.ewin{position:relative;background:#17130f;border-radius:2px;overflow:hidden;
      box-shadow:0 8px 26px rgba(0,0,0,.55)}
.ewtop,.ewmid,.ewbot{position:relative;background-repeat:no-repeat;
                     background-position:left top;background-color:#d3c4a6}
.ewmid{background-repeat:repeat-y}
.ewtitle{position:absolute;color:#2c2114;font:600 21px/1 Georgia,"Times New Roman",serif;
         letter-spacing:.4px;text-shadow:0 1px 0 rgba(255,255,255,.28);overflow:hidden;
         white-space:nowrap;text-overflow:ellipsis}
.ewdesc{font:15px/1.5 Georgia,"Times New Roman",serif;color:#3a2c1a;
        max-height:236px;overflow:hidden}
.ewpic{position:absolute;background-size:cover;background-position:center;background-color:#1a1510}
.ewpic.nop{display:flex;align-items:center;justify-content:center;background-color:rgba(0,0,0,.05);
           border:1px dashed rgba(70,50,25,.35);color:rgba(70,50,25,.42);font-size:11px}
.ewclip{position:absolute;width:55px;height:30px;pointer-events:none}
.ewopts{position:absolute}
.ewopt{display:flex;align-items:center;justify-content:flex-start;padding:0 18px;overflow:hidden;
      background:linear-gradient(180deg,#6d4a1e,#4a3110);background-size:100% 100%;
      background-repeat:no-repeat;color:#e8d9ba;font:14px/1.2 Georgia,serif;
      text-shadow:0 1px 1px rgba(0,0,0,.65)}
.ewopt.dimopt{background:rgba(60,40,20,.10);color:#cbaf87;font:italic 12px Georgia,serif}
.ewfoot{font:10px ui-monospace,monospace;color:var(--dim);margin-top:7px}
.btn{font-size:12px;padding:5px 12px;background:linear-gradient(180deg,#7d4a16,#5a330c);
     border:1px solid #a06a24;border-radius:2px;color:#f3e2bd}
.dec{display:flex;gap:12px;width:330px;padding:12px;background:linear-gradient(180deg,#221e1a,#181413);
     border:1px solid var(--edge);border-radius:3px}
.dico{width:36px;height:36px;flex:0 0 36px;background-color:#1d1913;border:1px solid #3d3223;
      border-radius:2px;background-repeat:no-repeat;background-position:center}
.dbody{min-width:0}
.dname{font-size:14px;color:var(--gold2);margin-bottom:4px}
.ddesc{font-size:12px;color:var(--txt2);max-height:3.2em;overflow:hidden}
.dfoot{font:10px ui-monospace,monospace;color:var(--dim);margin-top:8px}
.ideas{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:12px}
.idea{display:flex;gap:12px;padding:12px;background:linear-gradient(180deg,#221e1a,#181413);
      border:1px solid var(--edge);border-radius:3px}
.iico{width:36px;height:36px;flex:0 0 36px;background-color:#1d1913;border:1px solid #3d3223;
      border-radius:2px;background-repeat:no-repeat;background-position:center}
.iname{font-size:14px;color:var(--gold2)}
.islot{font:10px ui-monospace,monospace;color:var(--dim);margin-left:6px}
.idesc{font-size:12px;color:var(--txt2);margin-top:3px}
.empty{color:var(--dim);font-style:italic}
.ok{color:#6fbf8b}
.dim{color:var(--dim);font-size:12px}
.tree{position:relative;margin:16px 0;background:#0e0c0a;
      background-image:radial-gradient(rgba(150,115,70,.10) 1px,transparent 1px);
      background-size:26px 26px;border:1px solid var(--edge);border-radius:3px;overflow:auto}
.edges{position:absolute;left:0;top:0;pointer-events:none}
.node{position:absolute;width:176px;height:96px;text-align:center;overflow:hidden;
      background:linear-gradient(180deg,#2a241d,#17130f);
      border:1px solid #524128;border-radius:3px;padding-top:5px}
.node::after{content:"";position:absolute;inset:0;pointer-events:none;
             border:1px solid rgba(249,227,167,.10);border-radius:3px}
.node.missing{border-color:#8c3a30;background:linear-gradient(180deg,#2e201d,#191211)}
.nid{position:absolute;left:5px;top:3px;z-index:2;max-width:125px;overflow:hidden;
     white-space:nowrap;text-overflow:ellipsis;font:9px ui-monospace,monospace;
     color:rgba(232,223,204,.5)}
.nicon{width:56px;height:49px;margin:0 auto;background-color:#1a1611;background-repeat:no-repeat;
       background-position:center;background-size:56px 49px;
       box-shadow:inset 0 0 0 1px rgba(150,115,70,.22)}
.ntitle{font-size:12px;line-height:15px;margin-top:3px;padding:0 7px;color:#e8dfcc;
        display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.legend{display:flex;gap:18px;align-items:center;flex-wrap:wrap;font-size:12px;
        color:var(--txt2);margin-top:10px}
.sw{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px;
    vertical-align:-1px}
.tbl{width:100%;border-collapse:collapse;background:#1b1613;border:1px solid var(--edge);
     border-radius:3px;overflow:hidden;font-size:13px}
.tbl th{background:#262019;text-align:left;padding:9px 12px;font-weight:600;color:var(--gold)}
.tbl td{padding:8px 12px;border-top:1px solid #291f19;vertical-align:top}
.tbl tr:hover td{background:#211b17}
.mono,.tbl code,code{font-family:ui-monospace,Consolas,monospace;font-size:12px}
code{background:#2a211a;color:var(--gold);padding:1px 5px;border-radius:2px}
.sev{color:#fff;padding:1px 7px;border-radius:2px;font-size:11px}
.bar{display:inline-block;width:70px;height:7px;background:#2d251d;border-radius:2px;
     vertical-align:middle;margin-right:8px;overflow:hidden}
.bar span{display:block;height:100%;background:linear-gradient(90deg,#7a5c33,#e8c97a)}
details{margin:8px 0}
summary{cursor:pointer;color:var(--edge2);font-size:13px;padding:4px 0}
.group{margin-bottom:18px}
.group h3{font-size:13px;color:var(--txt2);margin:14px 0 10px;font-weight:500}
"""


def render(
    mod_root: str,
    out_path: str,
    name: str,
    version: str,
    definitions: dict,
    loc: dict,
    issues: list[dict],
    stats: dict | None = None,
    assets=None,
    image_budget: int = IMAGE_BUDGET,
    game_root: str = "",
) -> dict[str, Any]:
    """assets 传 None 时全程不出图（离线、体积稳定），selftest 依赖这一点。"""
    started = time.time()
    sprites = _Sprites(assets, budget=image_budget)
    # 事件窗几何优先取 mod 自己覆盖的 interface/eventwindow.gui，其次原版；
    # 都没有就退回内置的原版数值——版式照样对，只是没有窗框贴图。
    geo = gui.event_layout(gui.windows_for(mod_root, game_root))

    sections = {
        "focus": _render_focus(definitions.get("focus", []), loc, sprites),
        "events": _render_events(definitions.get("event", []), loc, sprites, geo),
        "decisions": _render_decisions(
            definitions.get("decision", []),
            definitions.get("decision_category", []),
            loc,
            sprites,
        ),
        "ideas": _render_ideas(definitions.get("idea", []), loc, sprites),
        "coverage": _render_coverage(definitions, loc),
        "issues": _render_issues(issues),
    }

    extras = "".join(
        _render_defs_table(kind, items)
        for kind, items in sorted(definitions.items())
        if kind
        not in {"focus", "event", "decision", "decision_category", "idea"}
        and isinstance(items, list)
    )

    counts = {
        "error": sum(1 for i in issues if i.get("level") == "error"),
        "warn": sum(1 for i in issues if i.get("level") == "warn"),
    }

    image_note = ""
    if sprites.hits:
        image_note = f" · 贴图 {sprites.hits} 张"
        if sprites.skipped:
            image_note += f"（预算已满，跳过 {sprites.skipped}）"

    source = f"本机游戏目录 {_esc(game_root)}" if game_root else "游戏目录"

    doc = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(name)} · 离线预览</title>
<style>{CSS_BASE}
{sprites.css()}
{_event_css(geo)}</style></head><body>
<header class="top">
  <h1>{_esc(name)}</h1>
  <div class="meta">
    版本 {_esc(version)} · 生成于 {time.strftime("%Y-%m-%d %H:%M")} ·
    错误 <b style="color:#e05a4a">{counts["error"]}</b> ·
    警告 <b style="color:#d8a03a">{counts["warn"]}</b>
    {f" · 文件 {stats['files']}" if stats and stats.get("files") else ""}{image_note}
  </div>
</header>
<div class="wrap">
<nav>
  <a href="#focus">国策树</a>
  <a href="#events">事件</a>
  <a href="#decisions">决议</a>
  <a href="#ideas">国家精神</a>
  <a href="#coverage">本地化覆盖</a>
  <a href="#issues">问题清单</a>
  <a href="#more">其它定义</a>
</nav>

<h2 id="focus">国策树</h2>
{sections["focus"]}

<h2 id="events">事件</h2>
{sections["events"]}

<h2 id="decisions">决议</h2>
{sections["decisions"]}

<h2 id="ideas">国家精神</h2>
{sections["ideas"]}

<h2 id="coverage">本地化覆盖</h2>
{sections["coverage"]}

<h2 id="issues">问题清单</h2>
{sections["issues"]}

<h2 id="more">其它定义</h2>
{extras or '<p class="empty">无</p>'}

<p class="dim" style="margin-top:36px">
  静态快照，不反映运行时行为（AI、触发条件求值、平衡性）；界面外观与游戏内不完全一致。
  图标与事件图取自{source}，仅作本地预览，不随本文件分发。
</p>
</div></body></html>"""

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(doc)
    return {
        "ok": True,
        "path": out_path,
        "bytes": len(doc.encode("utf-8")),
        "sections": {k: (len(v) > 60) for k, v in sections.items()},
        "seconds": round(time.time() - started, 3),
        "assets": {
            "images": sprites.hits,
            "skipped": sprites.skipped,
            "missing": sprites.misses,
            "bytes": sprites.used,
        },
        "gui": {"source": geo["source"], "window": f'{geo["width"]}x{geo["height_total"]}'},
        "note": "双击打开即可，无需游戏与网络。",
    }
