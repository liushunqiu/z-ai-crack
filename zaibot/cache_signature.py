#!/usr/bin/env python3
"""Create zaibot_signature_cache.json from captured_request.json.

Useful after running capture_signature.py or when manually editing a captured
request sample.
"""
import json
import time
import sys
from pathlib import Path
from urllib.parse import urlparse, parse_qs

BASE = Path(__file__).parent
CAPTURED = BASE / "captured_request.json"
OUT = BASE / "zaibot_signature_cache.json"


def main() -> int:
    if not CAPTURED.exists():
        print("[x] captured_request.json not found", file=sys.stderr)
        return 1
    data = json.loads(CAPTURED.read_text())
    reqs = data.get("requests") or []
    if not reqs:
        print("[x] no captured requests", file=sys.stderr)
        return 1
    req = reqs[-1]
    headers = {str(k).lower(): v for k, v in (req.get("headers") or {}).items()}
    sig = headers.get("x-signature")
    qs = parse_qs(urlparse(req.get("url", "")).query)
    sig_ts = (qs.get("signature_timestamp") or [str(req.get("timestamp") or "")])[0]
    if not sig or not sig_ts:
        print("[x] signature or signature_timestamp missing", file=sys.stderr)
        return 1
    OUT.write_text(json.dumps({
        "signature": sig,
        "signature_timestamp": sig_ts,
        "created_at": time.time(),
        "source": "captured_request.json",
    }, indent=2), encoding="utf-8")
    print(f"[✓] saved {OUT}")
    print(f"    signature={sig[:16]}... signature_timestamp={sig_ts}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
