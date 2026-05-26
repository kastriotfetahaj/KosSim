#include "json_parser.h"

#include <algorithm>
#include <cstddef>
#include <cstdlib>
#include <stack>
#include <string>

#include "../../build/_deps/json-src/include/nlohmann/json.hpp"

using namespace nlohmann;

namespace {
    // Author note: not relevant for exploitation.
    // If you don't trust us, we copied from here:
    // from: https://json.nlohmann.me/features/parsing/sax_interface/
    class ValueBuilder {
        std::stack<int> what; // 1 = array 2 = object
        std::stack<ArrayData *> currentArray;
        std::stack<ObjectData *> currentObject;
        std::stack<std::string> lastKey;
        Value result;

        void parsedValue(Value v) {
            if (what.empty()) {
                result = v;
            } else if (what.top() == 1) {
                currentArray.top()->push_back(v);
            } else if (what.top() == 2) {
                (*currentObject.top())[std::move(lastKey.top())] = v;
                lastKey.pop();
            }
        }

    public:
        // called when null is parsed
        bool null() {
            parsedValue(Value{ValueType::NULLVALUE, 0});
            return true;
        }

        // called when a boolean is parsed; value is passed
        bool boolean(bool val) {
            parsedValue(Value{ValueType::BOOL, val ? 1 : 0});
            return true;
        }

        // called when a signed or unsigned integer number is parsed; value is passed
        bool number_integer(json::number_integer_t val) {
            parsedValue(Value(ValueType::INT, val));
            return true;
        }

        bool number_unsigned(json::number_unsigned_t val) {
            parsedValue(Value(ValueType::INT, val));
            return true;
        }

        // called when a floating-point number is parsed; value and original string is passed
        bool number_float(json::number_float_t val, const json::string_t &s) {
            parsedValue(Value());
            return true;
        }

        // called when a string is parsed; value is passed and can be safely moved away
        bool string(json::string_t &val) {
            parsedValue(Value(ValueType::STRING, new StringData(std::move(val))));
            return true;
        }

        // called when a binary value is parsed; value is passed and can be safely moved away
        bool binary(json::binary_t &val) {
            parsedValue(Value());
            return true;
        }

        // called when an object or array begins or ends, resp. The number of elements is passed (or -1 if not known)
        bool start_object(std::size_t elements) {
            what.push(2);
            currentObject.push(new ObjectData());
            return true;
        }

        bool end_object() {
            if (what.top() != 2) abort();
            auto current = currentObject.top();
            currentObject.pop();
            what.pop();
            parsedValue(Value(ValueType::OBJECT, current));
            return true;
        }

        bool start_array(std::size_t elements) {
            what.push(1);
            currentArray.push(new ArrayData());
            return true;
        }

        bool end_array() {
            if (what.top() != 1) abort();
            auto current = currentArray.top();
            currentArray.pop();
            what.pop();
            parsedValue(Value(ValueType::ARRAY, current));
            return true;
        }

        // called when an object key is parsed; value is passed and can be safely moved away
        bool key(json::string_t &val) {
            lastKey.emplace(std::move(val));
            return true;
        }

        // called when a parse error occurs; byte position, the last token, and an exception is passed
        bool parse_error(std::size_t position, const std::string &last_token, const json::exception &ex) {
            throw ex;
        }

        [[nodiscard]] Value value() const {
            return result;
        }
    };
}

Value jsonToValue(const std::string &str) {
    ValueBuilder builder;
    json::sax_parse(str, &builder);
    return builder.value();
}