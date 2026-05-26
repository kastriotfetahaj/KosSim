#ifndef RTLIB_STORAGE_H
#define RTLIB_STORAGE_H

#include <fstream>
#include <nlohmann/json.hpp>

#include "jit_values.h"

using namespace nlohmann;


class DataStorage {
    std::string filename;
    std::ifstream f;
public:
    explicit DataStorage(const std::string &filename) : filename(filename), f(filename) {}

    bool isPublic();

    std::optional<Value> nextEntry();
};

#endif //RTLIB_STORAGE_H
