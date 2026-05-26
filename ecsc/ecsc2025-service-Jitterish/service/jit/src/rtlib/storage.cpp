#include <iostream>
#include <iterator>

#include "storage.h"
#include "json_parser.h"

namespace {
    class Line : std::string {
        friend std::istream &operator>>(std::istream &is, Line &line) {
            return std::getline(is, line);
        }
    };
}

bool DataStorage::isPublic() {
    return !filename.contains("private");
}

std::optional<Value> DataStorage::nextEntry() {
    std::string str;
    while (std::getline(f, str)) {
        try {
            return jsonToValue(str);
        } catch (const json::exception &e) {
            std::cerr << "[WARN] broken data in " << filename << std::endl;
        }
    }
    return {};
}
