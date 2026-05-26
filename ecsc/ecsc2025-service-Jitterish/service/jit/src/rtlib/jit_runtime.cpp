#include "jit_values.h"
#include "jit_runtime.h"
#include <iostream>
#include "storage.h"
#include "json_parser.h"

using namespace nlohmann;

extern "C" {
API_FUNCTION Value jit_rt_constant(const char *data, size_t len);

API_FUNCTION Value jit_rt_add(Value v1, Value v2);
API_FUNCTION Value jit_rt_sub(Value v1, Value v2);
API_FUNCTION Value jit_rt_mul(Value v1, Value v2);
API_FUNCTION Value jit_rt_div(Value v1, Value v2);
API_FUNCTION Value jit_rt_not(Value v);
API_FUNCTION Value jit_rt_and(Value v1, Value v2);
API_FUNCTION Value jit_rt_or(Value v1, Value v2);
API_FUNCTION Value jit_rt_default(Value v1, Value v2);
API_FUNCTION Value jit_rt_equal(Value v1, Value v2);
API_FUNCTION Value jit_rt_lt(Value v1, Value v2);
API_FUNCTION Value jit_rt_getproperty(Value v1, Value v2);
API_FUNCTION Value jit_rt_setproperty(Value object, Value key, Value v);
API_FUNCTION Value jit_rt_object_new();
API_FUNCTION Value jit_rt_array_new();
API_FUNCTION Value jit_rt_append(Value v1, Value v2);
API_FUNCTION Value jit_rt_len(Value v);
API_FUNCTION Value jit_rt_defined(Value v);
API_FUNCTION int jit_rt_bool(Value v);
API_FUNCTION Value jit_rt_query(const char *collection, JitFunction filter, JitFunction map, JitFunction reduce, size_t limit, Value param);
}


void printValue(Value v) {
    switch (v.type()) {
        case ValueType::UNDEFINED:
            std::cout << "undefined";
            break;
        case ValueType::NULLVALUE:
            std::cout << "null";
            break;
        case ValueType::BOOL:
            std::cout << (v.data<bool>() ? "true" : "false");
            break;
        case ValueType::INT:
            std::cout << v.integer();
            break;
        case ValueType::STRING:
            std::cout << json(v.str());
            break;
        case ValueType::ARRAY: {
            std::cout << '[';
            std::string c;
            for (auto v2: *v.data<ArrayData *>()) {
                std::cout << c;
                printValue(v2);
                c = ',';
            }
            std::cout << ']';
            break;
        }
        case ValueType::OBJECT: {
            std::cout << '{';
            std::string c;
            for (const auto &kv: *v.data<ObjectData *>()) {
                std::cout << c << json(kv.first) << ":";
                printValue(kv.second);
                c = ',';
            }
            std::cout << '}';
            break;
        }
        default:
            std::cout << "<not implemented>";
            break;
    }
}

Value jit_rt_print(Value v) {
    printValue(v);
    std::cout << "\n";
    return {};
}

Value jit_rt_constant(const char *data, size_t len) {
    return jsonToValue(std::string(data, len));
}

Value jit_rt_add(Value v1, Value v2) {
    if (v1.is(ValueType::INT) && v2.is(ValueType::INT)) {
        return {ValueType::INT, v1.integer() + v2.integer()};
    }
    if (v1.is(ValueType::STRING) || v2.is(ValueType::STRING)) {
        return {ValueType::STRING, new std::string(v1.str() + v2.str())};
    }
    return {};
}

Value jit_rt_sub(Value v1, Value v2) {
    if (v1.is(ValueType::INT) && v2.is(ValueType::INT)) {
        return {ValueType::INT, v1.integer() - v2.integer()};
    }
    return {};
}

Value jit_rt_mul(Value v1, Value v2) {
    if (v1.is(ValueType::INT) && v2.is(ValueType::INT)) {
        return {ValueType::INT, v1.integer() * v2.integer()};
    }
    return {};
}

Value jit_rt_div(Value v1, Value v2) {
    if (v1.is(ValueType::INT) && v2.is(ValueType::INT)) {
        return {ValueType::INT, v1.integer() / v2.integer()};
    }
    return {};
}

Value jit_rt_not(Value v) {
    return {ValueType::BOOL, !v.is_true()};
}

Value jit_rt_and(Value v1, Value v2) {
    return {ValueType::BOOL, v1.is_true() && v2.is_true()};
}

Value jit_rt_or(Value v1, Value v2) {
    return {ValueType::BOOL, v1.is_true() || v2.is_true()};
}

Value jit_rt_default(Value v1, Value v2) {
    return v1.is_true() ? v1 : v2;
}

