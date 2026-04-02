# gsu-c-compiler

A web-based C compiler for Georgia State University's CS curriculum, specifically CSC 3320. Students write C code in the browser, the server compiles and runs it in a sandboxed environment, and output streams back in real time through an interactive terminal.

## Quick Start (Local)

```bash
# 1. Build and start everything
docker compose up --build

# 2. Open the editor
open http://localhost:3000
```

The editor is at `http://localhost:3000`. Write C code, press **Run** (or `Ctrl+Enter`), and interact with the terminal directly — programs that use `scanf` will prompt for input in real time.

## Architecture

Two execution paths exist:

**WebSocket path (interactive terminal)** — used by the browser UI:
```
Browser (CodeMirror + xterm.js)
  → Nginx (port 3000)
  → FastAPI /ws/compile (WebSocket)
      ├─ gcc main.c -o a.out   (compile phase, 10s timeout)
      └─ ./a.out               (execution phase, 120s wall clock / 5s CPU)
  ← stdout/stderr streamed back in real time
  ← stdin forwarded from terminal keystrokes
```

**HTTP path (REST)** — used for scripting/curl:
```
POST /compile  {code, stdin}
  → FastAPI
  → AWS Lambda (gcc-sandbox)  [optional, requires deploy.sh]
  → {stdout, stderr, exit_code, compile_error, elapsed_ms}
```

## Project Structure

```
/
  /api          # FastAPI backend (WebSocket compile, HTTP compile, rate limiting)
  /lambda       # Lambda container image (GCC + Python handler) — optional
  /frontend     # Single-page CodeMirror + xterm.js editor (index.html + nginx.conf)
  deploy.sh     # ECR push + Lambda create/update script
  docker-compose.yml
```

## Environment Configuration

```bash
cp .env.example .env
```

| Variable | Default | Description |
|---|---|---|
| `TIMEOUT_SECONDS` | `10` | GCC compile timeout |
| `MEMORY_MB` | `64` | Container memory limit |
| `RATE_LIMIT` | `10` | Requests/minute per IP |
| `ALLOWED_ORIGINS` | `*` | CORS origins |
| `LAMBDA_FUNCTION_NAME` | `gcc-sandbox` | Lambda function name (HTTP path only) |
| `AWS_REGION` | `us-east-1` | AWS region (HTTP path only) |

## Manual API Testing

```bash
curl http://localhost:8000/health

curl -X POST http://localhost:8000/compile \
  -H 'Content-Type: application/json' \
  -d '{"code":"#include <stdio.h>\nint main(){printf(\"hello\\n\");return 0;}"}'
```

## Lambda Deployment (Optional)

The HTTP `/compile` endpoint can route to AWS Lambda for an additional layer of isolation. This is optional — the WebSocket terminal runs GCC directly in the API container.

```bash
# Deploy the Lambda function (requires AWS CLI configured)
./deploy.sh
```

On EC2 with an IAM instance profile, leave `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` blank — boto3 picks up credentials from the instance metadata service automatically.

## Security

- Rate limited to 10 requests/minute per IP (configurable)
- WebSocket execution: `RLIMIT_AS` (64 MB), `RLIMIT_CPU` (5s), `RLIMIT_NPROC` (32)
- Lambda reserved concurrency capped at 10 (set by `deploy.sh`)
- All Lambda invocations logged to CloudWatch
- **Network (Lambda):** Lambda functions have outbound internet access by default. To fully isolate, deploy inside a private VPC subnet with no NAT gateway (adds ~$32/month).
