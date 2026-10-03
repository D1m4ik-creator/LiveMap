"""Local protocol test, using a generated test pattern (not a catalog camera).

Requires MediaMTX 1.21.1 and FFmpeg with libx264. Never contacts a camera owner.
Starts isolated loopback publishers and the same gateway launcher used in deployment.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import signal
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen


ORIGIN = "http://127.0.0.1:4173"
BASE = "http://127.0.0.1:18888/camera1/"


def get(path="index.m3u8", origin=ORIGIN):
    with urlopen(Request(urljoin(BASE, path), headers={"Origin": origin}), timeout=25) as response:
        return response.read(), response.headers


def playlist():
    text, headers = get()
    assert headers.get("Access-Control-Allow-Origin") == ORIGIN
    lines = text.decode().splitlines()
    path = next(line for line in lines if line and not line.startswith("#"))
    if path.split("?", 1)[0].endswith(".m3u8"):
        text, headers = get(path)
    assert b"#EXTINF" in text
    return text, headers


def wait_ready():
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        try:
            return playlist()
        except (HTTPError, URLError, AssertionError, TimeoutError):
            time.sleep(1)
    raise RuntimeError("Gateway did not produce a media playlist")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mediamtx", required=True)
    parser.add_argument("--ffmpeg", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--hold", action="store_true", help="Keep gateway running for browser acceptance; Ctrl+C stops it")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    children = []
    report = {"fixture": "generated H264 test pattern; not a real street camera", "checks": []}
    with tempfile.TemporaryDirectory(prefix="livemap-rtsp-test-") as directory:
        publisher_path = Path(directory) / "publisher.json"
        publisher_path.write_text(json.dumps({
            "rtsp": True, "rtspAddress": "127.0.0.1:18554", "rtspTransports": ["tcp"],
            "hls": False, "webrtc": False, "rtmp": False, "srt": False, "moq": False,
            "paths": {"fixture": {"source": "publisher"}},
        }), encoding="utf-8")
        def start_pattern():
            return subprocess.Popen([
                args.ffmpeg, "-hide_banner", "-loglevel", "error", "-re", "-f", "lavfi", "-i",
                "testsrc2=size=640x360:rate=25", "-an", "-c:v", "libx264", "-preset", "ultrafast",
                "-tune", "zerolatency", "-pix_fmt", "yuv420p", "-g", "25", "-b:v", "800k",
                "-f", "rtsp", "-rtsp_transport", "tcp", "rtsp://127.0.0.1:18554/fixture",
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        log_path = Path(args.report).with_suffix(".log")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("w", encoding="utf-8") as log:
            gateway = None
            try:
                publisher = subprocess.Popen([args.mediamtx, str(publisher_path)], stdout=log, stderr=log)
                children.append(publisher)
                time.sleep(1)
                pattern = start_pattern()
                children.append(pattern)
                env = {**os.environ, "LIVEMAP_RTSP_UPSTREAM": "rtsp://127.0.0.1:18554/fixture",
                       "LIVEMAP_RTSP_ALLOWED_HOST": "127.0.0.1", "PUBLIC_ORIGIN": ORIGIN, "PORT": "18888"}
                gateway = subprocess.Popen([sys.executable, str(root / "deploy/media/gateway.py"),
                                            "--binary", args.mediamtx, "--local-test"],
                                           env=env, stdout=log, stderr=log,
                                           creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0)
                children.append(gateway)
                time.sleep(1)
                if gateway.poll() is not None or publisher.poll() is not None or pattern.poll() is not None:
                    raise RuntimeError("A test process failed; check for occupied ports")
                text, _ = wait_ready()
                report["checks"].append("RTSP TCP -> HLS fMP4, exact-origin CORS")
                segment = next(line for line in reversed(text.decode().splitlines())
                               if line and not line.startswith("#"))
                assert len(get(segment)[0]) > 0
                assert get(origin="https://unapproved.example")[1].get("Access-Control-Allow-Origin") != "https://unapproved.example"
                report["checks"].append("media segment delivered; unapproved origin is not granted CORS")
                def viewer(_):
                    return len(get(segment)[0])
                began = time.monotonic()
                with ThreadPoolExecutor(max_workers=20) as pool:
                    sizes = list(pool.map(viewer, range(20)))
                assert all(size > 0 for size in sizes)
                report["parallel_segment_requests"] = 20
                report["parallel_seconds"] = round(time.monotonic() - began, 3)
                report["checks"].append("20 simultaneous HTTP segment requests; not 20 long-running players")
                pattern.terminate()
                pattern.wait(timeout=10)
                time.sleep(3)
                pattern = start_pattern()
                children.append(pattern)
                time.sleep(2)
                assert pattern.poll() is None
                wait_ready()
                report["checks"].append("upstream interruption and restart recovered")
                Path(args.report).write_text(json.dumps(report, indent=2), encoding="utf-8")
                print(json.dumps(report), flush=True)
                if args.hold:
                    print(f"Browser fixture: {BASE}index.m3u8", flush=True)
                    while True:
                        if pattern.poll() is not None:
                            pattern = start_pattern()
                            children.append(pattern)
                        time.sleep(1)
                else:
                    deadline = time.monotonic() + 90
                    while time.monotonic() < deadline:
                        log.flush()
                        if "not needed by anyone" in log_path.read_text(encoding="utf-8"):
                            break
                        time.sleep(1)
                    report["idle_upstream_closed"] = "not needed by anyone" in log_path.read_text(encoding="utf-8")
                    assert report["idle_upstream_closed"]
                    Path(args.report).write_text(json.dumps(report, indent=2), encoding="utf-8")
            except KeyboardInterrupt:
                pass
            finally:
                for child in reversed(children):
                    if child.poll() is None:
                        if child is gateway and os.name == "nt":
                            child.send_signal(signal.CTRL_BREAK_EVENT)
                        else:
                            child.terminate()
                        try:
                            child.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            child.kill()
                            child.wait()


if __name__ == "__main__":
    main()
