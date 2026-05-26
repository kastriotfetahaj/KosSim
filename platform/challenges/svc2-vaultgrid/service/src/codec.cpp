#include "codec.hpp"

#include <iomanip>
#include <sstream>
#include <string>
#include <vector>

std::string short_hash(const std::string& input) {
    uint64_t h = 1469598103934665603ULL;
    for (unsigned char c : input) {
        h ^= c;
        h *= 1099511628211ULL;
    }
    std::ostringstream out;
    out << std::hex << std::setw(16) << std::setfill('0') << h;
    return out.str();
}

std::string to_hex(const std::string& bytes) {
    std::ostringstream out;
    for (unsigned char c : bytes) out << std::hex << std::setw(2) << std::setfill('0') << static_cast<int>(c);
    return out.str();
}

std::string from_hex(const std::string& hex) {
    std::string out;
    for (size_t i = 0; i + 1 < hex.size(); i += 2) {
        out.push_back(static_cast<char>(std::stoul(hex.substr(i, 2), nullptr, 16)));
    }
    return out;
}

std::vector<std::string> split_secret(const std::string& flag, const std::string& object_id) {
    std::string a, b, c;
    for (size_t i = 0; i < flag.size(); ++i) {
        unsigned char p = static_cast<unsigned char>(short_hash(object_id + ":pad:" + std::to_string(i))[0]);
        unsigned char n = static_cast<unsigned char>(short_hash(object_id + ":noise:" + std::to_string(i))[1]);
        a.push_back(static_cast<char>(static_cast<unsigned char>(flag[i]) ^ p));
        b.push_back(static_cast<char>(n));
        c.push_back(static_cast<char>(p ^ n));
    }
    return {to_hex(a), to_hex(b), to_hex(c)};
}

std::string xor_shards(const std::vector<std::string>& shards) {
    if (shards.size() < 3) return "";
    auto a = from_hex(shards[0]);
    auto b = from_hex(shards[1]);
    auto c = from_hex(shards[2]);
    std::string out;
    for (size_t i = 0; i < a.size() && i < b.size() && i < c.size(); ++i) {
        out.push_back(static_cast<char>(a[i] ^ b[i] ^ c[i]));
    }
    return out;
}
