#!/usr/bin/env python3
"""Generate and verify chat.z.ai X-Signature locally."""
import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, str(Path(__file__).parent))
import zaibot_core as z


def verify_captured(path: Path) -> int:
    data = json.loads(path.read_text())
    ok = 0
    total = 0
    for req in data.get("requests", []):
        if not isinstance(req, dict) or "chat/completions" not in req.get("url", ""):
            continue
        qs = parse_qs(urlparse(req["url"]).query)
        body = json.loads(req.get("body") or "{}")
        headers = {str(k).lower(): v for k, v in (req.get("headers") or {}).items()}
        expected = headers.get("x-signature")
        if not expected:
            continue
        total += 1
        actual = z.sign_with_secret(
            z.DEFAULT_HMAC_SECRET,
            body.get("signature_prompt") or body.get("messages", [{}])[-1].get("content", ""),
            qs["timestamp"][0],
            qs["requestId"][0],
            qs["user_id"][0],
        )
        passed = actual == expected
        ok += int(passed)
        print(f"[{total}] {'OK' if passed else 'FAIL'} expected={expected} actual={actual}")
    print(f"pass {ok}/{total}")
    return 0 if ok == total and total else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify-captured", type=Path, default=Path(__file__).parent / "captured_request.json")
    ap.add_argument("--prompt")
    ap.add_argument("--timestamp")
    ap.add_argument("--request-id")
    ap.add_argument("--user-id")
    args = ap.parse_args()
    if args.prompt:
        if not (args.timestamp and args.request_id and args.user_id):
            ap.error("--prompt requires --timestamp --request-id --user-id")
        print(z.sign_with_secret(z.DEFAULT_HMAC_SECRET, args.prompt, args.timestamp, args.request_id, args.user_id))
        return 0
    return verify_captured(args.verify_captured)

if __name__ == "__main__":
    raise SystemExit(main())
