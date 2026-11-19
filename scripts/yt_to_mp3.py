#!/usr/bin/env python3
"""Convert YouTube links to MP3 files.

Requires: yt-dlp (pip install yt-dlp) and ffmpeg on PATH.

Usage:
  yt_to_mp3.py URL [URL ...]            convert one or more links
  yt_to_mp3.py --file links.txt         convert every link found in a text file
  echo URL | yt_to_mp3.py -             read links from stdin
  yt_to_mp3.py --watch inbox.txt        keep running; convert links as they are
                                        appended to inbox.txt (Ctrl+C to stop)

Options:
  -o, --out DIR        output directory (default: ./mp3)
  -q, --quality KBPS   MP3 bitrate: 128, 192, 256 or 320 (default: 192)
  --playlist           download whole playlists instead of only the linked video
  --interval SECONDS   polling interval for --watch (default: 5)
  --cookies-from-browser NAME
                       use your browser's YouTube login (chrome, firefox, edge,
                       safari, brave…) when YouTube says "Sign in to confirm"
  --cookies FILE       same, from an exported cookies.txt file

Links already converted are recorded in DIR/.converted and skipped next time.
Only download content you own or have permission to download.
"""

import argparse
import json
import re
import shutil
import sys
import time
from pathlib import Path

YOUTUBE_RE = re.compile(
    r"(https?://)?(www\.|m\.|music\.)?"
    r"(youtube\.com/(watch\?[^\s]*v=|shorts/|live/|playlist\?list=)|youtu\.be/)"
    r"[\w\-?=&%.#]+"
)


def extract_links(text: str) -> list[str]:
    """Return YouTube links found in arbitrary text, in order, without duplicates."""
    seen, links = set(), []
    for m in YOUTUBE_RE.finditer(text):
        url = m.group(0)
        if not url.startswith("http"):
            url = "https://" + url
        if url not in seen:
            seen.add(url)
            links.append(url)
    return links


def check_deps() -> None:
    missing = []
    try:
        import yt_dlp  # noqa: F401
    except ImportError:
        missing.append("yt-dlp  (pip install yt-dlp)")
    if not shutil.which("ffmpeg"):
        missing.append("ffmpeg  (apt install ffmpeg / brew install ffmpeg)")
    if missing:
        sys.exit("Missing dependencies:\n  " + "\n  ".join(missing))


class _QuietLogger:
    """Swallow yt-dlp's own output; errors are reported by report()."""
    def debug(self, msg): pass
    def info(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): pass


class Converter:
    def __init__(self, out_dir: Path, quality: str, playlist: bool,
                 cookies: Path | None = None, cookies_browser: str | None = None):
        self.out_dir = out_dir
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.ledger = out_dir / ".converted"
        self.done = set(self.ledger.read_text().split()) if self.ledger.exists() else set()
        self.quality = quality
        self.playlist = playlist
        self.cookies = cookies
        self.cookies_browser = cookies_browser
        self.files: list[str] = []
        self.on_progress = None  # optional callable(fraction 0..1)

    def _progress_hook(self, d: dict) -> None:
        if self.on_progress and d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            if total:
                self.on_progress(min(d.get("downloaded_bytes", 0) / total, 1.0))

    def _post_hook(self, d: dict) -> None:
        if d.get("status") == "finished" and d.get("postprocessor") == "MoveFiles":
            path = d.get("info_dict", {}).get("filepath")
            if path:
                self.files.append(path)

    def convert(self, url: str) -> dict:
        import yt_dlp

        if url in self.done:
            return {"url": url, "status": "skipped", "reason": "already converted"}

        self.files = []
        opts = {
            "format": "bestaudio/best",
            "outtmpl": str(self.out_dir / "%(title)s [%(id)s].%(ext)s"),
            "noplaylist": not self.playlist,
            "restrictfilenames": False,
            "windowsfilenames": True,
            "quiet": True,
            "logger": _QuietLogger(),
            "no_warnings": True,
            "noprogress": True,
            "writethumbnail": True,
            "postprocessors": [
                {"key": "FFmpegExtractAudio", "preferredcodec": "mp3",
                 "preferredquality": self.quality},
                {"key": "FFmpegMetadata", "add_metadata": True},
                {"key": "EmbedThumbnail"},
            ],
            "progress_hooks": [self._progress_hook],
            "postprocessor_hooks": [self._post_hook],
        }
        if self.cookies:
            opts["cookiefile"] = str(self.cookies)
        if self.cookies_browser:
            opts["cookiesfrombrowser"] = (self.cookies_browser,)
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
        except Exception as e:  # yt-dlp raises DownloadError and others
            msg = str(e).splitlines()[0].removeprefix("ERROR: ")
            if "confirm you" in msg and "not a bot" in msg:
                msg = ("YouTube asked to sign in (bot check). Retry with "
                       "--cookies-from-browser chrome (or firefox, edge…)")
            return {"url": url, "status": "error", "error": msg}

        self.done.add(url)
        with self.ledger.open("a") as f:
            f.write(url + "\n")
        return {"url": url, "status": "ok", "files": self.files}


def report(result: dict) -> None:
    if result["status"] == "ok":
        for f in result["files"] or ["(file written to output directory)"]:
            print(f"✔ {f}")
    elif result["status"] == "skipped":
        print(f"↷ skipped {result['url']} ({result['reason']})")
    else:
        print(f"✘ {result['url']}: {result['error']}", file=sys.stderr)


def watch(conv: Converter, inbox: Path, interval: float) -> None:
    inbox.touch(exist_ok=True)
    print(f"Watching {inbox} for YouTube links (Ctrl+C to stop)…")
    offset = 0
    try:
        while True:
            size = inbox.stat().st_size
            if size < offset:  # file was truncated
                offset = 0
            if size > offset:
                with inbox.open() as f:
                    f.seek(offset)
                    chunk = f.read()
                    offset = f.tell()
                for url in extract_links(chunk):
                    print(f"→ {url}")
                    report(conv.convert(url))
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nStopped.")


def main() -> int:
    p = argparse.ArgumentParser(description="Convert YouTube links to MP3.")
    p.add_argument("urls", nargs="*", help="YouTube links, or '-' to read from stdin")
    p.add_argument("--file", type=Path, help="text file containing links")
    p.add_argument("--watch", type=Path, metavar="INBOX", help="watch a file for new links")
    p.add_argument("-o", "--out", type=Path, default=Path("mp3"))
    p.add_argument("-q", "--quality", default="192", choices=["128", "192", "256", "320"])
    p.add_argument("--playlist", action="store_true")
    p.add_argument("--interval", type=float, default=5.0)
    p.add_argument("--cookies", type=Path, help="cookies.txt file for YouTube login")
    p.add_argument("--cookies-from-browser", metavar="BROWSER",
                   help="read YouTube login cookies from this browser")
    p.add_argument("--json", action="store_true", help="print a JSON summary at the end")
    args = p.parse_args()

    check_deps()
    conv = Converter(args.out, args.quality, args.playlist,
                     args.cookies, args.cookies_from_browser)

    if args.watch:
        watch(conv, args.watch, args.interval)
        return 0

    text = " ".join(u for u in args.urls if u != "-")
    if "-" in args.urls:
        text += "\n" + sys.stdin.read()
    if args.file:
        text += "\n" + args.file.read_text()

    links = extract_links(text)
    if not links:
        p.error("no YouTube links found")

    results = []
    for i, url in enumerate(links, 1):
        print(f"[{i}/{len(links)}] {url}")
        r = conv.convert(url)
        report(r)
        results.append(r)

    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
    return 1 if any(r["status"] == "error" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
