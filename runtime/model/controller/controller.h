/*
 * HAND-WRITTEN STAND-IN for Simulink Coder (ERT) output. It mirrors the
 * entry points and root I/O structs ERT emits for a model named
 * "controller" (controller_initialize/step/terminate, controller_U/_Y)
 * so the runtime and HAL can be validated before a licensed model exists.
 * The proportional law is illustrative; it is not derived from any existing LabVIEW control loop.
 */
#ifndef CONTROLLER_H
#define CONTROLLER_H
#include "rtwtypes.h"

typedef struct {
  real_T T_meas_C;     /* process temperature, degC */
  boolean_T sensor_ok; /* input quality from HAL */
  real_T T_set_C;      /* setpoint, degC */
} ExtU_controller_T;

typedef struct {
  real_T heater_cmd;   /* 0..1 fraction (illustrative scaling) */
  real_T blower_cmd;   /* 0..1 fraction (illustrative scaling) */
  boolean_T running;   /* law active and healthy */
  boolean_T fault;     /* latched until process restart */
} ExtY_controller_T;

extern ExtU_controller_T controller_U;
extern ExtY_controller_T controller_Y;

void controller_initialize(void);
void controller_step(void);
void controller_terminate(void);
#endif
