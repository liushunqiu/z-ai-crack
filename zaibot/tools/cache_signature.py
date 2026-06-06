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
import logging
_logger = logging.getLogger(__name__)


BASE = Path(__file__).parent
CAPTURED = BASE / "captured_request.json"
OUT = BASE / "zaibot_signature_cache.json"


def main() -> int:
    if not CAPTURED.exists():
        _logger.warning("[x] captured_request.json not found")
        return 1
    data = json.loads(CAPTURED.read_text())
    reqs = data.get("requests") or []
    if not reqs:
        _logger.warning("[x] no captured requests")
        return 1
    req = reqs[-1]
    headers = {str(k).lower(): v for k, v in (req.get("headers") or {}).items()}
    sig = headers.get("x-signature")
    qs = parse_qs(urlparse(req.get("url", "")).query)
    sig_ts = (qs.get("signature_timestamp") or [str(req.get("timestamp") or "")])[0]
    if not sig or not sig_ts:
        _logger.warning("[x] signature or signature_timestamp missing")
        return 1
    OUT.write_text(json.dumps({
        "signature": sig,
        "signature_timestamp": sig_ts,
        "created_at": time.time(),
        "source": "captured_request.json",
    }, indent=2), encoding="utf-8")
    _logger.info(f"[✓] saved {OUT}")
    _logger.info(f"    signature={sig[:16]}... signature_timestamp={sig_ts}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
