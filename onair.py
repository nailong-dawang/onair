#!/usr/bin/env python3
"""onair -- a 'do not disturb' lamp for meetings.

Step zero of the hardware gadget I want to build: it reads my calendar,
and when I'm in a meeting the lamp turns red (ON AIR); otherwise green.
This is the software prototype -- an HTTP interface + a desktop status
page -- so the logic is exercised now and an ESP32 can poll the same
/api/status later.

Providers (swappable):
  - DemoProvider  : simulated meetings, for development & screenshots.
  - GCalProvider   : polls `hatch_gws_cli calendar +agenda --today`;
                     active only when the calendar connector is connected.

Modes:
  auto    follow the calendar provider (default)
  force-on / force-off : manual override (physical lamps have a button)

Endpoints:
  GET  /              the lamp (HTML, auto-refreshes)
  GET  /api/status    {mode, busy, event, ends_at, next_in_min}
  POST /api/mode     {"mode": "auto|force-on|force-off"}

Stdlib only. Run:  python3 onair.py  (listens on 0.0.0.0:8932)
Provider: set ONAIR_PROVIDER=gcal to try the real calendar.
"""
import json
import os
import subprocess
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

PROVIDER = os.environ.get("ONAIR_PROVIDER", "demo").lower()
_port = int(os.environ.get("ONAIR_PORT", "8932"))


class DemoProvider:
    """A pretend meeting schedule so the UI is testable without a calendar.

    Busy 09:30-10:00, 14:00-15:30, and 16:45-17:15 local time every day.
    """

    SLOTS = [("09:30", "10:00", "站会 standup"), ("14:00", "15:30", "项目评审"),
             ("16:45", "17:15", "1:1 同事")]

    def events(self):
        now = datetime.now()
        out = []
        for s, e, title in self.SLOTS:
            sh, sm = map(int, s.split(":"))
            eh, em = map(int, e.split(":"))
            start = now.replace(hour=sh, minute=sm, second=0, microsecond=0)
            end = now.replace(hour=eh, minute=em, second=0, microsecond=0)
            out.append({"summary": title, "start": start.isoformat(timespec="minutes"),
                        "end": end.isoformat(timespec="minutes")})
        return out


class GCalProvider:
    CLI = "/opt/hatch/bin/hatch_gws_cli"

    def _connected(self):
        try:
            r = subprocess.run([self.CLI, "calendar", "status"], capture_output=True,
                               text=True, timeout=15)
            return r.returncode == 0 and '"ok":true' in r.stdout \
                and '"status":"connected"' in r.stdout
        except Exception:
            return False

    def events(self):
        if not self._connected():
            return []
        try:
            r = subprocess.run(
                [self.CLI, "calendar", "+agenda", "--today", "--format", "json"],
                capture_output=True, text=True, timeout=25)
            if r.returncode != 0:
                return []
            data = json.loads(r.stdout)
            items = data.get("events", data) if isinstance(data, dict) else data
            out = []
            for ev in items or []:
                if ev.get("all_day"):
                    continue
                start = ev.get("event_starts_at", {}).get("user_local") \
                    or ev.get("start", {}).get("dateTime")
                end = ev.get("event_ends_at", {}).get("user_local") \
                    or ev.get("end", {}).get("dateTime")
                if start and end:
                    out.append({"summary": ev.get("summary", "(无标题)"),
                                "start": start, "end": end})
            return out
        except Exception:
            return []


provider = GCalProvider() if PROVIDER == "gcal" else DemoProvider()

state = {"mode": "auto", "busy": False, "event": None, "ends_at": None,
         "next_in_min": None, "provider": PROVIDER, "updated": None}
_lock = threading.Lock()


def _parse(ts):
    try:
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            return dt
        return dt.astimezone().replace(tzinfo=None)
    except Exception:
        return None


