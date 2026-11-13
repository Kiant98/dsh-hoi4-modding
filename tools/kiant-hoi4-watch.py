#!/usr/bin/env python3
"""kiant-hoi4-watch —— 改盘即刷新的本地预览服务。

浏览器里是 kiant_hoi4_preview 的完整产物；你在编辑器里每存一次盘，它自己
重新渲染并刷新，不用回 MCP 重调工具、也不用手动重开页面。

用法：
  python tools/kiant-hoi4-watch.py examples/sample_mod
  python tools/kiant-hoi4-watch.py my_mod --port 8770 --open
  python tools/kiant-hoi4-watch.py my_mod --once --out .modkit/preview.html

不带 --game 时自动探测本机 HOI4；探测不到就退回「无贴图」模式，版面照样对，
只是没有窗框和图标。服务只监听 127.0.0.1，不对外网开放。
"""

import argparse
import json
import os
import sys
import tempfile
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "mcp-server"))

import assets  # noqa: E402
import checks  # noqa: E402
import cw  # noqa: E402
import preview  # noqa: E402

SKIP_DIRS = {".git", ".modkit", "__pycache__", ".pytest_cache", "node_modules"}
SKIP_EXT = (".pyc", ".log", ".sqlite", ".sqlite3", ".tmp")

STATE = {"sig": "", "html": "", "at": 0.0, "ms": 0, "bytes": 0, "files": 0, "err": ""}
LOCK = threading.Lock()
LIB = {"key": "", "obj": None}
CFG = {}


# --------------------------------------------------------------------------- #
# 变更探测
# --------------------------------------------------------------------------- #

