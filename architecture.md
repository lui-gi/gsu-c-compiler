# University Web-Based C Compiler Service

## Overview

A web service where students and faculty submit C source code via a browser, the server compiles and runs it, and returns stdout/stderr. Primary concerns: security (arbitrary code execution), simplicity (student-maintainable), and easy deployment on a university VM.

---

## Architecture Options

| Option | Isolation | Complexity | Best For |
|---|---|---|---|
| **1. Monolith + firejail/seccomp** | Medium (host-level) | Low | Prototyping only |
| **2. Docker-per-request** | High (namespace+cgroups) | Medium | **← Recommended** |
| **3. Microservices (API + queue + workers)** | High | High | Production at scale |
| **4. Serverless (Lambda/Cloud Run)** | High (platform) | Medium-High | Vendor-managed infra |

### Option 1: Monolith + firejail/seccomp
A single Python/Flask/FastAPI server receives code, writes it to a temp dir, runs `gcc` via subprocess, and executes the binary under `firejail` or `seccomp-bpf` rules.

- **Pro:** Dead simple (~300 LOC), no container overhead, runs on a $5–10/month VPS
- **Con:** `gcc` itself runs unsandboxed. Seccomp profiles are subtle — a misconfiguration means arbitrary code runs on the host. Bad for projects with rotating student maintainers.

### Option 2: Docker-per-request (Recommended)
A thin API server spawns a fresh Docker container per request using a hardened `gcc:alpine` image. The container is destroyed after the run completes.

- **Pro:** Strong, well-understood isolation (Linux namespaces + cgroups). Both compilation *and* execution are sandboxed. Security policy fits in one `docker run` command anyone can audit. One-command deploy.
- **Con:** ~300–800ms container startup per request (imperceptible for interactive use).

### Option 3: Microservices
Separate services: public API → Redis/RabbitMQ queue → compiler worker pods → result store.

- **Pro:** Scales horizontally, handles burst load gracefully, clean separation of concerns
- **Con:** Over-engineered for a ~30-student university tool. Adds Redis, queues, polling/WebSockets, and multi-service ops overhead for no practical benefit at this scale.

### Option 4: Serverless (Lambda / Cloud Run)
Cloud function compiles and runs code inside a platform-managed MicroVM sandbox.

- **Pro:** Zero server management, Firecracker-grade isolation, auto-scaling
- **Con:** GCC is not natively available in Lambda — requires a custom 50–100 MB layer. Vendor lock-in. Local debugging is painful. Cost is unpredictable when students submit infinite loops.

---

## Recommended Architecture: Docker-Per-Request

### Why This One

Architecture 2 wins on three axes that matter most for a university project:

1. **Security is strong and auditable.** The isolation is built from standard Linux primitives (namespaces + cgroups) expressed directly in `docker run` flags. Any CS student can read `--memory 64m --pids-limit 32 --network none --cap-drop ALL` and immediately understand the policy. Compare that to a hand-written seccomp profile — an allow-list of ~200 syscalls that is subtle to write and invisible to future maintainers.

2. **It sandboxes everything, not just execution.** In Architecture 1, `gcc` itself runs directly on the host. A crafted source file could exploit a GCC plugin system or compiler bug. In Architecture 2, the compiler runs inside the container too.

3. **Best security-to-complexity ratio.** Architecture 3 also has strong isolation but at 3–5x the operational complexity. Architecture 4 also has strong isolation but requires vendor-specific infrastructure. Architecture 2 achieves the same isolation ceiling in ~200 LOC and one `docker run` command.

### How It Works

```
Browser (CodeMirror)
  └─ POST /compile {code: "..."}
       └─ FastAPI API Server
            └─ docker run --rm --memory 64m --cpus 0.5 --pids-limit 32 \
                          --network none --cap-drop ALL --read-only \
                          gcc-sandbox:latest
                 └─ gcc /sandbox/main.c -o /tmp/a.out && timeout 5 /tmp/a.out
                      └─ stdout/stderr → JSON response
```

### API Contract

```
POST /compile
Content-Type: application/json

{ "code": "int main() { printf(\"hello\"); return 0; }" }

200 OK
{
  "stdout": "hello",
  "stderr": "",
  "exit_code": 0,
  "compile_error": null,
  "elapsed_ms": 412
}
```

### Security Limits

```python
MAX_CODE_SIZE_BYTES  = 50_000   # 50 KB source limit
MAX_OUTPUT_BYTES     = 65_536   # 64 KB output cap
CONTAINER_MEMORY_MB  = 64       # hard memory limit
CONTAINER_CPU_QUOTA  = 0.5      # half a CPU core
CONTAINER_PIDS_LIMIT = 32       # fork bomb prevention
COMPILE_TIMEOUT_S    = 10       # gcc wall time
EXEC_TIMEOUT_S       = 5        # binary wall time
API_RATE_LIMIT       = "10/minute"
```

---

## Project Structure

```
/project
  /api
    main.py          # FastAPI routes, validation, rate limiting
    sandbox.py       # docker run wrapper with all security flags
    config.py        # all tunable security constants
    requirements.txt
  /sandbox-image
    Dockerfile       # FROM gcc:13-alpine, strip shell, non-root user
  /frontend
    index.html       # CodeMirror editor + fetch() to /compile
  docker-compose.yml
  .env.example
```

---

## Execution Flow

