#!/usr/bin/env python3
"""YouTube to MP3, with a simple web page you open on your phone or computer.

Paste one or many YouTube links, tap Convert, and the MP3s are saved to your
Music folder. Runs only on this device (http://127.0.0.1:8765).

Usage:
  yt_mp3_web.py [--out DIR] [--port 8765]

Requires yt_to_mp3.py next to this file, yt-dlp and ffmpeg.
Only download content you own or have permission to download.
"""

import argparse
import json
import queue
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from yt_to_mp3 import Converter, check_deps, extract_links  # noqa: E402

PAGE = r"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>YouTube to MP3</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--text:#16181d;--muted:#667085;--line:#e3e6eb;
  --accent:#d92d20;--accent-text:#fff;--ok:#12b76a;--err:#d92d20;--bar:#f2f4f7}
@media (prefers-color-scheme:dark){:root{--bg:#0f1115;--card:#181b21;--text:#eef0f3;
  --muted:#98a2b3;--line:#2a2f38;--accent:#f04438;--bar:#252a33}}
html{color-scheme:light dark}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);
  font:16px/1.45 system-ui,-apple-system,Roboto,sans-serif}
main{max-width:560px;margin:0 auto;padding:20px 16px 48px}
h1{font-size:22px;margin:4px 0 2px}
.sub{color:var(--muted);margin:0 0 16px;font-size:14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px}
textarea{width:100%;min-height:130px;resize:vertical;border:1px solid var(--line);
  border-radius:10px;padding:10px;font:inherit;background:var(--bg);color:var(--text)}
.row{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-top:10px}
label{font-size:14px;color:var(--muted);display:flex;align-items:center;gap:6px}
select{font:inherit;padding:6px 8px;border-radius:8px;border:1px solid var(--line);
  background:var(--bg);color:var(--text)}
button{font:inherit;border:0;border-radius:10px;padding:12px 16px;cursor:pointer;
  background:var(--bar);color:var(--text)}
button.primary{background:var(--accent);color:var(--accent-text);font-weight:600;flex:1}
button:disabled{opacity:.5}
#msg{min-height:20px;font-size:14px;color:var(--muted);margin-top:8px}
h2{font-size:15px;margin:22px 0 8px;display:flex;justify-content:space-between;align-items:center}
h2 button{padding:6px 10px;font-size:13px}
.job{background:var(--card);border:1px solid var(--line);border-radius:12px;
  padding:10px 12px;margin-bottom:8px}
.title{font-size:14px;word-break:break-word}
.state{font-size:13px;color:var(--muted);margin-top:2px}
.state.ok{color:var(--ok)}.state.err{color:var(--err)}
.bar{height:6px;background:var(--bar);border-radius:3px;margin-top:6px;overflow:hidden}
.bar i{display:block;height:100%;background:var(--accent);width:0;transition:width .4s}
audio{width:100%;margin-top:8px;height:36px}
.retry{margin-top:8px;padding:8px 12px;font-size:14px}
.empty{color:var(--muted);font-size:14px;text-align:center;padding:16px}
</style></head><body><main>
<h1>YouTube to MP3</h1>
<p class="sub">Paste one or more links, one per line or all together.</p>
<div class="card">
  <textarea id="links" placeholder="https://youtu.be/…&#10;https://www.youtube.com/watch?v=…"></textarea>
  <div class="row">
    <label>Quality <select id="quality">
      <option value="128">128 kbps</option><option value="192" selected>192 kbps</option>
      <option value="256">256 kbps</option><option value="320">320 kbps (best)</option>
    </select></label>
    <label><input type="checkbox" id="playlist"> Whole playlists</label>
  </div>
  <div class="row">
    <button id="paste" type="button">Paste</button>
    <button id="go" class="primary" type="button">Convert</button>
  </div>
  <div id="msg"></div>
</div>
<h2><span>Downloads</span><button id="clear" type="button">Clear finished</button></h2>
<div id="jobs"><div class="empty">Nothing yet.</div></div>
<p class="sub" id="where"></p>
</main>
<script>
const $ = id => document.getElementById(id);
const store = {get(k){try{return localStorage.getItem(k)}catch(e){return null}},
               set(k,v){try{localStorage.setItem(k,v)}catch(e){}}};
