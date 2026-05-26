#pragma once
#include <map>
#include <string>

struct HttpRequest {
    std::string method;
    std::string path;
    std::map<std::string, std::string> query;
    std::map<std::string, std::string> headers;
    std::string body;
};

struct HttpResponse {
    int status = 200;
    std::string type = "application/json";
    std::string body = "{}";
    std::map<std::string, std::string> extra_headers;
};

std::string url_decode(const std::string& in);
std::string query_param(const HttpRequest& req, const std::string& key);
void run_http_server(int port);
