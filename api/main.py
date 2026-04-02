import asyncio
import contextlib
import os
import resource
import shutil
import uuid

from fastapi import FastAPI, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import hashlib
import logging

from config import MAX_CODE_SIZE_BYTES, MAX_STDIN_BYTES, COMPILE_TIMEOUT_S, EXEC_TIMEOUT_S, API_RATE_LIMIT, ALLOWED_ORIGINS
from sandbox import run_in_sandbox

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

limiter = Limiter(key_func=get_remote_address)

app = FastAPI(title="GSU C Compiler Service")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)


class CompileRequest(BaseModel):
    code: str
    stdin: str = ""

    @field_validator("code")
    @classmethod
    def code_size(cls, v: str) -> str:
        if len(v.encode()) > MAX_CODE_SIZE_BYTES:
            raise ValueError(f"Source code exceeds {MAX_CODE_SIZE_BYTES} bytes")
        return v

    @field_validator("stdin")
    @classmethod
    def stdin_size(cls, v: str) -> str:
        if len(v.encode()) > MAX_STDIN_BYTES:
            raise ValueError(f"stdin exceeds {MAX_STDIN_BYTES} bytes")
        return v


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/compile")
@limiter.limit(API_RATE_LIMIT)
async def compile_code(request: Request, body: CompileRequest):
    code_hash = hashlib.sha256(body.code.encode()).hexdigest()[:12]
    logger.info("compile request ip=%s hash=%s", request.client.host, code_hash)

    result = run_in_sandbox(body.code, body.stdin)

    logger.info(
        "compile result hash=%s exit_code=%s elapsed_ms=%s",
        code_hash,
        result.get("exit_code"),
        result.get("elapsed_ms"),
    )
    return result


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    return JSONResponse(status_code=413, content={"error": str(exc)})


async def _pump_output(websocket: WebSocket, proc: asyncio.subprocess.Process) -> None:
    try:
        while True:
            chunk = await proc.stdout.read(4096)
            if not chunk:
                break
            await websocket.send_bytes(chunk)
    except Exception:
        pass


async def _pump_input(websocket: WebSocket, proc: asyncio.subprocess.Process) -> None:
    try:
        while True:
            msg = await websocket.receive()
            if msg.get("type") == "websocket.disconnect":
                break
            data = msg.get("bytes") or (msg.get("text") or "").encode("utf-8")
            if data:
                proc.stdin.write(data)
                await proc.stdin.drain()
    except Exception:
        pass
    finally:
        with contextlib.suppress(Exception):
            proc.stdin.close()
        if proc.returncode is None:
            with contextlib.suppress(Exception):
                proc.kill()


@app.websocket("/ws/compile")
async def ws_compile(websocket: WebSocket):
    await websocket.accept()

    try:
        payload = await asyncio.wait_for(websocket.receive_json(), timeout=10.0)
    except Exception:
        await websocket.close(code=1008)
        return

    code = payload.get("code", "")
    if not isinstance(code, str) or len(code.encode()) > MAX_CODE_SIZE_BYTES:
        await websocket.send_text("\r\n\x1b[31mError: invalid or oversized code\x1b[0m\r\n")
        await websocket.close()
        return

    job_id = str(uuid.uuid4())
    workdir = f"/tmp/ws_{job_id}"
    os.makedirs(workdir, exist_ok=True)
    src = os.path.join(workdir, "main.c")
    binary = os.path.join(workdir, "a.out")

    try:
        with open(src, "w") as f:
            f.write(code)

        # ── Phase 1: Compile ────────────────────────────────
        await websocket.send_text("\x1b[2mCompiling…\x1b[0m\r\n")

        compile_proc = await asyncio.create_subprocess_exec(
            "gcc", src, "-o", binary, "-Wall", "-Wextra",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, stderr_data = await asyncio.wait_for(
                compile_proc.communicate(), timeout=COMPILE_TIMEOUT_S
            )
        except asyncio.TimeoutError:
            compile_proc.kill()
            await websocket.send_text("\r\n\x1b[31mCompile timeout\x1b[0m\r\n")
            await websocket.close()
            return

        if compile_proc.returncode != 0:
            err = stderr_data.decode("utf-8", errors="replace").replace("\n", "\r\n")
            await websocket.send_text("\x1b[31m" + err + "\x1b[0m")
            await websocket.close()
            return

        # ── Phase 2: Execute ────────────────────────────────
        def _set_limits():
            resource.setrlimit(resource.RLIMIT_AS,    (64 * 1024 * 1024, 64 * 1024 * 1024))
            resource.setrlimit(resource.RLIMIT_CPU,    (EXEC_TIMEOUT_S, EXEC_TIMEOUT_S + 1))
            resource.setrlimit(resource.RLIMIT_NPROC,  (32, 32))

        WALL_TIMEOUT_S = 120  # interactive programs may wait for user input

        proc = await asyncio.create_subprocess_exec(
            binary,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            preexec_fn=_set_limits,
        )

        output_task = asyncio.create_task(_pump_output(websocket, proc))
        input_task  = asyncio.create_task(_pump_input(websocket, proc))

        try:
            await asyncio.wait_for(output_task, timeout=WALL_TIMEOUT_S)
        except asyncio.TimeoutError:
            proc.kill()
            with contextlib.suppress(Exception):
                await websocket.send_text("\r\n\x1b[33m[exec timeout]\x1b[0m\r\n")
        finally:
            input_task.cancel()
            await asyncio.gather(input_task, return_exceptions=True)

        rc = await proc.wait()
        color = "\x1b[32m" if rc == 0 else "\x1b[31m"
        with contextlib.suppress(Exception):
            await websocket.send_text(f"\r\n{color}[exit {rc}]\x1b[0m\r\n")
            await websocket.close()

    finally:
        shutil.rmtree(workdir, ignore_errors=True)
