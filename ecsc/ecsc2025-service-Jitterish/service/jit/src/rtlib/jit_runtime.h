#ifndef RTLIB_JIT_RUNTIME_H
#define RTLIB_JIT_RUNTIME_H

#include <nlohmann/json.hpp>
#include "jit_values.h"

#define API_FUNCTION __attribute__((visibility ("default"))) __attribute__((used))

extern "C" {
API_FUNCTION Value jit_rt_print(Value v);
}

__attribute__((visibility("hidden")))
extern bool hasPrivilegedAccess;

#endif //RTLIB_JIT_RUNTIME_H
