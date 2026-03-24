# gsu-c-compiler

A web-based C compiler for Georgia State University's CS curriculum, specifically CSC 3320. Students submit C source code in the browser, the server compiles and runs it in an isolated sandbox, and returns the output.

## Architecture

This project uses a **Docker-per-request** sandbox model — each compilation runs in a fresh, ephemeral container with hard resource limits and no network access. See [architecture.md](./architecture.md) for the full design, alternative architectures considered, and the multi-terminal implementation plan.

## Project Structure

```
/
  /api               # FastAPI backend (compile endpoint, sandbox runner)
  /sandbox-image     # Hardened gcc:alpine Docker image
  /frontend          # Single-page CodeMirror editor
  docker-compose.yml
  architecture.md    # Full architecture decision record
```

## Quick Start

```bash
# Build the sandbox image
docker build -t gcc-sandbox:latest ./sandbox-image

# Start the API and frontend
docker compose up

# Open the editor
open http://localhost:3000
```

## Security

- Each request runs in a container with `--memory 64m`, `--pids-limit 32`, `--network none`, and `--cap-drop ALL`
- Rate limited to 10 requests/minute per IP
- Requires rootless Docker on the host (`dockerd --rootless`)
