#!/usr/bin/env python3
"""One-time Gmail OAuth loopback flow — prints GMAIL_REFRESH_TOKEN.

Stdlib only, so it runs on any machine with Python 3:

    GMAIL_CLIENT_ID=... GMAIL_CLIENT_SECRET=... python3 scripts/gmail_authorize.py

See docs/runbooks/gmail-line-setup.md for the Google Cloud setup that precedes this.
"""

import http.server
import json
import os
import secrets
import sys
import urllib.parse
import urllib.request

SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
PORT = 8765
REDIRECT_URI = f"http://127.0.0.1:{PORT}"


def main() -> None:
    client_id = os.environ.get("GMAIL_CLIENT_ID", "")
    client_secret = os.environ.get("GMAIL_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        sys.exit("Set GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET in the environment first.")

    state = secrets.token_urlsafe(16)
    auth_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(
        {
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "scope": SCOPE,
            "access_type": "offline",
            "prompt": "consent",  # force refresh_token issuance even if previously granted
            "state": state,
        }
    )
    print("\n1. Open this URL in a browser logged in as the owner Gmail:\n")
    print(auth_url)
    print(f"\n2. Approve access — Google redirects to {REDIRECT_URI} ...\n")

    code_holder: dict[str, str] = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 (stdlib naming)
            params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if params.get("state", [""])[0] != state:
                self.send_error(400, "state mismatch — restart the flow")
                return
            code_holder["code"] = params.get("code", [""])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write("Authorized. You can close this tab.".encode())

        def log_message(self, *args: object) -> None:  # silence request logging
            pass

    with http.server.HTTPServer(("127.0.0.1", PORT), Handler) as srv:
        while "code" not in code_holder:
            srv.handle_request()

    body = urllib.parse.urlencode(
        {
            "code": code_holder["code"],
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": REDIRECT_URI,
            "grant_type": "authorization_code",
        }
    ).encode()
    req = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req) as resp:
        tokens = json.load(resp)

    refresh = tokens.get("refresh_token")
    if not refresh:
        sys.exit(f"No refresh_token in response: {tokens}")
    print("Add to infra/compose/.env:\n")
    print(f"GMAIL_REFRESH_TOKEN={refresh}\n")


if __name__ == "__main__":
    main()
