#include <iostream>
#include <dlfcn.h>
#include <nlohmann/json.hpp>

#include "jit_values.h"
#include "jit_runtime.h"
#include "json_parser.h"


int main(int argc, const char* argv[]) {
    if (argc < 2 || argc > 4) {
        std::cerr << "USAGE: " << argv[0] << " <query/function> [<param-as-json>] [--privileged]" << std::endl;
        return 1;
    }

    Value param{};
    if (argc >= 3) {
        param = jsonToValue(argv[2]);
    }
    hasPrivilegedAccess = argc >= 4 && std::string(argv[3]) == "--privileged";

    auto f = (JitFunction) dlsym(RTLD_DEFAULT, argv[1]);
    if (!f) {
        std::cerr << "\"" << argv[1] << "\" is neither a function nor a query" << std::endl;
        return 1;
    }
    auto result = callJitFunction(f, param);
    if (!result.is(ValueType::UNDEFINED)) {
        jit_rt_print(result);
    }
    return 0;
}