Value jit_rt_equal(Value v1, Value v2) {
    if (v1.type() != v2.type())
        return {ValueType::BOOL, false};
    if (v1.type() == ValueType::STRING)
        return {ValueType::BOOL, (*v1.data<StringData *>()) == (*v2.data<StringData *>())};
    return {ValueType::BOOL, v1.data<uintptr_t>() == v2.data<uintptr_t>()};
}

Value jit_rt_lt(Value v1, Value v2) {
    if (v1.is(ValueType::INT) && v2.is(ValueType::INT)) {
        return {ValueType::BOOL, v1.integer() < v2.integer()};
    } else if (v1.is(ValueType::STRING) && v2.is(ValueType::STRING)) {
        return {ValueType::BOOL, (*v1.data<StringData *>()) < (*v2.data<StringData *>())};
    }
    return {};
}

Value jit_rt_getproperty(Value v1, Value v2) {
    if (v1.is(ValueType::STRING) && v2.is(ValueType::INT)) {
        return {ValueType::INT, v1.data<StringData *>()->at(v2.integer())};
    }
    if (v1.is(ValueType::ARRAY) && v2.is(ValueType::INT)) {
        auto data = v1.data<ArrayData *>();
        return v2.integer() < data->size() ? data->at(v2.integer()) : Value{};
    }
    if (v1.is(ValueType::OBJECT)) {
        auto data = v1.data<ObjectData *>();
        auto it = data->find(v2.str());
        return it != data->end() ? it->second : Value{};
    }
    return {};
}

Value jit_rt_setproperty(Value object, Value key, Value v) {
    if (object.is(ValueType::STRING) && key.is(ValueType::INT)) {
        object.data<StringData *>()->at(key.integer()) = (char) v.integer();
    } else if (object.is(ValueType::ARRAY) && key.is(ValueType::INT)) {
        object.data<ArrayData *>()->at(key.integer()) = v;
    } else if (object.is(ValueType::OBJECT)) {
        (*object.data<ObjectData *>())[key.str()] = v;
    }
    return v;
}

Value jit_rt_object_new() {
    return {ValueType::OBJECT, new ObjectData()};
}

Value jit_rt_array_new() {
    return {ValueType::ARRAY, new ArrayData()};
}

Value jit_rt_append(Value v1, Value v2) {
    if (v1.is(ValueType::ARRAY)) {
        v1.data<ArrayData *>()->push_back(v2);
    }
    if (v1.is(ValueType::STRING)) {
        v1.data<StringData *>()->append(v2.str());
    }
    return v1;
}

Value jit_rt_len(Value v) {
    if (v.is(ValueType::STRING)) {
        return {ValueType::INT, v.data<StringData *>()->size()};
    } else if (v.is(ValueType::ARRAY)) {
        return {ValueType::INT, v.data<ArrayData *>()->size()};
    } else if (v.is(ValueType::OBJECT)) {
        return {ValueType::INT, v.data<ObjectData *>()->size()};
    }
    return {};
}

Value jit_rt_defined(Value v) {
    return {ValueType::BOOL, !v.is(ValueType::UNDEFINED)};
}

int jit_rt_bool(Value v) {
    return v.is_true();
}

static void terminate(const char *msg) {
    std::cout << "Error: " << msg << std::endl;
    exit(0);
}

bool hasPrivilegedAccess = false;

Value jit_rt_query(const char *collection, JitFunction filter, JitFunction map, JitFunction reduce, size_t limit, Value param) {
    auto storage = DataStorage(std::string(collection) + ".ndjson");
    if (!hasPrivilegedAccess && !storage.isPublic()) {
        terminate("access denied");
    }

    Value result = Value {};

    while (auto nextEntry = storage.nextEntry()) {
        Value entry = nextEntry.value();
        if (filter && !callJitFunction(filter, entry, param).is_true()) {
            continue;
        }
        if (map) {
            entry = callJitFunction(map, entry, param);
        }
        if (reduce) {
            result = callJitFunction(reduce, entry, result, param);
        } else {
            jit_rt_print(entry);
        }
        if ((--limit) == 0)
            break;
    }

    return result;
}

void *jit_functions[] = {
        (void *) jit_rt_constant,
        (void *) jit_rt_add,
        (void *) jit_rt_sub,
        (void *) jit_rt_mul,
        (void *) jit_rt_div,
        (void *) jit_rt_not,
        (void *) jit_rt_and,
        (void *) jit_rt_or,
        (void *) jit_rt_default,
        (void *) jit_rt_equal,
        (void *) jit_rt_lt,
        (void *) jit_rt_getproperty,
        (void *) jit_rt_setproperty,
        (void *) jit_rt_object_new,
        (void *) jit_rt_array_new,
        (void *) jit_rt_append,
        (void *) jit_rt_len,
        (void *) jit_rt_defined,
        (void *) jit_rt_bool,
        (void *) jit_rt_print,
        (void *) jit_rt_query
};
