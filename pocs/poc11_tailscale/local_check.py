"""Compara cabeceras de identidad directas y servidas por Tailscale."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.redact import redact  # noqa: E402


def _get(url: str, headers: dict[str, str] | None = None) -> dict:
    request = Request(url, headers=headers or {}, method="GET")
    try:
        with urlopen(request, timeout=15) as response:
            return {"status": response.status, "body": json.loads(response.read().decode("utf-8"))}
    except (OSError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        return {"error": redact(str(exc))}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8792)
    parser.add_argument("--ts-url")
    args = parser.parse_args(argv)
    base = f"http://127.0.0.1:{args.port}/whoami"
    plain = _get(base)
    spoofed = _get(base, {"Tailscale-User-Login": "attacker@example.com"})
    identity = spoofed.get("body", {}).get("Tailscale-User-Login")
    result = {"identity_absent_direct": not plain.get("body", {}).get("Tailscale-User-Login"),
              "spoof_accepted_direct": identity == "attacker@example.com",
              "direct_status": plain.get("status"), "spoof_status": spoofed.get("status")}
    if args.ts_url:
        result["tailscale"] = _get(args.ts_url.rstrip("/") + "/whoami")
    output = redact(json.dumps(result, ensure_ascii=False, indent=2))
    Path("local_check.json").write_text(output + "\n", encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
