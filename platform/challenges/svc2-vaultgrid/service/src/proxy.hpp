#pragma once
#include <map>
#include <string>

namespace vg {

struct ProxyResponse {
    int status = 0;
    std::string body;
    std::string content_type;
};

ProxyResponse http_request(
    const std::string& method,
    const std::string& host,
    int port,
    const std::string& path,
    const std::string& body = "",
    const std::map<std::string, std::string>& headers = {}
);

}  // namespace vg
