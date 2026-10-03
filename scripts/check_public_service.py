"""External smoke check; handles one Free service cold start without hiding failures."""

import argparse
import json
from pathlib import Path
import time
from urllib.request import urlopen


def read(origin: str, path: str) -> dict:
    with urlopen(origin.rstrip("/") + path, timeout=60) as response:
        return json.load(response)


def check(origin: str, *, attempts: int = 3, delay: float = 30) -> dict:
    result = {"origin": origin, "checked_at": time.time(), "attempts": []}
    for attempt in range(attempts):
        start = time.monotonic()
        try:
            latencies = {}
            def sample(path):
                started = time.monotonic()
                body = read(origin, path)
                latencies[path.split("?")[0]] = round(time.monotonic() - started, 3)
                return body
            ready = sample("/api/v1/health/ready")
            cameras = sample("/api/v1/health/cameras")
            catalog = sample("/api/v1/places?bbox=19,41,180,82&zoom=3")
            if ready.get("status") != "ok":
                raise ValueError("Database readiness failed")
            if cameras.get("status") != "ok":
                raise ValueError("No current stream or camera worker checks are stale")
            if not (catalog.get("clusters") or catalog.get("points")):
                raise ValueError("Public map is empty")
            result.update(status="ok", cameras=cameras, latency_seconds=latencies, duration_seconds=round(time.monotonic() - start, 3))
            break
        except Exception as exc:
            result["attempts"].append({"number": attempt + 1, "error": str(exc), "duration_seconds": round(time.monotonic() - start, 3)})
            result["status"] = "failed"
            if attempt < attempts - 1:
                time.sleep(delay)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--origin", default="https://livemap-demo.onrender.com")
    parser.add_argument("--output", type=Path, default=Path("monitor-result.json"))
    args = parser.parse_args()
    result = check(args.origin)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    if result["status"] != "ok":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
