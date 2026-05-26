#include "crypto_util.hpp"

#include <cstring>
#include <fcntl.h>
#include <sstream>
#include <stdexcept>
#include <unistd.h>

namespace vg {

namespace {

uint32_t rotr(uint32_t x, uint32_t n) {
    return (x >> n) | (x << (32 - n));
}

const uint32_t K[64] = {
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1,
    0x923f82a4, 0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3,
    0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786,
    0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147,
    0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
    0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
    0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a,
    0x5b9cca4f, 0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
    0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2};

void sha256_compress(uint32_t state[8], const uint8_t block[64]) {
    uint32_t w[64];
    for (int i = 0; i < 16; ++i) {
        w[i] = (static_cast<uint32_t>(block[i * 4]) << 24) |
               (static_cast<uint32_t>(block[i * 4 + 1]) << 16) |
               (static_cast<uint32_t>(block[i * 4 + 2]) << 8) |
               static_cast<uint32_t>(block[i * 4 + 3]);
    }
    for (int i = 16; i < 64; ++i) {
        uint32_t s0 = rotr(w[i - 15], 7) ^ rotr(w[i - 15], 18) ^ (w[i - 15] >> 3);
        uint32_t s1 = rotr(w[i - 2], 17) ^ rotr(w[i - 2], 19) ^ (w[i - 2] >> 10);
        w[i] = w[i - 16] + s0 + w[i - 7] + s1;
    }
    uint32_t a = state[0], b = state[1], c = state[2], d = state[3];
    uint32_t e = state[4], f = state[5], g = state[6], h = state[7];
    for (int i = 0; i < 64; ++i) {
        uint32_t S1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25);
        uint32_t ch = (e & f) ^ (~e & g);
        uint32_t temp1 = h + S1 + ch + K[i] + w[i];
        uint32_t S0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22);
        uint32_t maj = (a & b) ^ (a & c) ^ (b & c);
        uint32_t temp2 = S0 + maj;
        h = g;
        g = f;
        f = e;
        e = d + temp1;
        d = c;
        c = b;
        b = a;
        a = temp1 + temp2;
    }
    state[0] += a;
    state[1] += b;
    state[2] += c;
    state[3] += d;
    state[4] += e;
    state[5] += f;
    state[6] += g;
    state[7] += h;
}

}  // namespace

sha256_digest sha256(const uint8_t* data, size_t len) {
    uint32_t state[8] = {0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
                        0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19};
    uint64_t bit_len = static_cast<uint64_t>(len) * 8;
    while (len >= 64) {
        sha256_compress(state, data);
        data += 64;
        len -= 64;
    }
    uint8_t tail[128]{};
    if (len > 0) std::memcpy(tail, data, len);
    tail[len] = 0x80;
    size_t pad_end = len < 56 ? 56 : 120;
    for (int i = 0; i < 8; ++i) {
        tail[pad_end + i] = static_cast<uint8_t>((bit_len >> (56 - i * 8)) & 0xff);
    }
    sha256_compress(state, tail);
    if (len >= 56) sha256_compress(state, tail + 64);
    sha256_digest digest{};
    for (int i = 0; i < 8; ++i) {
        digest[i * 4] = static_cast<uint8_t>(state[i] >> 24);
        digest[i * 4 + 1] = static_cast<uint8_t>(state[i] >> 16);
        digest[i * 4 + 2] = static_cast<uint8_t>(state[i] >> 8);
        digest[i * 4 + 3] = static_cast<uint8_t>(state[i]);
    }
    return digest;
}

sha256_digest sha256(const std::string& data) {
    return sha256(reinterpret_cast<const uint8_t*>(data.data()), data.size());
}

sha256_digest hmac_sha256(const std::string& key, const std::string& data) {
    constexpr size_t block_size = 64;
    std::vector<uint8_t> key_block(block_size, 0);
    if (key.size() > block_size) {
        auto h = sha256(key);
        std::memcpy(key_block.data(), h.data(), h.size());
    } else {
        std::memcpy(key_block.data(), key.data(), key.size());
    }
    std::vector<uint8_t> ipad(block_size), opad(block_size);
    for (size_t i = 0; i < block_size; ++i) {
        ipad[i] = key_block[i] ^ 0x36;
        opad[i] = key_block[i] ^ 0x5c;
    }
    std::vector<uint8_t> inner(ipad);
    inner.insert(inner.end(), data.begin(), data.end());
    auto inner_hash = sha256(inner.data(), inner.size());
    std::vector<uint8_t> outer(opad);
    outer.insert(outer.end(), inner_hash.begin(), inner_hash.end());
    return sha256(outer.data(), outer.size());
}