def refresh():
    """Poll the provider and recompute busy/free. Runs in a thread loop."""
    now = datetime.now()
    busy, event, ends_at, next_in = False, None, None, None
    for ev in sorted(provider.events(), key=lambda e: e["start"]):
        s, e = _parse(ev["start"]), _parse(ev["end"])
        if not s or not e:
            continue
        if s <= now < e:
            busy, event, ends_at = True, ev["summary"], ev["end"]
            break
        if now < s:
            delta = int((s - now).total_seconds() // 60)
            next_in = delta if next_in is None else min(next_in, delta)
    with _lock:
        state.update({"busy": busy, "event": event, "ends_at": ends_at,
                      "next_in_min": next_in,
                      "updated": now.isoformat(timespec="seconds")})


def snapshot():
    with _lock:
        snap = dict(state)
    mode = snap["mode"]
    if mode == "force-on":
        snap["busy"], snap["event"] = True, "(手动强制 ON AIR)"
    elif mode == "force-off":
        snap["busy"], snap["event"] = False, None
    color = "#E5484D" if snap["busy"] else "#3DDC97"
    label = "🔴 ON AIR · 别来烦我" if snap["busy"] else "🟢 有空 · 欢迎打扰"
    if snap["mode"] != "auto":
        label += f"（手动 {snap['mode']}）"
    snap["color"], snap["label"] = color, label
    return snap


PAGE = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="30">
<title>onair · 别来烦我灯</title>
<style>
 body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
      background:#111;font-family:system-ui,"PingFang SC",sans-serif;color:#fff}
 .lamp{text-align:center;padding:2rem}
 .dot{width:220px;height:220px;border-radius:50%;margin:0 auto 1.2rem;
      background:VAR_COLOR;box-shadow:0 0 120px VAR_COLOR;transition:background .5s}
 h1{font-size:1.6rem;margin:.4rem 0} p{color:#aaa;margin:.25rem 0}
 .btn{margin-top:1rem} .btn button{background:#222;color:#fff;border:1px solid #444;
      padding:.5rem 1rem;border-radius:8px;margin:0 .3rem;cursor:pointer;font-size:.9rem}
 .btn button.active{background:#444;border-color:#888}
</style></head>
<body><div class="lamp">
 <div class="dot"></div><h1>VAR_LABEL</h1>
 <p>VAR_SUB</p><p style="font-size:.8rem">VAR_META</p>
 <div class="btn">
  <button data-m="auto">自动</button><button data-m="force-on">强制 ON AIR</button>
  <button data-m="force-off">强制空闲</button>
 </div></div>
<script>
document.querySelectorAll('.btn button').forEach(b=>b.onclick=()=>{
 fetch('/api/mode',{method:'POST',headers:{'Content-Type':'application/json'},
  body:JSON.stringify({mode:b.dataset.m})}).then(()=>location.reload())});
fetch('/api/status').then(r=>r.json()).then(s=>{
 document.querySelectorAll('.btn button').forEach(b=>
  b.classList.toggle('active', b.dataset.m===s.mode));});
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        raw = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if urlparse(self.path).path == "/api/status":
            self._send(200, json.dumps(snapshot(), ensure_ascii=False))
            return
        snap = snapshot()
        sub = ""
        if snap["busy"] and snap["ends_at"]:
            sub = f"进行中：{snap['event']} · 到 {snap['ends_at'][:16]}"
        elif not snap["busy"] and snap["next_in_min"] is not None:
            sub = f"下一场会议：约 {snap['next_in_min']} 分钟后"
        elif not snap["busy"]:
            sub = "今天没有更多会议了"
        page = (PAGE.replace("VAR_COLOR", snap["color"])
                    .replace("VAR_LABEL", snap["label"])
                    .replace("VAR_SUB", sub)
                    .replace("VAR_META", f"provider={snap['provider']} · mode={snap['mode']} · updated={snap['updated'] or '-'}"))
        self._send(200, page, "text/html")

    def do_POST(self):
        if urlparse(self.path).path != "/api/mode":
            self._send(404, '{"error":"not found"}')
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
            mode = body.get("mode")
            if mode not in ("auto", "force-on", "force-off"):
                self._send(400, '{"error":"mode must be auto|force-on|force-off"}')
                return
            with _lock:
                state["mode"] = mode
            self._send(200, json.dumps(snapshot(), ensure_ascii=False))
        except Exception as e:
            self._send(400, json.dumps({"error": str(e)}))

    def log_message(self, *a):
        pass


def main():
    refresh()
    threading.Thread(target=_poller, daemon=True).start()
    HTTPServer(("0.0.0.0", _port), Handler).serve_forever()


def _poller():
    while True:
        time.sleep(60)
        try:
            refresh()
        except Exception:
            pass


if __name__ == "__main__":
    main()
