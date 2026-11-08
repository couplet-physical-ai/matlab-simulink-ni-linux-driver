/*
 * Binds the runtime to any Embedded Coder (ERT) model that honors the
 * ni-stand-io-v1 interface (see matlab/+nistand/contract.m):
 *   inports  T_meas_C (double), sensor_ok (boolean), T_set_C (double)
 *   outports heater_cmd, blower_cmd (double 0..1), running, fault (boolean)
 * Build with -DMODEL=<name> -DMODEL_HEADER='"<name>.h"'. Defaults to the
 * hand-written stand-in model "controller".
 */
#ifndef MODEL_GLUE_H
#define MODEL_GLUE_H

#ifndef MODEL
#define MODEL controller
#endif
#ifndef MODEL_HEADER
#define MODEL_HEADER "controller.h"
#endif
#include MODEL_HEADER

#define NS_CAT_(a, b) a##b
#define NS_CAT(a, b) NS_CAT_(a, b)
#define NS_STR_(x) #x
#define NS_STR(x) NS_STR_(x)

#define MODEL_NAME NS_STR(MODEL)
#define MODEL_U NS_CAT(MODEL, _U)
#define MODEL_Y NS_CAT(MODEL, _Y)
#define MODEL_INIT NS_CAT(MODEL, _initialize)
#define MODEL_STEP NS_CAT(MODEL, _step)
#define MODEL_TERM NS_CAT(MODEL, _terminate)

#endif
