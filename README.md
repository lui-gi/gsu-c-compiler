# gsu-c-compiler

A web-based C compiler for Georgia State University's CS curriculum, specifically CSC 3320. Students submit C source code in the browser, the server compiles and runs it in an isolated sandbox, and returns the output.

## Architecture

This project uses **AWS Lambda** as the compilation sandbox — each request invokes a fresh Lambda function that runs GCC inside a container image stored in ECR. The FastAPI backend calls Lambda synchronously via boto3 and returns the result as JSON. The frontend never touches the compiler directly.

```
Browser (CodeMirror)
  → Nginx (port 3000)
  → FastAPI API (port 8000)
  → AWS Lambda (gcc-sandbox)
      ├─ gcc main.c -o a.out   (compile phase, 10s timeout)
      └─ ./a.out               (execution phase, 5s timeout)
  → {stdout, stderr, exit_code, elapsed_ms}
```

## Project Structure

```
/
  /api          # FastAPI backend (compile endpoint, Lambda invoker)
  /lambda       # Lambda container image (GCC + Python handler)
  /frontend     # Single-page CodeMirror editor
  deploy.sh     # ECR push + Lambda create/update script
  docker-compose.yml
```

## Quick Start

```bash
# 1. Deploy the Lambda function (requires AWS CLI configured)
./deploy.sh

# 2. Configure environment
cp .env.example .env
# Edit .env: set LAMBDA_FUNCTION_NAME and AWS_REGION

# 3. Start the API and frontend
docker compose up

# 4. Open the editor
open http://localhost:3000
```

On EC2 with an IAM instance profile, leave `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` blank — boto3 picks up credentials from the metadata service automatically.

## Security

- Rate limited to 10 requests/minute per IP
- Lambda reserved concurrency capped at 10 (set by `deploy.sh`)
- All invocations logged to CloudWatch for audit
- **Network access:** Unlike the previous Docker sandbox (`--network=none`), Lambda functions have outbound internet access by default. Student code can make network requests. To fully restore network isolation, deploy the Lambda function inside a private VPC subnet with no NAT gateway (adds ~$32/month for a NAT gateway — out of scope for a single course).
