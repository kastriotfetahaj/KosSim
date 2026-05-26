#include "json.hpp"

#include <cctype>
#include <sstream>

namespace vg {

namespace {

size_t skip_ws(const std::string& body, size_t i) {
    while (i < body.size() && std::isspace(static_cast<unsigned char>(body[i]))) ++i;
    return i;
}

bool starts_with(const std::string& body, size_t i, const std::string& target) {
    return body.compare(i, target.size(), target) == 0;
}

size_t find_key(const std::string& body, const std::string& key) {
    std::string needle = "\"" + key + "\"";
    size_t i = 0;
    while (i < body.size()) {
        i = body.find(needle, i);
        if (i == std::string::npos) return std::string::npos;
        size_t j = i + needle.size();
        j = skip_ws(body, j);
        if (j < body.size() && body[j] == ':') return j + 1;
        i = i + needle.size();
    }
    return std::string::npos;
}

}  // namespace

std::string json_string(const std::string& body, const std::string& key) {
    size_t i = find_key(body, key);
    if (i == std::string::npos) return {};
    i = skip_ws(body, i);
    if (i >= body.size() || body[i] != '"') return {};
    ++i;
    std::string out;
    while (i < body.size() && body[i] != '"') {
        if (body[i] == '\\' && i + 1 < body.size()) {
            char next = body[i + 1];
            switch (next) {
                case '"': out += '"'; break;
                case '\\': out += '\\'; break;
                case '/': out += '/'; break;
                case 'n': out += '\n'; break;
                case 'r': out += '\r'; break;
                case 't': out += '\t'; break;
                default: out += next; break;
            }
            i += 2;
        } else {
            out += body[i++];
        }
    }
    return out;
}

int json_int(const std::string& body, const std::string& key, int fallback) {
    size_t i = find_key(body, key);
    if (i == std::string::npos) return fallback;
    i = skip_ws(body, i);
    if (i >= body.size()) return fallback;
    size_t start = i;
    if (body[i] == '-' || body[i] == '+') ++i;
    while (i < body.size() && std::isdigit(static_cast<unsigned char>(body[i]))) ++i;
    if (start == i) return fallback;
    try {
        return std::stoi(body.substr(start, i - start));
    } catch (...) {
        return fallback;
    }
}

std::string json_field_raw(const std::string& body, const std::string& key) {
    size_t i = find_key(body, key);
    if (i == std::string::npos) return {};
    i = skip_ws(body, i);
    if (i >= body.size()) return {};
    if (body[i] == '"') {
        size_t j = i + 1;
        while (j < body.size() && body[j] != '"') {
            if (body[j] == '\\') j += 2;
            else ++j;
        }
        if (j < body.size()) ++j;
        return body.substr(i, j - i);
    }
    if (body[i] == '[' || body[i] == '{') {
        char open = body[i];
        char close = open == '[' ? ']' : '}';
        int depth = 0;
        size_t j = i;
        while (j < body.size()) {
            char c = body[j];
            if (c == '"') {
                ++j;
                while (j < body.size() && body[j] != '"') {
                    if (body[j] == '\\') j += 2;
                    else ++j;
                }
                ++j;
                continue;
            }
            if (c == open) ++depth;
            else if (c == close) {
                --depth;
                if (depth == 0) {
                    ++j;
                    break;
                }
            }
            ++j;
        }
        return body.substr(i, j - i);
    }
    size_t j = i;
    while (j < body.size() && body[j] != ',' && body[j] != '}' && body[j] != ']') ++j;
    return body.substr(i, j - i);
}

std::string json_escape(const std::string& in) {
    std::ostringstream out;
    for (unsigned char c : in) {
        switch (c) {
            case '"': out << "\\\""; break;
            case '\\': out << "\\\\"; break;
            case '\n': out << "\\n"; break;
            case '\r': out << "\\r"; break;
            case '\t': out << "\\t"; break;
            default:
                if (c < 0x20) {
                    out << "\\u00";
                    static const char* hex = "0123456789abcdef";
                    out << hex[(c >> 4) & 0xf] << hex[c & 0xf];
                } else {
                    out << static_cast<char>(c);
                }
        }
    }
    return out.str();
}

}  // namespace vg
