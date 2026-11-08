/* Unit tests for the stand-in model's contract (fault latch, clamping, safe terminate). */
#include <math.h>
#include <stdio.h>
#include "controller.h"

static int failures;
#define EXPECT(c) do { if (!(c)) { printf("FAIL %s:%d %s\n", __FILE__, __LINE__, #c); failures++; } } while (0)

int main(void)
{
  controller_initialize();
  EXPECT(controller_Y.heater_cmd == 0.0 && controller_Y.blower_cmd == 1.0 && !controller_Y.running);

  controller_U = (ExtU_controller_T){.T_meas_C = 20.0, .sensor_ok = true, .T_set_C = 40.0};
  controller_step();
  EXPECT(controller_Y.running && controller_Y.heater_cmd == 1.0); /* clamped */

  controller_U.T_meas_C = 50.0;
  controller_step();
  EXPECT(controller_Y.heater_cmd == 0.0); /* no negative heat */

  controller_U.T_meas_C = 38.0;
  controller_step();
  EXPECT(fabs(controller_Y.heater_cmd - 0.2) < 1e-12);

  controller_U.T_meas_C = NAN;
  controller_step();
  EXPECT(controller_Y.fault && !controller_Y.running && controller_Y.heater_cmd == 0.0 && controller_Y.blower_cmd == 1.0);

  controller_U = (ExtU_controller_T){.T_meas_C = 20.0, .sensor_ok = true, .T_set_C = 40.0};
  controller_step();
  EXPECT(controller_Y.fault && controller_Y.heater_cmd == 0.0); /* latched: no auto-recovery */

  controller_initialize();
  controller_U.sensor_ok = false;
  controller_step();
  EXPECT(controller_Y.fault);

  controller_terminate();
  EXPECT(controller_Y.heater_cmd == 0.0 && controller_Y.blower_cmd == 1.0);

  printf("%s (%d failures)\n", failures ? "FAILED" : "OK", failures);
  return failures != 0;
}