if (store.get('q')) $('quality').value = store.get('q');
$('quality').onchange = () => store.set('q', $('quality').value);

$('paste').onclick = async () => {
  try { const t = await navigator.clipboard.readText();
        $('links').value += ($('links').value && !$('links').value.endsWith('\n') ? '\n' : '') + t; }
  catch (e) { $('msg').textContent = 'Long-press the box and tap Paste instead.'; }
};

$('go').onclick = async () => {
  const text = $('links').value.trim();
  if (!text) { $('msg').textContent = 'Paste at least one YouTube link first.'; return; }
  $('go').disabled = true;
  try {
    const r = await fetch('/api/add', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({text, quality:$('quality').value, playlist:$('playlist').checked})});
    const d = await r.json();
    $('msg').textContent = d.added ? `Added ${d.added} link${d.added>1?'s':''}.` : 'No YouTube links found in that text.';
    if (d.added) $('links').value = '';
    refresh();
  } catch (e) { $('msg').textContent = 'Could not reach the converter. Is it still running in Termux?'; }
  $('go').disabled = false;
};

$('jobs').onclick = async e => {
  const b = e.target.closest('.retry'); if (!b) return;
  b.disabled = true;
  await fetch('/api/add', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({text:b.dataset.url, quality:b.dataset.q, playlist:!!b.dataset.pl,
                        replace:+b.dataset.id})});
  refresh();
};

$('clear').onclick = async () => { await fetch('/api/clear', {method:'POST'}); refresh(); };

const LABEL = {queued:'Waiting…', working:'Downloading…', converting:'Converting to MP3…',
               ok:'Saved', skipped:'Already converted', error:'Failed'};
function esc(s){return String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}

