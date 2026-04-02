import json
import time

import boto3
from botocore.config import Config

from config import (
    MAX_OUTPUT_BYTES,
    COMPILE_TIMEOUT_S,
    EXEC_TIMEOUT_S,
    LAMBDA_FUNCTION_NAME,
    LAMBDA_REGION,
)

# boto3 read timeout must exceed the Lambda function timeout so the HTTP
# connection is not dropped before the function has a chance to respond.
_LAMBDA_TIMEOUT_S  = COMPILE_TIMEOUT_S + EXEC_TIMEOUT_S + 5
_BOTO3_READ_TIMEOUT = _LAMBDA_TIMEOUT_S + 10

_lambda_client = boto3.client(
    "lambda",
    region_name=LAMBDA_REGION,
    config=Config(
        read_timeout=_BOTO3_READ_TIMEOUT,
        connect_timeout=5,
        retries={"max_attempts": 0},  # never silently retry a timed-out invocation
    ),
)


def run_in_sandbox(code: str, stdin: str = "") -> dict:
    """
    Invoke the Lambda compiler function synchronously and return a result dict
    with keys: stdout, stderr, exit_code, compile_error, elapsed_ms.
    """
    payload = json.dumps({"code": code, "stdin": stdin}).encode()

    start = time.monotonic()
    try:
        response = _lambda_client.invoke(
            FunctionName=LAMBDA_FUNCTION_NAME,
            InvocationType="RequestResponse",
            Payload=payload,
        )
        elapsed_ms = int((time.monotonic() - start) * 1000)

        # FunctionError is set when Lambda's runtime or the handler itself
        # threw an unhandled exception (distinct from a non-zero gcc/binary exit).
        if response.get("FunctionError"):
            raw = response["Payload"].read().decode("utf-8", errors="replace")
            return _error_result(f"lambda_error: {raw}", elapsed_ms)

        result = json.loads(response["Payload"].read())

        # Defence-in-depth: cap output size on the API side as well.
        for key in ("stdout", "stderr"):
            if isinstance(result.get(key), str):
                result[key] = result[key][:MAX_OUTPUT_BYTES]

        result.setdefault("elapsed_ms", elapsed_ms)
        return result

    except Exception as exc:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return _error_result(str(exc), elapsed_ms)


def _error_result(error: str, elapsed_ms: int) -> dict:
    return {
        "stdout":        "",
        "stderr":        "",
        "exit_code":     -1,
        "compile_error": None,
        "elapsed_ms":    elapsed_ms,
        "error":         error,
    }
