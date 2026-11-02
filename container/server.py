"""A tiny job runner for the refresh container (port 8080, stdlib only).

POST /jobs        {"job": "...", "params": {...}} -> 202 {"id"} | 409 {"id"} if one is running | 400
GET  /jobs/<id>   -> {"state": running|ok|failed, "exit_code", "log_tail", "stdout"}

One job at a time. Output is scrubbed of the secret values in this process's environment
before it leaves the container. Started by container/Dockerfile.
"""

from __future__ import annotations

import json
import os
import subprocess  # noqa: S404  argv lists from the container/jobs.py whitelist only, never a shell string
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from jobs import commands_for

SECRET_NAMES = ("CLOUDFLARE_API_TOKEN", "CENSUS_API_KEY")
TAIL = 6000
APP_DIR = os.environ.get("APP_DIR", "/app")

_lock = threading.Lock()
_current: dict[str, Any] | None = None  # {"id", "state", "exit_code", "log", "stdout"}


def scrub(text: str) -> str:
    for name in SECRET_NAMES:
        value = os.environ.get(name, "")
        if len(value) >= 6:
            text = text.replace(value, "***")
    return text


def _run(job: dict[str, Any], commands: list[list[str]]) -> None:
    code = 0
    for argv in commands:
        proc = subprocess.run(  # noqa: S603  whitelisted argv, no shell
            argv, capture_output=True, text=True, check=False, cwd=APP_DIR
        )
        job["log"] += f"$ {' '.join(argv[2:] if argv[0].endswith('python') else argv)}\n"
        job["log"] += proc.stdout + proc.stderr
        job["stdout"] = proc.stdout
        code = proc.returncode
        if code != 0:
            break
    job["exit_code"] = code
    job["state"] = "ok" if code == 0 else "failed"


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, body: dict[str, Any]) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:  # noqa: N802
        global _current
        if self.path != "/jobs":
            return self._send(404, {"error": "not found"})
        try:
            payload = json.loads(
                self.rfile.read(int(self.headers.get("content-length", 0))) or b"{}"
            )
            commands = commands_for(str(payload.get("job")), payload.get("params") or {})
        except (ValueError, TypeError) as err:
            return self._send(400, {"error": str(err)})
        with _lock:
            if _current and _current["state"] == "running":
                return self._send(409, {"id": _current["id"]})
            job = {
                "id": uuid.uuid4().hex[:12],
                "state": "running",
                "exit_code": None,
                "log": "",
                "stdout": "",
            }
            _current = job
        threading.Thread(target=_run, args=(job, commands), daemon=True).start()
        return self._send(202, {"id": job["id"]})

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            return self._send(200, {"ok": True})
        job = _current
        if not self.path.startswith("/jobs/") or not job or self.path != f"/jobs/{job['id']}":
            return self._send(404, {"error": "unknown job"})
        return self._send(
            200,
            {
                "state": job["state"],
                "exit_code": job["exit_code"],
                "log_tail": scrub(job["log"])[-TAIL:],
                "stdout": scrub(job["stdout"]),
            },
        )

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return  # request lines carry nothing useful and the job output is returned via the API


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()  # noqa: S104  container-internal port
