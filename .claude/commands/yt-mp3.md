---
allowed-tools: Bash(python3 scripts/yt_to_mp3.py:*), Bash(pip install -U yt-dlp)
description: Convert YouTube links to MP3 files
argument-hint: <youtube-url> [more urls...] [--quality 320] [--out dir] [--playlist] [--cookies-from-browser chrome]
---

Use the `youtube-to-mp3` agent to convert these YouTube links to MP3: $ARGUMENTS

Report back the list of MP3 files created and any failures.
