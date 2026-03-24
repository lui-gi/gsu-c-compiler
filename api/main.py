from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import hashlib
import logging

from config import MAX_CODE_SIZE_BYTES, API_RATE_LIMIT
from sandbox import run_in_sandbox

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

limiter = Limiter(key_func=get_remote_address)

app = FastAPI(title="GSU C Compiler Service")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)


class CompileRequest(BaseModel):
    code: str

    @field_validator("code")
    @classmethod
    def code_size(cls, v: str) -> str:
        if len(v.encode()) > MAX_CODE_SIZE_BYTES:
            raise ValueError(f"Source code exceeds {MAX_CODE_SIZE_BYTES} bytes")
        return v


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/compile")
@limiter.limit(API_RATE_LIMIT)
async def compile_code(request: Request, body: CompileRequest):
    code_hash = hashlib.sha256(body.code.encode()).hexdigest()[:12]
    logger.info("compile request ip=%s hash=%s", request.client.host, code_hash)

    result = run_in_sandbox(body.code)

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
