"""Launch one read-only RTSP -> HLS path; upstream stays outside the catalog."""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import tempfile
from urllib.parse import unquote, urlsplit, urlunsplit


def build_config(env: dict, *, local_test: bool = False, resolve=socket.getaddrinfo) -> dict:
    source = env.get("LIVEMAP_RTSP_UPSTREAM", "")
    parsed = urlsplit(source)
    host = parsed.hostname
    if (parsed.scheme != "rtsp" or not host or not parsed.path
            or parsed.fragment or parsed.query or "\\" in source
            or any(ord(c) < 32 for c in source)):
        raise ValueError("A fixed RTSP upstream without query/fragment is required")
    if host != env.get("LIVEMAP_RTSP_ALLOWED_HOST"):
        raise ValueError("Upstream host must match the operator allowlist")
    port = parsed.port or 554
    addresses = {row[4][0] for row in resolve(host, port, type=socket.SOCK_STREAM)}
    if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
        if not (local_test and addresses and all(ipaddress.ip_address(ip).is_loopback for ip in addresses)):
            raise ValueError("Upstream must resolve exclusively to public addresses")
    # Pin one validated address, so a subsequent DNS change cannot reach a private host.
    ip = sorted(addresses)[0]
    authority = f"[{ip}]:{port}" if ":" in ip else f"{ip}:{port}"
    credentials = parsed.netloc.rsplit("@", 1)[0] + "@" if "@" in parsed.netloc else ""
    pinned = urlunsplit(("rtsp", credentials + authority, parsed.path, "", ""))
    origin = env.get("PUBLIC_ORIGIN", "")
    public = urlsplit(origin)
    if (not public.hostname or public.username or public.password or public.query or public.fragment
            or public.path not in ("", "/") or "*" in origin
            or (public.scheme != "https" and not (
                local_test and public.scheme == "http" and public.hostname in {"localhost", "127.0.0.1"}))):
        raise ValueError("PUBLIC_ORIGIN must be one exact HTTPS origin")
    hls_port = int(env.get("PORT", "8888"))
    if not 1024 <= hls_port <= 65535:
        raise ValueError("Invalid HLS port")
    return {
        "logLevel": "info", "logDestinations": ["stdout"],
        "api": False, "metrics": False, "pprof": False, "playback": False,
        "rtsp": False, "rtmp": False, "webrtc": False, "srt": False, "moq": False,
        "hls": True, "hlsAddress": f"{'127.0.0.1' if local_test else '0.0.0.0'}:{hls_port}",
        "hlsAllowOrigins": [origin.rstrip("/")], "hlsAlwaysRemux": False,
        "hlsVariant": "fmp4", "hlsSegmentCount": 7, "hlsSegmentDuration": "1s",
        "hlsSegmentMaxSize": "8M", "hlsMuxerCloseAfter": "10s", "writeQueueSize": 256,
        "authMethod": "internal", "authInternalUsers": [
            {"user": "any", "pass": "", "ips": [],
             "permissions": [{"action": "read", "path": "camera1"}]}],
        "paths": {"camera1": {"source": pinned, "sourceOnDemand": True,
            "sourceOnDemandStartTimeout": "20s", "sourceOnDemandCloseAfter": "10s",
            "rtspTransport": "tcp", "record": False}},
    }


def redact(line: str, source: str) -> str:
    line = line.replace(source, "[upstream]")
    for value in (urlsplit(source).password, urlsplit(source).username):
        if value:
            line = line.replace(value, "[redacted]").replace(unquote(value), "[redacted]")
    return re.sub(r"rtsp://[^\s\"']+", "[upstream]", line)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", default="mediamtx")
    parser.add_argument("--local-test", action="store_true", help="Loopback-only protocol acceptance test")
    args = parser.parse_args()
    try:
        config = build_config(dict(os.environ), local_test=args.local_test)
    except (ValueError, OSError):
        print("Gateway configuration rejected; check upstream allowlist and public origin", flush=True)
        return 2
    with tempfile.TemporaryDirectory(prefix="livemap-media-") as directory:
        path = Path(directory) / "mediamtx.json"
        path.write_text(json.dumps(config), encoding="utf-8")
        path.chmod(0o600)
        # MediaMTX supports env overrides; do not permit them to reopen APIs or add paths.
        child_env = {key: value for key, value in os.environ.items()
                     if not key.startswith(("MTX_", "LIVEMAP_RTSP_"))}
        process = subprocess.Popen([args.binary, str(path)], env=child_env,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        def stop(_signum, _frame):
            process.terminate()
        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        if hasattr(signal, "SIGBREAK"):
            signal.signal(signal.SIGBREAK, stop)
        try:
            for line in process.stdout:
                print(redact(line.rstrip(), os.environ["LIVEMAP_RTSP_UPSTREAM"]), flush=True)
            return process.wait()
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


if __name__ == "__main__":
    raise SystemExit(main())
