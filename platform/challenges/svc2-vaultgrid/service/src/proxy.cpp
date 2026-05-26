#include "proxy.hpp"

#include <algorithm>
#include <arpa/inet.h>
#include <cerrno>
#include <cstring>
#include <netdb.h>
#include <netinet/in.h>
#include <sstream>
#include <sys/socket.h>
#include <unistd.h>

namespace vg {

namespace {

bool send_all(int sock, const std::string& data) {
    size_t sent = 0;
    while (sent < data.size()) {
        ssize_t r = ::send(sock, data.data() + sent, data.size() - sent, 0);
        if (r <= 0) return false;
        sent += static_cast<size_t>(r);
    }
    return true;
}

std::string recv_all(int sock) {
    std::string out;
    char buf[4096];
    while (true) {
        ssize_t r = ::recv(sock, buf, sizeof(buf), 0);
        if (r <= 0) break;
        out.append(buf, static_cast<size_t>(r));
    }
    return out;
}

ProxyResponse parse_http(const std::string& raw) {
    ProxyResponse res;
    auto hdr_end = raw.find("\r\n\r\n");
    if (hdr_end == std::string::npos) return res;
    std::istringstream stream(raw.substr(0, hdr_end));
    std::string line;
    std::getline(stream, line);
    if (!line.empty() && line.back() == '\r') line.pop_back();
    auto first_space = line.find(' ');
    auto second_space = line.find(' ', first_space + 1);
    if (first_space == std::string::npos || second_space == std::string::npos) return res;
    try {
        res.status = std::stoi(line.substr(first_space + 1, second_space - first_space - 1));
    } catch (...) {
        return res;
    }
    while (std::getline(stream, line)) {
        if (!line.empty() && line.back() == '\r') line.pop_back();
        auto colon = line.find(':');
        if (colon == std::string::npos) continue;
        std::string key = line.substr(0, colon);
        std::transform(key.begin(), key.end(), key.begin(), [](unsigned char c) { return std::tolower(c); });
        if (key == "content-type") {
            size_t i = colon + 1;
            while (i < line.size() && std::isspace(static_cast<unsigned char>(line[i]))) ++i;
            res.content_type = line.substr(i);
        }
    }
    res.body = raw.substr(hdr_end + 4);
    return res;
}

}  // namespace

ProxyResponse http_request(
    const std::string& method,
    const std::string& host,
    int port,
    const std::string& path,
    const std::string& body,
    const std::map<std::string, std::string>& headers
) {
    ProxyResponse res;
    addrinfo hints{};
    hints.ai_family = AF_INET;
    hints.ai_socktype = SOCK_STREAM;
    addrinfo* info = nullptr;
    auto port_str = std::to_string(port);
    int rc = getaddrinfo(host.c_str(), port_str.c_str(), &hints, &info);
    if (rc != 0 || !info) return res;
    int sock = socket(info->ai_family, info->ai_socktype, info->ai_protocol);
    if (sock < 0) {
        freeaddrinfo(info);
        return res;
    }
    timeval tv{};
    tv.tv_sec = 5;
    setsockopt(sock, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
    setsockopt(sock, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof(tv));
    if (::connect(sock, info->ai_addr, info->ai_addrlen) < 0) {
        ::close(sock);
        freeaddrinfo(info);
        return res;
    }
    freeaddrinfo(info);
    std::ostringstream out;
    out << method << " " << path << " HTTP/1.1\r\n"
        << "host: " << host << ":" << port << "\r\n"
        << "connection: close\r\n";
    if (!body.empty()) out << "content-length: " << body.size() << "\r\n";
    for (const auto& [k, v] : headers) out << k << ": " << v << "\r\n";
    out << "\r\n" << body;
    if (!send_all(sock, out.str())) {
        ::close(sock);
        return res;
    }
    std::string raw = recv_all(sock);
    ::close(sock);
    return parse_http(raw);
}

}  // namespace vg