def scan_signature(mod_root):
    """文件数 + 总字节 + 最新 mtime，够判断「有没有存盘」，且不用哈希全文。"""
    files, total, newest = 0, 0, 0.0
    for base, dirs, names in os.walk(mod_root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in names:
            if name.lower().endswith(SKIP_EXT):
                continue
            path = os.path.join(base, name)
            try:
                st = os.stat(path)
            except OSError:
                continue
            files += 1
            total += st.st_size
            if st.st_mtime > newest:
                newest = st.st_mtime
    return "%d|%d|%.3f" % (files, total, newest), files


# --------------------------------------------------------------------------- #
# 渲染
# --------------------------------------------------------------------------- #

def descriptor_name(mod_root):
    name, version = os.path.basename(mod_root), "0.1.0"
    for cand in (os.path.join(mod_root, "descriptor.mod"),):
        if not os.path.isfile(cand):
            continue
        try:
            root, _ = cw.parse_file(cand)
            got = cw.as_text(getattr(cw.get_one(root, "name"), "value", None))
            ver = cw.as_text(getattr(cw.get_one(root, "version"), "value", None))
            if got:
                name = got
            if ver:
                version = ver
        except Exception:
            pass
    return name, version


def library(mod_root, game_root):
    """贴图库按 game_root 复用；进程内缓存解码结果，省下每次 0.33 秒的扫库。"""
    if not CFG.get("icons") or not game_root:
        return None
    key = os.path.abspath(game_root)
    if LIB["key"] != key or LIB["obj"] is None:
        LIB["key"] = key
        LIB["obj"] = assets.open_library(mod_root, game_root, limit_px=1024)
    return LIB["obj"]


def render(mod_root, game_root):
    name, version = descriptor_name(mod_root)
    report = checks.validate_mod(mod_root, deep=False)
    loc = checks.scan_localisation(mod_root)["keys"]
    bundle = checks.collect_definitions(mod_root)["definitions"]
    tmp = os.path.join(tempfile.gettempdir(), "kiant-watch-%d.html" % os.getpid())
    res = preview.render(
        mod_root,
        tmp,
        name=name,
        version=version,
        definitions=bundle,
        loc=loc,
        issues=report["issues"],
        stats=report["summary"],
        assets=library(mod_root, game_root),
        game_root=game_root,
    )
    with open(tmp, "r", encoding="utf-8") as fh:
        html = fh.read()
    return html, res


def current_html():
    """变了才重渲；浏览器重复请求 /render 时直接回缓存。"""
    mod_root, game_root = CFG["mod"], CFG["game"]
    with LOCK:
        sig, files = scan_signature(mod_root)
        if STATE["html"] and STATE["sig"] == sig:
            return STATE["html"]
        started = time.time()
        try:
            html, res = render(mod_root, game_root)
        except Exception as exc:  # 渲染失败也要把原因摆到页面上
            err = "%s: %s" % (type(exc).__name__, exc)
            STATE.update(sig=sig, at=time.time(), ms=int((time.time() - started) * 1000),
                         err=err, files=files)
            return error_page(err, mod_root)
        STATE.update(
            sig=sig, html=html, at=time.time(),
            ms=int((time.time() - started) * 1000), bytes=res.get("bytes", len(html)),
            files=files, err="", images=res.get("assets", {}).get("images", 0),
        )
        return html


def state_json():
    return {
        "sig": STATE["sig"],
        "at": STATE["at"],
        "ms": STATE["ms"],
        "bytes": STATE["bytes"],
        "files": STATE["files"],
        "images": STATE.get("images", 0),
        "err": STATE["err"],
        "gui": CFG.get("gui", ""),
        "icons": bool(CFG.get("icons") and CFG.get("game")),
    }


def page_html():
    """外壳页：把当前 mod 名与轮询间隔填进模板。"""
    return (PAGE
            .replace("__NAME__", CFG.get("name", "mod"))
            .replace("__INTERVAL__", str(CFG.get("interval", 900))))


def error_page(err, mod_root):
    return (
        '<!doctype html><meta charset="utf-8"><title>预览渲染失败</title>'
        '<body style="background:#14110f;color:#d8d2c6;font:14px/1.7 ui-monospace,monospace;padding:28px">'
        '<h2 style="color:#e8c97a">这次没渲染出来</h2>'
        "<p>修好下面这个错误，存盘后页面会自己恢复。</p>"
        '<pre style="background:#241d17;border:1px solid #4a3b28;padding:14px;white-space:pre-wrap">'
        + err.replace("<", "&lt;")
        + "</pre><p style=\"color:#6f6a60\">mod: " + mod_root.replace("<", "&lt;") + "</p>"
    )


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #

PAGE = """<!doctype html><html lang="zh"><meta charset="utf-8">
<title>预览 · __NAME__</title>
<style>
 html,body{margin:0;height:100%;background:#14110f;overflow:hidden}
 iframe{display:block;width:100%;height:100%;border:0}
 #bar{position:fixed;right:14px;bottom:14px;z-index:9;padding:7px 12px;border-radius:4px;
      background:rgba(22,19,17,.9);border:1px solid #4a3b28;color:#c0bdba;
      font:12px ui-monospace,SFMono-Regular,monospace;box-shadow:0 2px 10px rgba(0,0,0,.5)}
 #bar b{color:#e8c97a} #bar.err{border-color:#8a3b2a;color:#f0a58f}
 #dot{display:inline-block;width:7px;height:7px;border-radius:50%;background:#4a8a3b;margin-right:6px}
 #dot.busy{background:#e8c97a} #dot.bad{background:#c05030}
</style>
<iframe id="view" src="/render" title="预览"></iframe>
<div id="bar"><span id="dot"></span><b>改盘即刷新</b> · 等待第一次渲染…</div>
<script>
const view = document.getElementById('view');
const bar = document.getElementById('bar');
const dot = document.getElementById('dot');
let last = null;
function paint(s){
  const kb = Math.round((s.bytes||0)/1024);
  if (s.err) { bar.className='err'; dot.className='bad'; bar.innerHTML='<b>渲染失败</b> · '+s.err.slice(0,120); return; }
  bar.className=''; dot.className='';
  const clock = s.at ? new Date(s.at*1000).toLocaleTimeString('zh-CN',{hour12:false}) : '--:--:--';
  bar.innerHTML = '<span id="dot"></span><b>改盘即刷新</b> · '+s.files+' 个文件 · '+kb+' KB'
    + (s.images? ' · 贴图 '+s.images+' 张':'')
    + ' · '+s.ms+' ms · '+clock;
}
async function tick(){
  try{
    const s = await (await fetch('/state', {cache:'no-store'})).json();
    if (last && s.sig !== last && !s.err){
      dot.className='busy';
      view.src = '/render?v=' + Date.now();
    }
    last = s.sig;
    paint(s);
  }catch(e){ dot.className='bad'; bar.innerHTML='<b>连不上本地服务</b>（是不是关了？）'; }
}
setInterval(tick, __INTERVAL__);
tick();
</script></html>"""


def make_handler():
    class Handler(BaseHTTPRequestHandler):
        server_version = "kiant-hoi4-watch"

        def _send(self, code, body, ctype):
            data = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype + "; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            route = self.path.split("?")[0]
            if route in ("/", "/index.html"):
                return self._send(200, page_html(), "text/html")
            if route == "/render":
                return self._send(200, current_html(), "text/html")
            if route == "/state":
                return self._send(200, json.dumps(state_json(), ensure_ascii=False), "application/json")
            if route == "/health":
                return self._send(200, "ok", "text/plain")
            return self._send(404, "not found", "text/plain")

        def log_message(self, fmt, *args):
            if CFG.get("verbose"):
                sys.stderr.write("[watch] " + (fmt % args) + "\n")

    return Handler


# --------------------------------------------------------------------------- #
# 入口
# --------------------------------------------------------------------------- #

def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="kiant-hoi4-watch",
        description="盯着 mod 目录，浏览器里的预览跟着存盘自动刷新。",
    )
    ap.add_argument("mod_path", help="mod 根目录（含 descriptor.mod 的那一层）")
    ap.add_argument("--port", type=int, default=8765, help="起始端口，占用就往后找（默认 8765）")
    ap.add_argument("--interval", type=int, default=900, help="页面轮询间隔毫秒（默认 900）")
    ap.add_argument("--game", default="", help="HOI4 安装目录；不给就自动探测")
    ap.add_argument("--no-icons", action="store_true", help="不读游戏贴图，只出版面")
    ap.add_argument("--out", default="", help="--once 时的输出路径（默认 <mod>/.modkit/preview.html）")
    ap.add_argument("--once", action="store_true", help="只渲染一次写文件，不起服务")
    ap.add_argument("--open", action="store_true", help="起服务后自动开浏览器")
    ap.add_argument("--verbose", action="store_true", help="打印每次请求")
    args = ap.parse_args(argv)

    mod_root, _descriptor, _notes = checks.resolve_mod_root(args.mod_path)
    if not os.path.isdir(mod_root):
        sys.stderr.write("找不到 mod 目录：%s\n" % args.mod_path)
        return 2

    game = args.game.strip()
    if not game and not args.no_icons:
        try:
            import kb
            game = kb.find_game_dir() or ""
        except Exception:
            game = ""
    if not args.no_icons and not game:
        sys.stderr.write("没找到 HOI4 安装目录，退回无贴图模式（加 --game 可指定）\n")

    CFG.update(
        mod=mod_root, game=game, icons=not args.no_icons,
        interval=max(300, args.interval), verbose=args.verbose,
    )
    CFG["name"] = descriptor_name(mod_root)[0]

    if args.once:
        out = args.out or os.path.join(mod_root, ".modkit", "preview.html")
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        html, res = render(mod_root, game)
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(html)
        print("已生成 %s（%d 字节，贴图 %d 张，%d ms）" % (
            out, res.get("bytes", len(html)), res.get("assets", {}).get("images", 0),
            int(res.get("seconds", 0) * 1000)))
        return 0

    handler = make_handler()
    port = args.port
    for _ in range(8):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", port), handler)
            break
        except OSError:
            port += 1
    else:
        sys.stderr.write("端口 %d 起连续 8 个都被占用，换个 --port 再试\n" % args.port)
        return 1

    url = "http://127.0.0.1:%d/" % port
    print("预览服务已启动：%s" % url)
    print("  mod：%s" % mod_root)
    print("  游戏：%s" % (game or "（未使用，版面仍然可用）"))
    print("  存盘后 1 秒内自动刷新；Ctrl+C 结束。")
    if args.open:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
