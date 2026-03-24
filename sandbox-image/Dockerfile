# ── Stage 1: build the entrypoint helper ─────────────────────────────────────
# Full gcc:13-alpine gives us a compiler to build our own shell-free entrypoint.
FROM gcc:13-alpine AS builder

WORKDIR /build
COPY entrypoint.c .

# Compile a fully static binary so it runs in a stripped final image.
RUN gcc -static -O2 -o /build/entrypoint entrypoint.c

# Create non-root user/group definitions for the final stage.
RUN addgroup -g 1001 sandbox && \
    adduser -D -u 1001 -G sandbox sandbox

# ── Stage 2: hardened runtime ─────────────────────────────────────────────────
# Start from the same gcc:13-alpine (we need gcc, libc, timeout at runtime).
FROM gcc:13-alpine AS runtime

# Bring in passwd/group so the sandbox user exists without /etc needing a shell.
COPY --from=builder /etc/passwd /etc/passwd
COPY --from=builder /etc/group  /etc/group

# Copy the compiled, static entrypoint.
COPY --from=builder /build/entrypoint /usr/local/bin/run-sandbox

# /tmp must be writable for the compiled binary.
RUN chmod 1777 /tmp

# ── Harden: strip tools that have no role after image is tested ───────────────
# Remove shells and common network / package-manager utilities.
# `|| true` avoids failures on paths that may not exist in this layer.
RUN rm -f \
        /bin/sh \
        /bin/ash \
        /bin/busybox \
        /usr/bin/wget \
        /usr/bin/curl \
        /usr/bin/nc \
        /usr/bin/ncat \
        /sbin/apk \
        /usr/bin/apk \
        /usr/bin/ssh \
        /usr/bin/scp \
        /usr/bin/sftp \
        /usr/bin/python3 \
        /usr/bin/python \
        /usr/bin/perl \
        /usr/bin/ruby \
    || true

# Drop to non-root sandbox user.
USER sandbox

# Entrypoint: compile /sandbox/main.c, then exec with a 5-second timeout.
# The /sandbox directory is mounted read-only by the API at runtime:
#   docker run -v /tmp/jobs/{uuid}:/sandbox:ro ...
ENTRYPOINT ["/usr/local/bin/run-sandbox"]
