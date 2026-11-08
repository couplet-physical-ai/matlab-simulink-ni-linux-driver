/*
 * Fixed-step runtime for a Simulink-Coder-style model on Linux.
 *
 *   ctrl_<hal> [--period-ms N] [--duration-s N] [--setpoint C]
 *              [--rt-priority N] [--stats FILE] [--hal-arg ARG]
 *              [--max-late-periods N] [--status-file FILE]
 *
 * --status-file is rewritten atomically about once per second (put it on a
 * tmpfs such as /run) so tools can see a live loop without touching it.
 *
 * Absolute-deadline scheduling (clock_nanosleep TIMER_ABSTIME), no catch-up
 * bursts after an overrun, and a safe-output write on every exit path.
 * A wake-up later than --max-late-periods (e.g. after a freeze) latches a
 * runtime timing fault: outputs stay safe until the process is restarted.
 * This is a validation harness; it carries no authority over real hardware.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <math.h>
#include <sched.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/resource.h>
#include <time.h>
#include <unistd.h>

#include "model_glue.h"
#include "hal.h"

#define NS_PER_MS 1000000LL
#define NS_PER_S 1000000000LL

static volatile sig_atomic_t g_stop;
static void on_signal(int sig) { (void)sig; g_stop = 1; }

static long long ts_ns(const struct timespec *t) { return t->tv_sec * NS_PER_S + t->tv_nsec; }
static struct timespec ns_ts(long long ns) { struct timespec t = {ns / NS_PER_S, ns % NS_PER_S}; return t; }
static long long now_ns(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return ts_ns(&t); }

static void write_status(const char *path, const char *json)
{
  char tmp[512];
  if (snprintf(tmp, sizeof tmp, "%s.tmp", path) >= (int)sizeof tmp) return;
  FILE *f = fopen(tmp, "w");
  if (!f) return;
  fputs(json, f);
  if (fclose(f) == 0) rename(tmp, path);
}

static int cmp_ll(const void *a, const void *b)
{
  long long x = *(const long long *)a, y = *(const long long *)b;
  return (x > y) - (x < y);
}

int main(int argc, char **argv)
{
  double period_ms = 10.0, duration_s = 0.0, setpoint = 40.0;
  int rt_priority = 0;
  double max_late_periods = 5.0;
  const char *stats_path = NULL, *hal_arg = NULL, *status_path = NULL;
  for (int i = 1; i < argc; i++) {
    const char *a = argv[i], *v = i + 1 < argc ? argv[i + 1] : NULL;
    if (!v) { fprintf(stderr, "missing value for %s\n", a); return 64; }
    if (!strcmp(a, "--period-ms")) period_ms = atof(v);
    else if (!strcmp(a, "--duration-s")) duration_s = atof(v);
    else if (!strcmp(a, "--setpoint")) setpoint = atof(v);
    else if (!strcmp(a, "--rt-priority")) rt_priority = atoi(v);
    else if (!strcmp(a, "--stats")) stats_path = v;
    else if (!strcmp(a, "--hal-arg")) hal_arg = v;
    else if (!strcmp(a, "--max-late-periods")) max_late_periods = atof(v);
    else if (!strcmp(a, "--status-file")) status_path = v;
    else { fprintf(stderr, "unknown option %s\n", a); return 64; }
    i++;
  }
  if (!(period_ms >= 1.0 && period_ms <= 1000.0)) { fprintf(stderr, "period out of range\n"); return 64; }

  struct sigaction sa = {0};
  sa.sa_handler = on_signal;
  sigaction(SIGTERM, &sa, NULL);
  sigaction(SIGINT, &sa, NULL);

  const long long period = (long long)(period_ms * NS_PER_MS);
  const long long max_iters = duration_s > 0 ? (long long)(duration_s * NS_PER_S / period) : -1;
  /* Ring of the most recent samples for percentiles; worst cases tracked separately.
   * Allocated before mlockall so a small RLIMIT_MEMLOCK cannot fail it. */
  const size_t ring = 1u << 17;
  size_t cap = max_iters > 0 && (size_t)max_iters < ring ? (size_t)max_iters : ring;
  long long *late = calloc(cap, sizeof *late), *exec = calloc(cap, sizeof *exec);
  if (!late || !exec) { fprintf(stderr, "out of memory\n"); return 70; }

  /* MCL_FUTURE under a finite memlock limit makes later allocations (including
   * inside vendor libraries) fail, so only use it when the limit is unlimited
   * (systemd: LimitMEMLOCK=infinity; docker: --ulimit memlock=-1). */
  struct rlimit ml;
  bool unlimited = getrlimit(RLIMIT_MEMLOCK, &ml) == 0 && ml.rlim_cur == RLIM_INFINITY;
  bool locked = mlockall(unlimited ? MCL_CURRENT | MCL_FUTURE : MCL_CURRENT) == 0 && unlimited;
  if (!locked) fprintf(stderr, "warn: memory not fully locked (RLIMIT_MEMLOCK finite)\n");
  bool rt = false;
  if (rt_priority > 0) {
    struct sched_param sp = {.sched_priority = rt_priority};
    rt = sched_setscheduler(0, SCHED_FIFO, &sp) == 0;
    if (!rt) fprintf(stderr, "warn: SCHED_FIFO unavailable: %s\n", strerror(errno));
  }

  struct timespec boot_ts;
  clock_gettime(CLOCK_REALTIME, &boot_ts);
  hal_heartbeat hb = {.boot_id = ((uint64_t)ts_ns(&boot_ts)) ^ ((uint64_t)getpid() << 32)};

  if (hal_open(hal_arg) != 0) {
    fprintf(stderr, "hal_open(%s) failed\n", hal_name());
    hal_safe();
    hal_close();
    return 2;
  }
  MODEL_INIT();
  MODEL_U.T_set_C = setpoint;
  fprintf(stderr, "ctrl: model=%s hal=%s period=%.3f ms setpoint=%.2f C\n", MODEL_NAME, hal_name(), period_ms,
          setpoint);

  long long iters = 0, overruns = 0, io_faults = 0, worst_late = 0, worst_exec = 0;
  bool timing_fault = false;
  long long next = now_ns() + period;
  const long long status_every = period >= NS_PER_S ? 1 : NS_PER_S / period;
  char status[768];
  int rc = 0;
  while (!g_stop && (max_iters < 0 || iters < max_iters)) {
    struct timespec dl = ns_ts(next);
    while (clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &dl, NULL) == EINTR && !g_stop) {}
    if (g_stop) break;
    long long woke = now_ns();

    hal_inputs in = {0};
    if (hal_read(&in) != 0) { in.sensor_ok = false; io_faults++; }
    MODEL_U.T_meas_C = in.temperature_C[0];
    MODEL_U.sensor_ok = in.sensor_ok;
    MODEL_STEP();
    if (woke - next > (long long)(max_late_periods * period) && !timing_fault) {
      timing_fault = true; /* latched for the life of the process */
      fprintf(stderr, "timing fault: woke %.1f ms late; outputs held safe\n", (woke - next) / 1e6);
    }

    hb.sequence++;
    hb.running = MODEL_Y.running && !timing_fault;
    hb.fault = MODEL_Y.fault || timing_fault;
    hal_outputs out = {MODEL_Y.heater_cmd, MODEL_Y.blower_cmd};
    if (timing_fault) out = (hal_outputs){0.0, 1.0};
    if (hal_write(&out, &hb) != 0) {
      fprintf(stderr, "hal_write failed; going safe\n");
      rc = 3;
      break;
    }

    long long done = now_ns();
    size_t k = (size_t)iters % cap;
    late[k] = woke - next;
    exec[k] = done - woke;
    if (late[k] > worst_late) worst_late = late[k];
    if (exec[k] > worst_exec) worst_exec = exec[k];
    iters++;
    if (status_path && iters % status_every == 1) {
      struct timespec wall;
      clock_gettime(CLOCK_REALTIME, &wall);
      snprintf(status, sizeof status,
               "{\"model\": \"%s\", \"hal\": \"%s\", \"pid\": %d, \"updated_unix\": %lld,"
               " \"period_ms\": %.3f, \"iterations\": %lld, \"overruns\": %lld, \"io_faults\": %lld,"
               " \"running\": %s, \"fault\": %s, \"timing_fault\": %s, \"sensor_ok\": %s,"
               " \"T_meas_C\": %.3f, \"heater_cmd\": %.4f, \"blower_cmd\": %.4f,"
               " \"worst_wake_late_us\": %.1f, \"mlockall\": %s, \"sched_fifo\": %s}\n",
               MODEL_NAME, hal_name(), (int)getpid(), (long long)wall.tv_sec, period_ms, iters, overruns,
               io_faults, hb.running ? "true" : "false", hb.fault ? "true" : "false",
               timing_fault ? "true" : "false", in.sensor_ok ? "true" : "false",
               isfinite(in.temperature_C[0]) ? in.temperature_C[0] : -1.0, out.heater_cmd, out.blower_cmd,
               worst_late / 1000.0, locked ? "true" : "false", rt ? "true" : "false");
      write_status(status_path, status);
    }
    next += period;
    if (done > next) { /* overrun: skip missed slots, never burst to catch up */
      long long missed = (done - next) / period + 1;
      overruns += missed;
      next += missed * period;
    }
  }

  MODEL_TERM();
  hal_safe();
  hal_close();

  size_t n = (size_t)(iters < (long long)cap ? iters : (long long)cap);
  qsort(late, n, sizeof *late, cmp_ll);
  qsort(exec, n, sizeof *exec, cmp_ll);
