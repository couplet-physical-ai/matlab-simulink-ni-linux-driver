/* Minimal subset of the Simulink Coder rtwtypes.h so the stand-in model
 * compiles the same way generated code would. Replace with the generated
 * rtwtypes.h when a real model is exported. */
#ifndef RTWTYPES_H
#define RTWTYPES_H
#include <stdbool.h>
#include <stdint.h>
typedef double real_T;
typedef bool boolean_T;
typedef int32_t int32_T;
typedef uint32_t uint32_T;
#endif
