"""Minimal interactive guest client; tokens stay in process memory, never argv/disk."""

import argparse
import getpass
import http.client
import json
import ssl
from urllib.parse import urlsplit

BASE = "/api/solbuddy_access/v1"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("origin", help="Exact configured HTTPS origin")
    parser.add_argument("--ca-file", help="Optional trusted private CA certificate")
    args = parser.parse_args()
    origin = urlsplit(args.origin)
    if (
        origin.scheme != "https"
        or not origin.hostname
        or origin.username
        or origin.password
        or origin.path not in ("", "/")
        or origin.query
        or origin.fragment
    ):
        parser.error("Supply an HTTPS origin only")
    context = ssl.create_default_context(cafile=args.ca_file)

    def send(method, operation, credential, sequence=None, data=None):
        # HTTPSConnection verifies certificates and never follows redirects.
        connection = http.client.HTTPSConnection(
            origin.hostname, origin.port or 443, context=context, timeout=20
        )
        headers = {"Authorization": credential, "Content-Type": "application/json"}
        if sequence is not None:
            headers["X-Solbuddy-Sequence"] = str(sequence)
        try:
            connection.request(
                method,
                BASE + "/" + operation,
                body=json.dumps(data or {}) if method == "POST" else None,
                headers=headers,
            )
            result = connection.getresponse()
            if result.status != 200:
                # No automatic retry or uncertain sequence resynchronization.
                raise RuntimeError(f"HTTP {result.status}; session stopped")
            raw = result.read(8193)
            if len(raw) > 8192:
                raise RuntimeError("Unexpected response size")
            return json.loads(raw)
        finally:
            connection.close()

    invitation = getpass.getpass("Single-use invitation: ")
    session = send("POST", "session", "SolbuddyInvite " + invitation)
    del invitation
    token, sequence = session["session_token"], session["next_sequence"]
    del session
    print("Connected. Commands: permissions, on, off, renew, quit.")
    while (command := input("> ").strip()) != "quit":
        data = None
        method, operation = "POST", "execute"
        if command == "permissions":
            method, operation = "GET", "permissions"
        elif command == "renew":
            operation = "session/renew"
        elif command in ("on", "off"):
            data = {
                "entity_id": input("Approved entity ID: ").strip(),
                "action": "turn_" + command,
                "parameters": {},
            }
        else:
            print("Unknown command")
            continue
        result = send(method, operation, "SolbuddySession " + token, sequence, data)
        sequence += 1
        if operation == "session/renew":
            token, sequence = result["session_token"], result["next_sequence"]
            print("Session rotated; expires at", result["expires_at"])
        else:
            print(json.dumps(result, indent=2))
        del result


if __name__ == "__main__":
    try:
        main()
    except OSError, ValueError, RuntimeError, EOFError, KeyboardInterrupt:
        # Never print exception details that could contain request/credential data.
        raise SystemExit(
            "Client stopped. Do not retry an uncertain device action."
        ) from None
