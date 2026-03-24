import subprocess
import tempfile
import uuid
import os
import time
from pathlib import Path

from config import (
    MAX_OUTPUT_BYTES,
    CONTAINER_MEMORY_MB,
    CONTAINER_CPU_QUOTA,
    CONTAINER_PIDS_LIMIT,
    COMPILE_TIMEOUT_S,
    EXEC_TIMEOUT_S,
    SANDBOX_IMAGE,
)

# Total wall-clock budget: compile + exec + a small buffer
_TOTAL_TIMEOUT_S = COMPILE_TIMEOUT_S + EXEC_TIMEOUT_S + 2


def run_in_sandbox(code: str) -> dict:
    """
    Write `code` to an isolated temp directory, run it inside a hardened
    Docker container, and return a result dict with keys:
        stdout, stderr, exit_code, compile_error, elapsed_ms
    """
    job_id = str(uuid.uuid4())
    container_name = f"sandbox-{job_id}"

    with tempfile.TemporaryDirectory(prefix=f"job-{job_id}-") as tmpdir:
        src_path = Path(tmpdir) / "main.c"
        src_path.write_text(code)

        cmd = [
            "docker", "run",
            "--rm",
            "--name", container_name,
            f"--memory={CONTAINER_MEMORY_MB}m",
            f"--cpus={CONTAINER_CPU_QUOTA}",
            f"--pids-limit={CONTAINER_PIDS_LIMIT}",
            "--network=none",
            "--cap-drop=ALL",
            "--read-only",
            "--security-opt=no-new-privileges",
            "-v", f"{tmpdir}:/sandbox:ro",
            SANDBOX_IMAGE,
        ]

        start = time.monotonic()
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=_TOTAL_TIMEOUT_S,
            )
            elapsed_ms = int((time.monotonic() - start) * 1000)

            stdout = result.stdout[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace")
            stderr = result.stderr[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace")
            exit_code = result.returncode

            # gcc writes compile errors to stderr and exits non-zero before
            # producing a binary.  We surface that as compile_error.
            compile_error = None
            if exit_code != 0 and _looks_like_compile_error(stderr):
                compile_error = stderr
                stderr = ""

            return {
                "stdout": stdout,
                "stderr": stderr,
                "exit_code": exit_code,
                "compile_error": compile_error,
                "elapsed_ms": elapsed_ms,
            }

        except subprocess.TimeoutExpired:
            _kill_container(container_name)
            elapsed_ms = int((time.monotonic() - start) * 1000)
            return {
                "stdout": "",
                "stderr": "",
                "exit_code": -1,
                "compile_error": None,
                "elapsed_ms": elapsed_ms,
                "error": "timeout",
            }
        except Exception as exc:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            return {
                "stdout": "",
                "stderr": "",
                "exit_code": -1,
                "compile_error": None,
                "elapsed_ms": elapsed_ms,
                "error": str(exc),
            }


def _looks_like_compile_error(text: str) -> bool:
    """Heuristic: gcc compile errors mention 'error:' in stderr."""
    return "error:" in text or "undefined reference" in text


def _kill_container(name: str) -> None:
    try:
        subprocess.run(
            ["docker", "kill", name],
            capture_output=True,
            timeout=5,
        )
    except Exception:
        pass
