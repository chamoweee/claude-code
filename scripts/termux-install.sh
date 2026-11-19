#!/data/data/com.termux/files/usr/bin/bash
# One-step installer for the YouTube to MP3 app in Termux (Android).
#
#   curl -sL https://raw.githubusercontent.com/chamoweee/claude-code/main/scripts/termux-install.sh | bash
#
# Afterwards:
#   - Share a YouTube video to Termux  -> it is added to the app and converted
#   - Type `ytmp3` in Termux            -> opens the app in your browser
#   - Termux:Widget (optional)          -> home-screen button "YouTube MP3"
set -e

REF="${YTMP3_REF:-main}"
BASE="https://raw.githubusercontent.com/chamoweee/claude-code/$REF/scripts"
APP="$HOME/ytmp3"

echo "==> Installing Python and ffmpeg (this can take a few minutes)…"
pkg install -y python ffmpeg >/dev/null

echo "==> Installing / updating yt-dlp…"
pip install -q -U yt-dlp

echo "==> Downloading the app…"
mkdir -p "$APP" "$HOME/bin" "$HOME/.shortcuts"
curl -fsSL -o "$APP/yt_to_mp3.py" "$BASE/yt_to_mp3.py"
curl -fsSL -o "$APP/yt_mp3_web.py" "$BASE/yt_mp3_web.py"

if [ ! -d "$HOME/storage/music" ]; then
  echo "==> Asking for storage access: tap ALLOW on the popup."
  termux-setup-storage || true
  sleep 3
fi

# `ytmp3 [link]` starts the app if needed, adds the link, opens the browser.
cat > "$HOME/bin/ytmp3" <<'EOF'
#!/data/data/com.termux/files/usr/bin/bash
URL=http://127.0.0.1:8765
if ! curl -s -o /dev/null "$URL/api/jobs"; then
  termux-wake-lock 2>/dev/null || true   # keep converting while the screen is off
  nohup python "$HOME/ytmp3/yt_mp3_web.py" > "$HOME/ytmp3/server.log" 2>&1 &
  for _ in $(seq 30); do curl -s -o /dev/null "$URL/api/jobs" && break; sleep 0.5; done
fi
if [ -n "$1" ]; then
  curl -s --data-urlencode "text=$*" "$URL/api/add" > /dev/null
fi
termux-open-url "$URL/"
EOF
chmod +x "$HOME/bin/ytmp3"

# Sharing a link to Termux runs this.
cat > "$HOME/bin/termux-url-opener" <<'EOF'
#!/data/data/com.termux/files/usr/bin/bash
exec "$HOME/bin/ytmp3" "$1"
EOF
chmod +x "$HOME/bin/termux-url-opener"

# Optional home-screen button via the Termux:Widget app.
cp "$HOME/bin/ytmp3" "$HOME/.shortcuts/YouTube MP3"

# Make sure ~/bin is on PATH for new sessions.
grep -q 'HOME/bin' "$HOME/.bashrc" 2>/dev/null || echo 'export PATH="$HOME/bin:$PATH"' >> "$HOME/.bashrc"

echo
echo "Done! Opening the app…"
"$HOME/bin/ytmp3"
echo
echo "Next time: share a YouTube video to Termux, or type: ytmp3"
