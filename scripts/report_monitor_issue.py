"""Optional GitHub incident delivery; enable LIVEMAP_MONITOR_ISSUES explicitly.

Only opens/closes the monitor's own incident. Unchanged failures stay quiet.
"""

import argparse
import json
import os
from pathlib import Path
from urllib.request import Request, urlopen

TITLE = "[LiveMap monitor] Public service unavailable"
MARKER = "<!-- livemap-public-monitor -->"


def reconcile(healthy, issues, request, run_url):
    incidents = [item for item in issues if item.get("title") == TITLE
                 and MARKER in (item.get("body") or "") and not item.get("pull_request")]
    if healthy:
        for item in incidents:
            request("PATCH", f"/issues/{item['number']}", {"state": "closed", "state_reason": "completed",
                    "body": item["body"] + f"\n\nRecovered: {run_url}"})
    elif not incidents:
        request("POST", "/issues", {"title": TITLE, "body": MARKER +
                f"\n\nReadiness, public catalog or camera freshness check failed.\n\nRun and diagnostic artifact: {run_url}"})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--result", type=Path, default=Path("monitor-result.json"))
    args = parser.parse_args()
    repository = os.environ["GITHUB_REPOSITORY"]
    token = os.environ["GITHUB_TOKEN"]
    run_url = f"https://github.com/{repository}/actions/runs/{os.environ['GITHUB_RUN_ID']}"

    def request(method, path, body=None):
        headers = {"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json",
                   "X-GitHub-Api-Version": "2022-11-28", "Content-Type": "application/json"}
        data = json.dumps(body).encode() if body is not None else None
        with urlopen(Request(f"https://api.github.com/repos/{repository}" + path,
                             data=data, headers=headers, method=method), timeout=30) as response:
            return json.load(response)

    issues = []
    page = 1
    while True:
        batch = request("GET", f"/issues?state=open&per_page=100&page={page}")
        issues.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    try:
        result = json.loads(args.result.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        result = {}
    healthy = result.get("status") == "ok" and os.environ.get("HEALTH_OUTCOME") == "success"
    reconcile(healthy, issues, request, run_url)


if __name__ == "__main__":
    main()
