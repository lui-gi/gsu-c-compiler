/*
 * entrypoint.c — Sandbox entrypoint binary
 *
 * Compiles /sandbox/main.c to /tmp/a.out using gcc, then executes the
 * resulting binary with a 5-second alarm-based timeout. No shell or
 * external `timeout` binary is required at runtime.
 *
 * Exit codes:
 *   If gcc fails, its exit code is forwarded.
 *   If the program times out, exit code 124 is returned (matching the
 *   convention used by the coreutils `timeout` command).
 *   Otherwise, the program's own exit code is forwarded.
 */

#include <errno.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <sys/types.h>
#include <sys/wait.h>

static pid_t g_child_pid = -1;

static void on_alarm(int sig) {
    (void)sig;
    if (g_child_pid > 0)
        kill(g_child_pid, SIGKILL);
}

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

    /* Step 2: run with 5-second in-process timeout */
    char *const exec_argv[] = { "/tmp/a.out", NULL };

    g_child_pid = fork();
    if (g_child_pid < 0) {
        perror("fork");
        return 1;
    }
    if (g_child_pid == 0) {
        execv("/tmp/a.out", exec_argv);
        perror("/tmp/a.out");
        _exit(127);
    }

    /* Set up SIGALRM without SA_RESTART so waitpid is interrupted. */
    struct sigaction sa;
    sa.sa_handler = on_alarm;
    sigemptyset(&sa.sa_mask);
    sa.sa_flags = 0;
    sigaction(SIGALRM, &sa, NULL);
    alarm(5);

    int wstatus;
    int wret = waitpid(g_child_pid, &wstatus, 0);
    alarm(0);

    if (wret < 0) {
        /* EINTR means SIGALRM fired and killed the child; collect it. */
        waitpid(g_child_pid, &wstatus, 0);
        return 124;
    }

    if (WIFEXITED(wstatus))   return WEXITSTATUS(wstatus);
    if (WIFSIGNALED(wstatus)) {
        /* SIGKILL from our own alarm handler → report as timeout. */
        if (WTERMSIG(wstatus) == SIGKILL) return 124;
        return 128 + WTERMSIG(wstatus);
    }
    return 1;
}
