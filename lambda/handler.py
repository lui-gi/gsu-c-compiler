import json
import os
import shutil
import subprocess
import time
import uuid

MAX_OUTPUT_BYTES  = 65_536   # 64 KB output cap
COMPILE_TIMEOUT_S = int(os.getenv("COMPILE_TIMEOUT_S", "10"))
EXEC_TIMEOUT_S    = 5

# SECURITY NOTE: Unlike the Docker-per-request sandbox (--network=none),
# Lambda functions have outbound internet access by default. Student-submitted
# code CAN make network requests. Mitigations in place:
#   1. Reserved concurrency limit (set in deploy.sh) caps blast radius.
#   2. API rate limiting (slowapi, 10 req/min per IP) limits submission rate.
#   3. All invocations are logged to CloudWatch for audit.
# To fully restore network isolation, deploy this Lambda inside a private VPC
# subnet with no NAT gateway (requires VPC setup, adds ~$32/month for NAT).


def handler(event, context):
    code = event.get("code", "")
    if not isinstance(code, str):
        return _error_result("invalid payload: 'code' must be a string", 0)

    job_id  = str(uuid.uuid4())
    workdir = f"/tmp/{job_id}"
    os.makedirs(workdir, exist_ok=True)
    src    = os.path.join(workdir, "main.c")
    binary = os.path.join(workdir, "a.out")

    try:
        with open(src, "w") as f:
            f.write(code)

        start = time.monotonic()

        # Phase 1: Compile
        try:
            compile_proc = subprocess.run(
                ["gcc", src, "-o", binary, "-Wall", "-Wextra"],
                capture_output=True,
                timeout=COMPILE_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired:
            return _error_result("compile_timeout", int((time.monotonic() - start) * 1000))

        if compile_proc.returncode != 0:
            compile_error = compile_proc.stderr[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace")
            return {
                "stdout":        "",
                "stderr":        "",
                "exit_code":     compile_proc.returncode,
                "compile_error": compile_error,
                "elapsed_ms":    int((time.monotonic() - start) * 1000),
            }

        # Phase 2: Execute
        try:
            run_proc = subprocess.run(
                [binary],
                capture_output=True,
                timeout=EXEC_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            return {
                "stdout":        "",
                "stderr":        "",
                "exit_code":     124,   # matches coreutils timeout convention
                "compile_error": None,
                "elapsed_ms":    elapsed_ms,
                "error":         "exec_timeout",
            }

        elapsed_ms = int((time.monotonic() - start) * 1000)
        return {
            "stdout":        run_proc.stdout[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace"),
            "stderr":        run_proc.stderr[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace"),
            "exit_code":     run_proc.returncode,
            "compile_error": None,
            "elapsed_ms":    elapsed_ms,
        }

    finally:
        # Always clean up — Lambda reuses execution environments across warm
        # invocations, so /tmp (512 MB) would fill up without explicit cleanup.
        shutil.rmtree(workdir, ignore_errors=True)


def _error_result(error: str, elapsed_ms: int) -> dict:
    return {
        "stdout":        "",
        "stderr":        "",
        "exit_code":     -1,
        "compile_error": None,
        "elapsed_ms":    elapsed_ms,
        "error":         error,
    }