async function refresh() {
  let d; try { d = await (await fetch('/api/jobs')).json(); } catch (e) { return; }
  $('where').textContent = 'Saved to: ' + d.out;
  if (!d.jobs.length) { $('jobs').innerHTML = '<div class="empty">Nothing yet.</div>'; return; }
  $('jobs').innerHTML = d.jobs.slice().reverse().map(j => {
    const cls = j.status === 'ok' ? 'ok' : j.status === 'error' ? 'err' : '';
    const bar = (j.status === 'working' || j.status === 'converting')
      ? `<div class="bar"><i style="width:${Math.round((j.progress||0)*100)}%"></i></div>` : '';
    const players = (j.files||[]).map(f => `<audio controls preload="none" src="${esc(f.url)}"></audio>`).join('');
    const detail = j.status === 'error' ? ': ' + esc(j.error) : '';
    const retry = j.status === 'error'
      ? `<button class="retry" type="button" data-id="${j.id}" data-url="${esc(j.url)}" data-q="${esc(j.quality)}" data-pl="${j.playlist?1:''}">Retry</button>` : '';
    return `<div class="job"><div class="title">${esc(j.title || j.url)}</div>
      <div class="state ${cls}">${LABEL[j.status] || j.status}${detail}</div>${bar}${players}${retry}</div>`;
  }).join('');
}
refresh(); setInterval(refresh, 1500);
</script></body></html>"""


def friendly_error(msg):
    """Turn yt-dlp errors into plain advice for the web page."""
    if not msg:
        return msg
    m = msg.lower()
    if "bot check" in m or "not a bot" in m:
        return ("YouTube blocked this download. Switch between Wi-Fi and mobile data "
                "and tap Retry. If it keeps happening, run the installer again to update.")
    if "private" in m:
        return "This video is private."
    if "age" in m and ("restrict" in m or "confirm your age" in m):
        return "This video is age-restricted and can't be downloaded without signing in."
    if "unavailable" in m or "not available" in m:
        return "This video is unavailable (removed or blocked in your country)."
    return msg


class App:
    def __init__(self, out_dir: Path):
        self.conv = Converter(out_dir, "192", False)
        self.conv.on_progress = self._progress
        self.jobs: list[dict] = []
        self.lock = threading.Lock()
        self.q: queue.Queue = queue.Queue()
        self.current = None
        self.next_id = 1
        threading.Thread(target=self._worker, daemon=True).start()

    def add(self, text: str, quality: str, playlist: bool) -> int:
        if quality not in ("128", "192", "256", "320"):
            quality = "192"
        links = extract_links(text)
        with self.lock:
            for url in links:
                job = {"id": self.next_id, "url": url, "status": "queued",
                       "quality": quality, "playlist": bool(playlist),
                       "progress": 0.0, "files": [], "title": None, "error": None}
                self.next_id += 1
                self.jobs.append(job)
                self.q.put(job)
        return len(links)

    def remove_failed(self, job_id) -> None:
        with self.lock:
            self.jobs = [j for j in self.jobs
                         if not (j["id"] == job_id and j["status"] == "error")]

    def clear(self) -> None:
        with self.lock:
            self.jobs = [j for j in self.jobs if j["status"] in ("queued", "working", "converting")]

    def snapshot(self) -> dict:
        with self.lock:
            return {"out": str(self.conv.out_dir), "jobs": [dict(j) for j in self.jobs]}

    def _progress(self, frac: float) -> None:
        job = self.current
        if job:
            job["progress"] = frac
            if frac >= 1.0:
                job["status"] = "converting"

    def _worker(self) -> None:
        while True:
            job = self.q.get()
            self.current = job
            job["status"] = "working"
            self.conv.quality = job["quality"]
            self.conv.playlist = job["playlist"]
            r = self.conv.convert(job["url"])
            with self.lock:
                job["status"] = r["status"]
                job["error"] = friendly_error(r.get("error"))
                files = []
                for f in r.get("files", []):
                    p = Path(f)
                    files.append({"name": p.name, "url": "/audio/" + quote(p.name)})
                job["files"] = files
                if files:
                    job["title"] = Path(files[0]["name"]).stem
                if r["status"] == "skipped":
                    job["error"] = r.get("reason")
            self.current = None


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):  # keep the terminal quiet
            pass

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code: int = 200) -> None:
            self._send(code, json.dumps(obj).encode(), "application/json")

        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/":
                self._send(200, PAGE.encode(), "text/html; charset=utf-8")
            elif path == "/api/jobs":
                self._json(app.snapshot())
            elif path.startswith("/audio/"):
                self._audio(path[len("/audio/"):])
            else:
                self._send(404, b"Not found", "text/plain")

        def do_POST(self):
            path = urlparse(self.path).path
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(min(length, 1_000_000)).decode("utf-8", "replace")
            if path == "/api/add":
                if "json" in (self.headers.get("Content-Type") or ""):
                    try:
                        data = json.loads(raw or "{}")
                    except ValueError:
                        return self._json({"error": "bad JSON"}, 400)
                else:  # form-encoded, used by the Termux share-sheet helper
                    data = {k: v[0] for k, v in parse_qs(raw).items()}
                    data["playlist"] = data.get("playlist") in ("1", "true", "on")
                if data.get("replace"):
                    app.remove_failed(data["replace"])
                added = app.add(str(data.get("text", "")), str(data.get("quality", "192")),
                                bool(data.get("playlist")))
                self._json({"added": added})
            elif path == "/api/clear":
                app.clear()
                self._json({"ok": True})
            else:
                self._send(404, b"Not found", "text/plain")

        def _audio(self, name: str) -> None:
            from urllib.parse import unquote
            out = app.conv.out_dir.resolve()
            p = (out / unquote(name)).resolve()
            if p.parent != out or p.suffix.lower() != ".mp3" or not p.is_file():
                return self._send(404, b"Not found", "text/plain")
            self._send(200, p.read_bytes(), "audio/mpeg")

    return Handler


def default_out() -> Path:
    music = Path.home() / "storage" / "music"  # Termux shared Music folder
    return music / "YouTube" if music.is_dir() else Path("mp3")


def main() -> int:
    p = argparse.ArgumentParser(description="YouTube to MP3 web app.")
    p.add_argument("-o", "--out", type=Path, default=None)
    p.add_argument("--port", type=int, default=8765)
    args = p.parse_args()

    check_deps()
    app = App(args.out or default_out())
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(app))
    print(f"YouTube to MP3 is running: http://127.0.0.1:{args.port}/")
    print(f"MP3s are saved to {app.conv.out_dir}. Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
