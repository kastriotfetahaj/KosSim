#include "http.hpp"
#include "routes.hpp"

#include <algorithm>
#include <arpa/inet.h>
#include <cctype>
#include <cstring>
#include <iostream>
#include <netinet/in.h>
#include <sstream>
#include <stdexcept>
#include <sys/socket.h>
#include <thread>
#include <unistd.h>

static std::string trim(std::string s) {
    while (!s.empty() && std::isspace(static_cast<unsigned char>(s.front()))) s.erase(s.begin());
    while (!s.empty() && std::isspace(static_cast<unsigned char>(s.back()))) s.pop_back();
    return s;
}

std::string url_decode(const std::string& in) {
    std::string out;
    for (size_t i = 0; i < in.size(); ++i) {
        if (in[i] == '%' && i + 2 < in.size()) {
            std::string hex = in.substr(i + 1, 2);
            char* end = nullptr;
            long value = std::strtol(hex.c_str(), &end, 16);
            if (end && *end == '\0') {
                out.push_back(static_cast<char>(value));
                i += 2;
                continue;
            }
        }
        out.push_back(in[i] == '+' ? ' ' : in[i]);
    }
    return out;
}

std::string json_escape(const std::string& in) {
    std::ostringstream out;
    for (char c : in) {
        switch (c) {
            case '"': out << "\\\""; break;
            case '\\': out << "\\\\"; break;
            case '\n': out << "\\n"; break;
            case '\r': out << "\\r"; break;
            case '\t': out << "\\t"; break;
            default: out << c;
        }
    }
    return out.str();
}

std::string query_param(const HttpRequest& req, const std::string& key) {
    auto it = req.query.find(key);
    return it == req.query.end() ? "" : it->second;
}

static HttpRequest parse_request(const std::string& raw) {
    std::istringstream stream(raw);
    std::string line;
    HttpRequest req;
    std::getline(stream, line);
    if (!line.empty() && line.back() == '\r') line.pop_back();
    std::istringstream first(line);
    std::string target;
    first >> req.method >> target;
    auto qpos = target.find('?');
    req.path = qpos == std::string::npos ? target : target.substr(0, qpos);
    if (qpos != std::string::npos) {
        std::string query = target.substr(qpos + 1);
        std::stringstream qs(query);
        std::string item;
        while (std::getline(qs, item, '&')) {
            auto eq = item.find('=');
            std::string k = url_decode(item.substr(0, eq));
            std::string v = eq == std::string::npos ? "" : url_decode(item.substr(eq + 1));
            req.query[k] = v;
        }
    }
    while (std::getline(stream, line)) {
        if (line == "\r" || line.empty()) break;
        if (!line.empty() && line.back() == '\r') line.pop_back();
        auto colon = line.find(':');
        if (colon != std::string::npos) {
            std::string key = line.substr(0, colon);
            std::transform(key.begin(), key.end(), key.begin(), [](unsigned char c) { return std::tolower(c); });
            req.headers[key] = trim(line.substr(colon + 1));
        }
    }
    std::string rest((std::istreambuf_iterator<char>(stream)), std::istreambuf_iterator<char>());
    req.body = rest;
    return req;
}

static void handle_client(int client) {
    std::string raw;
    char buf[4096];
    ssize_t n = 0;
    while ((n = recv(client, buf, sizeof(buf), 0)) > 0) {
        raw.append(buf, static_cast<size_t>(n));
        auto hdr = raw.find("\r\n\r\n");
        if (hdr != std::string::npos) {
            size_t content_len = 0;
            auto lower = raw.substr(0, hdr);
            std::transform(lower.begin(), lower.end(), lower.begin(), [](unsigned char c) { return std::tolower(c); });
            auto pos = lower.find("content-length:");
            if (pos != std::string::npos) {
                auto end = lower.find("\r\n", pos);
                content_len = static_cast<size_t>(std::stoul(trim(lower.substr(pos + 15, end - pos - 15))));
            }
            if (raw.size() >= hdr + 4 + content_len) break;
        }
    }
    HttpResponse res;
    try {
        res = route_request(parse_request(raw));
    } catch (const std::exception& ex) {
        res = {500, "application/json", std::string("{\"error\":\"") + json_escape(ex.what()) + "\"}"};
    }
    std::string status = res.status == 200 ? "OK" : (res.status == 403 ? "Forbidden" : (res.status == 404 ? "Not Found" : "Error"));
    std::ostringstream out;
    out << "HTTP/1.1 " << res.status << " " << status << "\r\n"
        << "content-type: " << res.type << "\r\n"
        << "content-length: " << res.body.size() << "\r\n"
        << "connection: close\r\n\r\n"
        << res.body;
    auto text = out.str();
    send(client, text.data(), text.size(), 0);
    close(client);
}

void run_http_server(int port) {
    int server = socket(AF_INET, SOCK_STREAM, 0);
    int yes = 1;
    setsockopt(server, SOL_SOCKET, SO_REUSEADDR, &yes, sizeof(yes));
    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_addr.s_addr = INADDR_ANY;
    addr.sin_port = htons(static_cast<uint16_t>(port));
    if (bind(server, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) < 0) throw std::runtime_error("bind failed");
    if (listen(server, 64) < 0) throw std::runtime_error("listen failed");
    while (true) {
        int client = accept(server, nullptr, nullptr);
        if (client >= 0) std::thread(handle_client, client).detach();
    }
}
