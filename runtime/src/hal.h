/*
 * Narrow hardware abstraction between generated control logic and I/O.
 * The only backend in this export is hal_udp.c (synthetic plant simulator over UDP).
 */
#ifndef HAL_H
#define HAL_H
#include <stdbool.h>
#include <stdint.h>

#define HAL_TC_CHANNELS 4

typedef struct {
  double temperature_C[HAL_TC_CHANNELS];
  bool sensor_ok;
} hal_inputs;

typedef struct {
  double heater_cmd; /* 0..1 */
  double blower_cmd; /* 0..1 */
} hal_outputs;

typedef struct {
  uint64_t boot_id;  /* changes on every process start */
  uint64_t sequence; /* strictly increasing within a boot */
  bool running;
  bool fault;
} hal_heartbeat;

const char *hal_name(void);
int hal_open(const char *arg);  /* 0 on success */
int hal_read(hal_inputs *in);   /* 0 on success; nonzero = I/O fault */
int hal_write(const hal_outputs *out, const hal_heartbeat *hb);
void hal_safe(void);            /* best-effort heater off, blower max */
void hal_close(void);
#endif
