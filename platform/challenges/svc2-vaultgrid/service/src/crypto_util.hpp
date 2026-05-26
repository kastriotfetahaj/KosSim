#pragma once
#include <array>
#include <cstdint>
#include <string>
#include <vector>

namespace vg {

using sha256_digest = std::array<uint8_t, 32>;

sha256_digest sha256(const uint8_t* data, size_t len);
sha256_digest sha256(const std::string& data);

sha256_digest hmac_sha256(const std::string& key, const std::string& data);

std::string base64url_encode(const std::vector<uint8_t>& data);
std::vector<uint8_t> base64url_decode(const std::string& text);

std::vector<uint8_t> random_bytes(size_t n);
std::string random_hex(size_t bytes);

std::string to_hex(const std::vector<uint8_t>& bytes);
std::string to_hex(const std::string& bytes);
std::vector<uint8_t> from_hex(const std::string& hex);

bool constant_time_eq(const std::string& a, const std::string& b);

}  // namespace vg