1. API validates code size (≤ 50 KB)
2. Write code to `tmpfs`-backed `/tmp/jobs/{uuid}/main.c`
3. `docker run --rm ... -v /tmp/jobs/{uuid}:/sandbox:ro gcc-sandbox`
   - Entrypoint: `gcc /sandbox/main.c -o /tmp/a.out && timeout 5 /tmp/a.out`
4. Capture stdout/stderr, truncate at 64 KB
5. On timeout: `docker kill sandbox-{uuid}`, return `{"error": "timeout"}`
6. Delete job directory in `finally` block
7. Return JSON response

---

## Security Checklist

- Run Docker in **rootless mode** (`dockerd --rootless`) — prevents API process from escalating to host root via the Docker socket
- Pin sandbox image to a **digest** (`gcc@sha256:...`), not a mutable tag
- Rate limit: `10 requests/minute per IP` via `slowapi`
- Strip the GCC Alpine image of `/bin/sh`, `wget`, etc. after testing
- Log every submission (hashed, not raw code) for abuse detection

---

## Deployment

**Local dev:**
```bash
docker compose up
# API on localhost:8000, frontend on localhost:3000
```

**University VM (Ubuntu 22.04, 2 vCPU / 2 GB RAM):**
1. Install rootless Docker via `dockerd-rootless-setuptool.sh`
2. `docker compose up -d`
3. Nginx reverse proxy with TLS via Let's Encrypt (`certbot`)

Handles ~10 concurrent compilations comfortably. Scale by adding a second VM with Nginx as a round-robin load balancer — no shared state to synchronize.

---

## Verification

- Submit `hello world` → expect `"stdout": "hello, world\n"`, `exit_code: 0`
- Submit infinite loop → expect timeout error after ~10s
- Submit fork bomb (`while(1) fork()`) → expect PID limit error quickly
- Submit code with `system("curl ...")` → expect network failure
- Submit oversized payload (>50 KB) → expect 413 before Docker is invoked
- Load test with 10 concurrent requests → all return within 2s

---

## Multi-Terminal Work Split

The project divides into 3 independent workstreams. Start Terminals 1 and 3 in parallel; Terminal 2 can begin once Terminal 1 has a working image.

### Terminal 1 — Sandbox Image
**Owns:** `sandbox-image/Dockerfile`

Paste this prompt:
```
Build a hardened Docker image for a C compiler sandbox.
- Base: gcc:13-alpine
- Multi-stage build: final stage strips /bin/sh, wget, and package manager
- Add a non-root user `sandbox` (uid 1001)
- Entrypoint: compile /sandbox/main.c to /tmp/a.out, then run it with `timeout 5`
- Verify the image builds and a hello-world program compiles and runs inside it
Save the result to sandbox-image/Dockerfile.
```

---

### Terminal 2 — Backend API
**Owns:** `api/config.py`, `api/sandbox.py`, `api/main.py`, `api/requirements.txt`

**Depends on:** Terminal 1 producing a working image tagged `gcc-sandbox:latest`

Paste this prompt:
```
Build the FastAPI backend for a university C compiler web service (Docker-per-request architecture).

Create these files:
- api/config.py: constants MAX_CODE_SIZE_BYTES=50000, MAX_OUTPUT_BYTES=65536,
  CONTAINER_MEMORY_MB=64, CONTAINER_CPU_QUOTA=0.5, CONTAINER_PIDS_LIMIT=32,
  COMPILE_TIMEOUT_S=10, EXEC_TIMEOUT_S=5, API_RATE_LIMIT="10/minute"
- api/sandbox.py: function run_in_sandbox(code: str) -> dict that writes code to a
  tmpfs-backed temp dir, calls `docker run --rm --memory 64m --cpus 0.5 --pids-limit 32
  --network none --cap-drop ALL --read-only --security-opt no-new-privileges
  -v {tmpdir}:/sandbox:ro gcc-sandbox:latest`, captures stdout/stderr truncated at
  MAX_OUTPUT_BYTES, handles timeout by calling `docker kill`, cleans up in finally block
- api/main.py: FastAPI app with POST /compile, input size validation, slowapi rate
  limiting, returns {stdout, stderr, exit_code, compile_error, elapsed_ms}
- api/requirements.txt: fastapi, uvicorn, slowapi, docker
```

---

### Terminal 3 — Frontend + Compose
**Owns:** `frontend/index.html`, `docker-compose.yml`, `.env.example`

**Can run in parallel with Terminal 2.**

Paste this prompt:
```
Build the frontend and docker-compose setup for a university C compiler web service.

1. frontend/index.html: single-page app with CodeMirror 6 (loaded from CDN, no build
   step) pre-loaded with a hello-world C template, a "Run" button that POSTs to
   /compile, and a read-only output panel showing stdout, stderr, and exit code.

2. docker-compose.yml: two services:
   - api: builds from ./api (python:3.12-slim), exposes port 8000,
     bind-mounts /var/run/docker.sock, mounts /tmp as tmpfs
   - frontend: serves frontend/ via nginx:alpine on port 3000

3. .env.example: TIMEOUT_SECONDS=10, MEMORY_MB=64, RATE_LIMIT=10
```

---

### Integration Order

1. Terminal 1 finishes → `docker build -t gcc-sandbox:latest ./sandbox-image`
2. Terminal 2 finishes → smoke-test `sandbox.py` with a hello-world call
3. Terminal 3 finishes → `docker compose up`
4. Open `http://localhost:3000`, submit hello world, verify end-to-end
