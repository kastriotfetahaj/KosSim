#pragma once
#include <string>

namespace vg {

std::string json_string(const std::string& body, const std::string& key);
int json_int(const std::string& body, const std::string& key, int fallback = 0);
std::string json_field_raw(const std::string& body, const std::string& key);
std::string json_escape(const std::string& input);

}  // namespace vg

inline std::string json_string(const std::string& body, const std::string& key) {
    return vg::json_string(body, key);
}

inline int json_int(const std::string& body, const std::string& key, int fallback = 0) {
    return vg::json_int(body, key, fallback);
}

inline std::string json_escape(const std::string& input) {
    return vg::json_escape(input);
}
