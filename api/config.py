import os

MAX_CODE_SIZE_BYTES  = 50_000   # 50 KB source limit
MAX_OUTPUT_BYTES     = 65_536   # 64 KB output cap
COMPILE_TIMEOUT_S    = int(os.getenv("TIMEOUT_SECONDS", "10"))
EXEC_TIMEOUT_S       = 5
API_RATE_LIMIT       = f"{os.getenv('RATE_LIMIT', '10')}/minute"
ALLOWED_ORIGINS      = os.getenv("ALLOWED_ORIGINS", "*").split(",")

# AWS Lambda target
LAMBDA_FUNCTION_NAME = os.getenv("LAMBDA_FUNCTION_NAME", "gcc-sandbox")
LAMBDA_REGION        = os.getenv("AWS_REGION", "us-east-1")
