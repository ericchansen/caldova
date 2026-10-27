"""Verify the actual Linux image starts, without model calls or credentials."""

import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

with tempfile.TemporaryFile() as logs:
    process = subprocess.Popen([sys.executable, "main.py"], stdout=logs, stderr=logs)
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if process.poll() is not None:
                logs.seek(0)
                raise RuntimeError(logs.read().decode())
            try:
                with urllib.request.urlopen("http://127.0.0.1:8088/readiness", timeout=2) as response:
                    assert response.status == 200
                    print("Linux hosted server readiness verified")
                    break
            except (urllib.error.URLError, TimeoutError):
                time.sleep(1)
        else:
            logs.seek(0)
            raise RuntimeError("Server did not become ready: " + logs.read().decode())
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
