"""External smoke check; handles one Free service cold start without hiding failures."""

import argparse
import json
from pathlib import Path
import time
from urllib.request import urlopen


def read(origin: str, path: str) -> dict:
    with urlopen(origin.rstrip("/") + path, timeout=60) as response:
        return json.load(response)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--origin", default="https://livemap-demo.onrender.com")
    parser.add_argument("--output", type=Path, default=Path("monitor-result.json"))
    args = parser.parse_args()
    result = {"origin": args.origin, "checked_at": time.time(), "attempts": []}
    for attempt in range(3):
        start = time.monotonic()
        try:
            ready = read(args.origin, "/api/v1/health/ready")
            cameras = read(args.origin, "/api/v1/health/cameras")
            catalog = read(args.origin, "/api/v1/places?bbox=19,41,180,82&zoom=3")
            assert ready["status"] == "ok", "Database readiness failed"
            assert cameras["status"] == "ok", "No current stream or camera worker checks are stale"
            assert catalog["clusters"] or catalog["points"], "Public map is empty"
            result.update(status="ok", cameras=cameras, duration_seconds=round(time.monotonic() - start, 3))
            break
        except Exception as exc:
            result["attempts"].append({"number": attempt + 1, "error": str(exc), "duration_seconds": round(time.monotonic() - start, 3)})
            result["status"] = "failed"
            if attempt < 2:
                time.sleep(30)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    if result["status"] != "ok":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
