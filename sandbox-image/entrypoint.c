/*
 * entrypoint.c — Sandbox entrypoint binary
 *
 * Compiles /sandbox/main.c to /tmp/a.out using gcc, then executes the
 * resulting binary under `timeout 5`. No shell is required at runtime.
 *
 * Exit codes:
 *   The exit code of `timeout /tmp/a.out` is forwarded as-is.
 *   If gcc fails, its exit code is forwarded.
 */

#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <sys/types.h>
#include <sys/wait.h>

static int run(char *const argv[]) {
    pid_t pid = fork();
    if (pid < 0) {
        perror("fork");
        return 1;
    }
    if (pid == 0) {
        execv(argv[0], argv);
        perror(argv[0]);
        _exit(127);
    }
    int status;
    if (waitpid(pid, &status, 0) < 0) {
        perror("waitpid");
        return 1;
    }
    if (WIFEXITED(status))   return WEXITSTATUS(status);
    if (WIFSIGNALED(status)) return 128 + WTERMSIG(status);
    return 1;
}

int main(void) {
    /* Step 1: compile */
    char *const gcc_args[] = {
        "/usr/local/bin/gcc",
        "/sandbox/main.c",
        "-o", "/tmp/a.out",
        "-Wall",
        "-Wextra",
        NULL
    };
    int rc = run(gcc_args);
    if (rc != 0) {
        /* gcc already wrote the error to stderr */
        return rc;
    }

    /* Step 2: run with timeout */
    char *const run_args[] = {
        "/usr/bin/timeout",
        "5",
        "/tmp/a.out",
        NULL
    };
    return run(run_args);
}
