#pragma once
#include "db.hpp"
#include "http.hpp"
#include <optional>
#include <string>

namespace vg {

struct UserRow {
    int64_t id;
    std::string username;
    std::string role;
};

void accounts_init(Database& db);

HttpResponse accounts_register(Database& db, const std::string& secret, const HttpRequest& req);
HttpResponse accounts_login(Database& db, const std::string& secret, const HttpRequest& req);
HttpResponse accounts_me(Database& db, const std::string& secret, const HttpRequest& req);
HttpResponse accounts_logout(Database& db, const std::string& secret, const HttpRequest& req);

std::optional<UserRow> accounts_current_user(Database& db, const std::string& secret, const HttpRequest& req);

}  // namespace vg
