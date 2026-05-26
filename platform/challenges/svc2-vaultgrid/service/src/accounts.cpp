#include "accounts.hpp"

#include "audit.hpp"
#include "crypto_util.hpp"
#include "json.hpp"

#include <algorithm>
#include <crypt.h>
#include <cstring>
#include <sstream>

namespace vg {

namespace {

constexpr const char* SESSION_COOKIE = "vg_session";
constexpr int64_t SESSION_TTL_SECONDS = 4 * 3600;

bool valid_username(const std::string& name) {
    if (name.size() < 3 || name.size() > 32) return false;
    return std::all_of(name.begin(), name.end(), [](unsigned char c) {
        return std::isalnum(c) || c == '_' || c == '.' || c == '-';
    });
}

std::string random_salt() {
    auto bytes = random_bytes(12);
    static const char* alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789./";
    std::string out;
    for (auto b : bytes) out.push_back(alphabet[b & 0x3f]);
    return out;
}

std::string hash_password(const std::string& password) {
    std::string salt_spec = "$5$rounds=10000$" + random_salt() + "$";
    struct crypt_data data {};
    char* result = crypt_r(password.c_str(), salt_spec.c_str(), &data);
    if (!result) return {};
    return result;
}

bool verify_password(const std::string& stored, const std::string& password) {
    if (stored.empty()) return false;
    struct crypt_data data {};
    char* result = crypt_r(password.c_str(), stored.c_str(), &data);
    if (!result) return false;
    return constant_time_eq(stored, result);
}

std::string sign_session(const std::string& secret, int64_t uid, int64_t exp) {
    std::ostringstream body;
    body << "{\"uid\":" << uid << ",\"exp\":" << exp << "}";
    std::vector<uint8_t> body_bytes(body.str().begin(), body.str().end());
    std::string body_b64 = base64url_encode(body_bytes);
    auto sig = hmac_sha256(secret + ":session", body_b64);
    std::string sig_b64 = base64url_encode(std::vector<uint8_t>(sig.begin(), sig.end()));
    return body_b64 + "." + sig_b64;
}

bool verify_session(const std::string& secret, const std::string& token, int64_t& uid, int64_t& exp) {
    auto dot = token.find('.');
    if (dot == std::string::npos) return false;
    std::string body_b64 = token.substr(0, dot);
    std::string sig_b64 = token.substr(dot + 1);
    auto want = hmac_sha256(secret + ":session", body_b64);
    std::string want_b64 = base64url_encode(std::vector<uint8_t>(want.begin(), want.end()));
    if (!constant_time_eq(want_b64, sig_b64)) return false;
    auto raw = base64url_decode(body_b64);
    std::string body(raw.begin(), raw.end());
    uid = json_int(body, "uid", -1);
    exp = json_int(body, "exp", 0);
    return uid >= 0 && exp > 0;
}

std::string read_cookie(const HttpRequest& req, const std::string& name) {
    auto it = req.headers.find("cookie");
    if (it == req.headers.end()) return {};
    std::stringstream ss(it->second);
    std::string item;
    while (std::getline(ss, item, ';')) {
        auto first = item.find_first_not_of(' ');
        if (first == std::string::npos) continue;
        item = item.substr(first);
        if (item.compare(0, name.size() + 1, name + "=") == 0) {
            return item.substr(name.size() + 1);
        }
    }
    return {};
}

HttpResponse json(int status, const std::string& body) {
    return {status, "application/json", body};
}

HttpResponse set_cookie_response(int status, const std::string& body, const std::string& cookie_value, int64_t max_age) {
    HttpResponse res = json(status, body);
    res.extra_headers["set-cookie"] = std::string(SESSION_COOKIE) + "=" + cookie_value + "; Path=/; HttpOnly; SameSite=Lax; Max-Age=" + std::to_string(max_age);
    return res;
}

int64_t now_seconds() {
    return Database{}.now_ms() / 1000;
}

UserRow user_from_row(Statement& stmt) {
    return UserRow{stmt.column_int(0), stmt.column_text(1), stmt.column_text(2)};
}

}  // namespace

void accounts_init(Database& /*db*/) {
    // Tables are declared in the main schema migration.
}

HttpResponse accounts_register(Database& db, const std::string& secret, const HttpRequest& req) {
    std::string username = json_string(req.body, "username");
    std::string password = json_string(req.body, "password");
    if (!valid_username(username)) return json(400, "{\"error\":\"invalid_username\"}");
    if (password.size() < 8) return json(400, "{\"error\":\"weak_password\"}");
    std::lock_guard<std::mutex> guard(db.mu);
    {
        Statement existing(db, "SELECT id FROM accounts WHERE username = ?1");
        existing.bind(1, username);
        if (existing.step()) return json(409, "{\"error\":\"duplicate\"}");
    }
    std::string hash = hash_password(password);
    if (hash.empty()) return json(500, "{\"error\":\"hash_failed\"}");
    int64_t now = db.now_ms();
    {
        Statement ins(db, "INSERT INTO accounts (username, password_hash, role, created_at) VALUES (?1, ?2, 'analyst', ?3)");
        ins.bind(1, username);
        ins.bind(2, hash);
        ins.bind(3, now);
        ins.step();
    }
    int64_t uid = db.last_insert_rowid();
    audit_record(db, username, "user.register", "user:" + std::to_string(uid));
    int64_t exp = now / 1000 + SESSION_TTL_SECONDS;
    std::string token = sign_session(secret, uid, exp);
    {
        Statement ses(db, "INSERT OR REPLACE INTO sessions (token, user_id, expires_at) VALUES (?1, ?2, ?3)");
        ses.bind(1, token);
        ses.bind(2, uid);
        ses.bind(3, exp);
        ses.step();
    }
    std::ostringstream out;
    out << "{\"id\":" << uid << ",\"username\":\"" << json_escape(username) << "\",\"role\":\"analyst\"}";
    return set_cookie_response(200, out.str(), token, SESSION_TTL_SECONDS);
}

HttpResponse accounts_login(Database& db, const std::string& secret, const HttpRequest& req) {
    std::string username = json_string(req.body, "username");
    std::string password = json_string(req.body, "password");
    std::lock_guard<std::mutex> guard(db.mu);
    Statement select(db, "SELECT id, username, role, password_hash FROM accounts WHERE username = ?1");
    select.bind(1, username);
    if (!select.step()) {
        audit_record(db, username.empty() ? "unknown" : username, "user.login_failed", username);
        return json(401, "{\"error\":\"bad_credentials\"}");
    }
    UserRow user{select.column_int(0), select.column_text(1), select.column_text(2)};
    std::string stored = select.column_text(3);
    if (!verify_password(stored, password)) {
        audit_record(db, username, "user.login_failed", username);
        return json(401, "{\"error\":\"bad_credentials\"}");
    }
    int64_t now = db.now_ms() / 1000;
    int64_t exp = now + SESSION_TTL_SECONDS;
    std::string token = sign_session(secret, user.id, exp);
    {
        Statement ses(db, "INSERT OR REPLACE INTO sessions (token, user_id, expires_at) VALUES (?1, ?2, ?3)");
        ses.bind(1, token);
        ses.bind(2, user.id);
        ses.bind(3, exp);
        ses.step();
    }
    audit_record(db, user.username, "user.login", "user:" + std::to_string(user.id));
    std::ostringstream out;
    out << "{\"id\":" << user.id << ",\"username\":\"" << json_escape(user.username)
        << "\",\"role\":\"" << json_escape(user.role) << "\"}";
    return set_cookie_response(200, out.str(), token, SESSION_TTL_SECONDS);
}

std::optional<UserRow> accounts_current_user(Database& db, const std::string& secret, const HttpRequest& req) {
    std::string token = read_cookie(req, SESSION_COOKIE);
    if (token.empty()) return std::nullopt;
    int64_t uid = -1, exp = 0;
    if (!verify_session(secret, token, uid, exp)) return std::nullopt;
    int64_t now = db.now_ms() / 1000;
    if (exp < now) return std::nullopt;
    std::lock_guard<std::mutex> guard(db.mu);
    Statement ses(db, "SELECT expires_at FROM sessions WHERE token = ?1");
    ses.bind(1, token);
    if (!ses.step()) return std::nullopt;
    if (ses.column_int(0) < now) return std::nullopt;
    Statement u(db, "SELECT id, username, role FROM accounts WHERE id = ?1");
    u.bind(1, uid);
    if (!u.step()) return std::nullopt;
    return UserRow{u.column_int(0), u.column_text(1), u.column_text(2)};
}

HttpResponse accounts_me(Database& db, const std::string& secret, const HttpRequest& req) {
    auto user = accounts_current_user(db, secret, req);
    if (!user) return json(401, "{\"error\":\"auth_required\"}");
    std::ostringstream out;
    out << "{\"id\":" << user->id << ",\"username\":\"" << json_escape(user->username)
        << "\",\"role\":\"" << json_escape(user->role) << "\"}";
    return json(200, out.str());
}

HttpResponse accounts_logout(Database& db, const std::string& /*secret*/, const HttpRequest& req) {
    std::string token = read_cookie(req, SESSION_COOKIE);
    if (!token.empty()) {
        std::lock_guard<std::mutex> guard(db.mu);
        Statement del(db, "DELETE FROM sessions WHERE token = ?1");
        del.bind(1, token);
        del.step();
    }
    return set_cookie_response(200, "{\"ok\":true}", "", 0);
}

}  // namespace vg
