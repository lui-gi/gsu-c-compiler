import os

MAX_CODE_SIZE_BYTES  = 50_000   # 50 KB source limit
MAX_OUTPUT_BYTES     = 65_536   # 64 KB output cap
CONTAINER_MEMORY_MB  = int(os.getenv("MEMORY_MB", "64"))     # hard memory limit
CONTAINER_CPU_QUOTA  = 0.5                                    # half a CPU core
CONTAINER_PIDS_LIMIT = 32                                     # fork bomb prevention
COMPILE_TIMEOUT_S    = int(os.getenv("TIMEOUT_SECONDS", "10"))  # gcc wall time
EXEC_TIMEOUT_S       = 5                                      # binary wall time
API_RATE_LIMIT       = f"{os.getenv('RATE_LIMIT', '10')}/minute"
SANDBOX_IMAGE        = "gcc-sandbox:latest"
ALLOWED_ORIGINS      = os.getenv("ALLOWED_ORIGINS", "*").split(",")
