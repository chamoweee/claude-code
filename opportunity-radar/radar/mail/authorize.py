"""One-time helper: mint a Gmail refresh token.

Run this **locally, once**, on a machine with a browser:

    python -m radar.mail.authorize

It asks for the client ID and secret from the Desktop OAuth client you created,
opens Google's consent screen, catches the redirect on localhost, and prints the
refresh token to paste into the ``GMAIL_REFRESH_TOKEN`` GitHub Secret.

Nothing is written to disk. The token is printed once and then forgotten — if
you lose it, run this again.

Only the ``gmail.send`` scope is requested. This grants no ability to read mail.
"""

from __future__ import annotations

import http.server
import json
import secrets
import socket
import sys
import threading
import urllib.parse
import urllib.request
import webbrowser

from .gmail import SEND_SCOPE, TOKEN_URL, MailError

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    code: str | None = None
    state: str | None = None
    expected_state: str = ""

    def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        _CallbackHandler.code = (query.get("code") or [None])[0]
        _CallbackHandler.state = (query.get("state") or [None])[0]
        ok = bool(_CallbackHandler.code) and \
            _CallbackHandler.state == _CallbackHandler.expected_state
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        body = ("<h2>Authorised.</h2><p>Return to your terminal — the refresh "
                "token is printed there. You can close this tab.</p>" if ok else
                "<h2>Something went wrong.</h2><p>Check the terminal.</p>")
        self.write_html(body)

    def write_html(self, body: str) -> None:
        self.wfile.write(f"<html><body style='font-family:sans-serif;padding:40px'>"
                         f"{body}</body></html>".encode())

    def log_message(self, *args) -> None:  # keep the console clean
        return


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def exchange_code(client_id: str, client_secret: str, code: str,
                  redirect_uri: str) -> dict:
    data = urllib.parse.urlencode({
        "client_id": client_id, "client_secret": client_secret, "code": code,
        "grant_type": "authorization_code", "redirect_uri": redirect_uri,
    }).encode()
    request = urllib.request.Request(TOKEN_URL, data=data, method="POST")
    request.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode())


def main() -> int:
    print(__doc__)
    client_id = input("OAuth client ID: ").strip()
    client_secret = input("OAuth client secret: ").strip()
    if not client_id or not client_secret:
        print("Both values are required.", file=sys.stderr)
        return 2

    port = _free_port()
    redirect_uri = f"http://localhost:{port}/"
    state = secrets.token_urlsafe(24)
    _CallbackHandler.expected_state = state

    params = urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SEND_SCOPE,
        # Without both of these Google returns no refresh token on repeat grants.
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    })
    url = f"{AUTH_URL}?{params}"

    server = http.server.HTTPServer(("127.0.0.1", port), _CallbackHandler)
    threading.Thread(target=server.handle_request, daemon=True).start()

    print(f"\nOpening your browser. If it does not open, visit:\n\n{url}\n")
    try:
        webbrowser.open(url)
    except Exception:  # noqa: BLE001 - headless machines are fine, the URL is printed
        pass

    print("Waiting for the redirect...")
    server.server_close()
    if not _CallbackHandler.code:
        print("No authorisation code received.", file=sys.stderr)
        return 1
    if _CallbackHandler.state != state:
        print("State mismatch — discarding this response.", file=sys.stderr)
        return 1

    try:
        payload = exchange_code(client_id, client_secret,
                                _CallbackHandler.code, redirect_uri)
    except Exception as exc:  # noqa: BLE001
        raise MailError(f"code exchange failed: {type(exc).__name__}") from exc

    refresh_token = payload.get("refresh_token")
    if not refresh_token:
        print("Google returned no refresh token. This usually means the account "
              "has already granted consent — revoke it at "
              "https://myaccount.google.com/permissions and run this again.",
              file=sys.stderr)
        return 1

    print("\n" + "=" * 64)
    print("GMAIL_REFRESH_TOKEN")
    print(refresh_token)
    print("=" * 64)
    print("\nPaste that into the GMAIL_REFRESH_TOKEN GitHub Secret, together with\n"
          "GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET and GMAIL_SENDER.\n"
          "It is not saved anywhere — if you lose it, run this again.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