static const char b64url_alphabet[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";

std::string base64url_encode(const std::vector<uint8_t>& data) {
    std::string out;
    size_t i = 0;
    while (i + 3 <= data.size()) {
        uint32_t v = (static_cast<uint32_t>(data[i]) << 16) |
                     (static_cast<uint32_t>(data[i + 1]) << 8) | data[i + 2];
        out += b64url_alphabet[(v >> 18) & 0x3f];
        out += b64url_alphabet[(v >> 12) & 0x3f];
        out += b64url_alphabet[(v >> 6) & 0x3f];
        out += b64url_alphabet[v & 0x3f];
        i += 3;
    }
    if (i < data.size()) {
        uint32_t v = static_cast<uint32_t>(data[i]) << 16;
        if (i + 1 < data.size()) v |= static_cast<uint32_t>(data[i + 1]) << 8;
        out += b64url_alphabet[(v >> 18) & 0x3f];
        out += b64url_alphabet[(v >> 12) & 0x3f];
        if (i + 1 < data.size()) out += b64url_alphabet[(v >> 6) & 0x3f];
    }
    return out;
}

std::vector<uint8_t> base64url_decode(const std::string& text) {
    int reverse[256];
    for (int i = 0; i < 256; ++i) reverse[i] = -1;
    for (int i = 0; i < 64; ++i) reverse[static_cast<unsigned char>(b64url_alphabet[i])] = i;
    std::vector<uint8_t> out;
    uint32_t buffer = 0;
    int bits = 0;
    for (char c : text) {
        if (c == '=') continue;
        int v = reverse[static_cast<unsigned char>(c)];
        if (v < 0) continue;
        buffer = (buffer << 6) | static_cast<uint32_t>(v);
        bits += 6;
        if (bits >= 8) {
            bits -= 8;
            out.push_back(static_cast<uint8_t>((buffer >> bits) & 0xff));
        }
    }
    return out;
}

std::vector<uint8_t> random_bytes(size_t n) {
    std::vector<uint8_t> out(n);
    int fd = ::open("/dev/urandom", O_RDONLY);
    if (fd < 0) throw std::runtime_error("/dev/urandom");
    size_t read_total = 0;
    while (read_total < n) {
        ssize_t r = ::read(fd, out.data() + read_total, n - read_total);
        if (r <= 0) {
            ::close(fd);
            throw std::runtime_error("urandom read");
        }
        read_total += static_cast<size_t>(r);
    }
    ::close(fd);
    return out;
}

std::string random_hex(size_t bytes) {
    auto buf = random_bytes(bytes);
    return to_hex(buf);
}

std::string to_hex(const std::vector<uint8_t>& bytes) {
    static const char* digits = "0123456789abcdef";
    std::string out;
    out.reserve(bytes.size() * 2);
    for (uint8_t b : bytes) {
        out.push_back(digits[(b >> 4) & 0x0f]);
        out.push_back(digits[b & 0x0f]);
    }
    return out;
}

std::string to_hex(const std::string& bytes) {
    return to_hex(std::vector<uint8_t>(bytes.begin(), bytes.end()));
}

std::vector<uint8_t> from_hex(const std::string& hex) {
    std::vector<uint8_t> out;
    out.reserve(hex.size() / 2);
    for (size_t i = 0; i + 1 < hex.size(); i += 2) {
        char hi = hex[i], lo = hex[i + 1];
        auto val = [](char c) -> int {
            if (c >= '0' && c <= '9') return c - '0';
            if (c >= 'a' && c <= 'f') return c - 'a' + 10;
            if (c >= 'A' && c <= 'F') return c - 'A' + 10;
            return -1;
        };
        int h = val(hi), l = val(lo);
        if (h < 0 || l < 0) return {};
        out.push_back(static_cast<uint8_t>((h << 4) | l));
    }
    return out;
}

bool constant_time_eq(const std::string& a, const std::string& b) {
    if (a.size() != b.size()) return false;
    uint8_t diff = 0;
    for (size_t i = 0; i < a.size(); ++i) {
        diff |= static_cast<uint8_t>(a[i]) ^ static_cast<uint8_t>(b[i]);
    }
    return diff == 0;
}

}  // namespace vg
