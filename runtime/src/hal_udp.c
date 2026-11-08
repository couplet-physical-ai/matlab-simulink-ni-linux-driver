/*
 * HAL backend that talks to the synthetic plant/guardian simulator over UDP.
 *   controller -> plant: "CMD <boot> <seq> <running> <fault> <heater> <blower>\n"
 *   plant -> controller: "MEAS <ack> <T0> <T1> <T2> <T3> <ok>\n" every 10 ms,
 *                        <ack> = seq of the latest CMD the plant accepted
 * A measurement older than STALE_NS is reported as a sensor fault.
 */
#define _GNU_SOURCE
#include <arpa/inet.h>
#include <errno.h>
#include <netdb.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

#include "hal.h"

#define STALE_NS (100LL * 1000000LL)

static int sock = -1;
static struct sockaddr_storage peer;
static socklen_t peer_len;
static hal_inputs last;
static long long last_rx_ns;

static long long now_ns(void)
{
  struct timespec t;
  clock_gettime(CLOCK_MONOTONIC, &t);
  return t.tv_sec * 1000000000LL + t.tv_nsec;
}

const char *hal_name(void) { return "udp-plant-sim"; }

int hal_open(const char *arg)
{
  char host[256] = "127.0.0.1", port[16] = "47000";
  if (arg) {
    const char *colon = strrchr(arg, ':');
    if (!colon || (size_t)(colon - arg) >= sizeof host) return -1;
    memcpy(host, arg, (size_t)(colon - arg));
    host[colon - arg] = '\0';
    snprintf(port, sizeof port, "%s", colon + 1);
  }
  struct addrinfo hints = {.ai_family = AF_INET, .ai_socktype = SOCK_DGRAM}, *res = NULL;
  if (getaddrinfo(host, port, &hints, &res) != 0 || !res) return -1;
  memcpy(&peer, res->ai_addr, res->ai_addrlen);
  peer_len = res->ai_addrlen;
  freeaddrinfo(res);
  sock = socket(AF_INET, SOCK_DGRAM | SOCK_NONBLOCK, 0);
  if (sock < 0) return -1;
  /* Handshake: wait up to 3 s for a first measurement so the model does not
   * start on an empty input and latch a spurious sensor fault. */
  for (int i = 0; i < 30; i++) {
    sendto(sock, "HELLO\n", 6, 0, (struct sockaddr *)&peer, peer_len);
    struct timespec pause = {0, 100 * 1000000L};
    nanosleep(&pause, NULL);
    hal_inputs probe;
    hal_read(&probe);
    if (last_rx_ns != 0) return 0;
  }
  return -1;
}

int hal_read(hal_inputs *in)
{
  char buf[256];
  ssize_t n;
  while ((n = recv(sock, buf, sizeof buf - 1, 0)) > 0) { /* drain: keep newest */
    buf[n] = '\0';
    unsigned long long seq;
    int ok;
    hal_inputs m = {0};
    if (sscanf(buf, "MEAS %llu %lf %lf %lf %lf %d", &seq, &m.temperature_C[0], &m.temperature_C[1],
               &m.temperature_C[2], &m.temperature_C[3], &ok) == 6) {
      m.sensor_ok = ok != 0;
      last = m;
      last_rx_ns = now_ns();
    }
  }
  *in = last;
  if (last_rx_ns == 0 || now_ns() - last_rx_ns > STALE_NS) {
    in->sensor_ok = false;
    return 0; /* stale data is an input-quality fault, not a transport error */
  }
  return 0;
}

static int send_cmd(const hal_outputs *out, const hal_heartbeat *hb)
{
  char buf[256];
  int len = snprintf(buf, sizeof buf, "CMD %llu %llu %d %d %.6f %.6f\n",
                     (unsigned long long)hb->boot_id, (unsigned long long)hb->sequence,
                     hb->running, hb->fault, out->heater_cmd, out->blower_cmd);
  ssize_t n = sendto(sock, buf, (size_t)len, 0, (struct sockaddr *)&peer, peer_len);
  /* A dropped datagram is tolerated: the guardian's staleness check owns that risk. */
  return (n < 0 && errno != EAGAIN && errno != ECONNREFUSED && errno != ENETUNREACH &&
          errno != EHOSTUNREACH) ? -1 : 0;
}

int hal_write(const hal_outputs *out, const hal_heartbeat *hb) { return send_cmd(out, hb); }

void hal_safe(void)
{
  if (sock < 0) return;
  hal_outputs safe = {0.0, 1.0};
  hal_heartbeat hb = {0, 0, false, true};
  send_cmd(&safe, &hb);
}

void hal_close(void)
{
  if (sock >= 0) close(sock);
  sock = -1;
}