#define Q(a, q) (n ? (a)[(size_t)((q) * (n - 1))] / 1000.0 : NAN)
  FILE *f = stats_path ? fopen(stats_path, "w") : stdout;
  if (!f) f = stdout;
  fprintf(f,
          "{\n  \"model\": \"%s\",\n  \"hal\": \"%s\",\n  \"period_ms\": %.3f,\n  \"iterations\": %lld,\n"
          "  \"overruns\": %lld,\n  \"io_faults\": %lld,\n  \"mlockall\": %s,\n  \"sched_fifo\": %s,\n"
          "  \"wake_latency_us\": {\"p50\": %.1f, \"p99\": %.1f, \"p999\": %.1f, \"max\": %.1f},\n"
          "  \"step_exec_us\": {\"p50\": %.1f, \"p99\": %.1f, \"max\": %.1f},\n"
          "  \"final\": {\"fault\": %s, \"timing_fault\": %s, \"T_meas_C\": %.3f},\n  \"exit_code\": %d\n}\n",
          MODEL_NAME, hal_name(), period_ms, iters, overruns, io_faults, locked ? "true" : "false",
          rt ? "true" : "false", Q(late, 0.5), Q(late, 0.99), Q(late, 0.999), worst_late / 1000.0,
          Q(exec, 0.5), Q(exec, 0.99), worst_exec / 1000.0, MODEL_Y.fault ? "true" : "false",
          timing_fault ? "true" : "false", isfinite(MODEL_U.T_meas_C) ? MODEL_U.T_meas_C : -1.0, rc);
  if (f != stdout) fclose(f);
  free(late);
  free(exec);
  return rc;
}
