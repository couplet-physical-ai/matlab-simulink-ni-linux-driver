/* HAND-WRITTEN STAND-IN for generated code; see controller.h. */
#include <math.h>
#include "controller.h"

ExtU_controller_T controller_U;
ExtY_controller_T controller_Y;

static const real_T Kp = 0.1;      /* illustrative, not tuned */
static const real_T BLOWER_RUN = 0.5;

void controller_initialize(void)
{
  controller_Y.heater_cmd = 0.0;
  controller_Y.blower_cmd = 1.0;
  controller_Y.running = false;
  controller_Y.fault = false;
}

void controller_step(void)
{
  if (!controller_U.sensor_ok || !isfinite(controller_U.T_meas_C)) {
    controller_Y.fault = true; /* latched: no automatic recovery */
  }
  if (controller_Y.fault) {
    controller_Y.running = false;
    controller_Y.heater_cmd = 0.0;
    controller_Y.blower_cmd = 1.0;
    return;
  }
  real_T u = Kp * (controller_U.T_set_C - controller_U.T_meas_C);
  controller_Y.heater_cmd = u < 0.0 ? 0.0 : (u > 1.0 ? 1.0 : u);
  controller_Y.blower_cmd = BLOWER_RUN;
  controller_Y.running = true;
}

void controller_terminate(void)
{
  controller_Y.heater_cmd = 0.0;
  controller_Y.blower_cmd = 1.0;
  controller_Y.running = false;
}
