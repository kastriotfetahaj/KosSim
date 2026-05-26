#ifndef RTLIB_JIT_VALUES_H
#define RTLIB_JIT_VALUES_H

#include <cstdint>
#include <string>
#include <vector>
#include <unordered_map>

#define DATA_MASK 0x00ffffffffffffff
#define TYPE_MASK 0xff00000000000000

enum class ValueType : uint64_t {
    UNDEFINED = 0,
    NULLVALUE = 1ul << 56,
    BOOL = 2ul << 56,
    INT = 3ul << 56,
    STRING = 4ul << 56,
    ARRAY = 5ul << 56,
    OBJECT = 6ul << 56,
};

struct Value;

typedef std::string StringData;
typedef std::vector<Value> ArrayData;
typedef std::unordered_map<std::string, Value> ObjectData;

struct Value {
private:
    uint64_t container; 

public:
    inline Value() : container(0) {}  

    template<class T>
    inline Value(ValueType type, T data) : container(((uint64_t) type) | (DATA_MASK & (uint64_t) data)) {}

    inline uint64_t raw() const { return container; }

    inline ValueType type() const {
        return (ValueType) (TYPE_MASK & container);
    }

    inline bool is(ValueType t) const { return type() == t; }

    template<class T>
    inline T data() const {
        return (T) (DATA_MASK & container);
    }

    inline uint64_t integer() const { return data<uint64_t>(); }

    inline const std::string str() const {
        switch (type()) {
            case ValueType::NULLVALUE:
                return "null";
            case ValueType::BOOL:
                return std::to_string(data<bool>());
            case ValueType::INT:
                return std::to_string(data<uint64_t>());
            case ValueType::STRING:
                return *data<StringData *>();
            default:
                return "";
        }
    }

    inline const bool is_true() const {
        switch (type()) {
            case ValueType::BOOL:
                return data<bool>();
            case ValueType::INT:
                return data<uint64_t>() != 0;
            case ValueType::STRING:
                return !data<StringData *>()->empty();
            case ValueType::ARRAY:
                return !data<ArrayData *>()->empty();
            case ValueType::OBJECT:
                return !data<ObjectData *>()->empty();
            default:
                return false;
        }
    }

};

void printValue(Value v);

extern void *jit_functions[];

typedef Value (*JitFunction)(...);

#define callJitFunction(f, ...) f(0, 0, 0, 0, 0, 0, __VA_ARGS__)

#endif //RTLIB_JIT_VALUES_H
