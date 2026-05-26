#include "routes.hpp"

#include "accounts.hpp"
#include "audit.hpp"
#include "codec.hpp"
#include "crypto_util.hpp"
#include "json.hpp"
#include "proxy.hpp"
#include "state.hpp"
#include "ui.hpp"

#include <fstream>
#include <sstream>

namespace {

bool authorized(const HttpRequest& req, const VaultState& state) {
    auto a = req.headers.find("x-checker-secret");
    auto b = req.headers.find("x-service-secret");
    std::string sent = a != req.headers.end() ? a->second
                                              : (b != req.headers.end() ? b->second : "");
    return !sent.empty() && sent == state.checker_secret;
}

HttpResponse json(int status, const std::string& body) {
    return {status, "application/json", body, {}};
}

std::vector<std::string> split_path(const std::string& path) {
    std::vector<std::string> parts;
    std::stringstream ss(path);
    std::string part;
    while (std::getline(ss, part, '/'))
        if (!part.empty()) parts.push_back(part);
    return parts;
}

HttpResponse eno_task(const HttpRequest& req) {
    auto& state = global_state();
    if (!authorized(req, state)) return json(403, "{\"error\":\"forbidden\"}");
    std::string method = json_string(req.body, "method");
    for (auto& c : method) c = static_cast<char>(std::toupper(static_cast<unsigned char>(c)));
    int tick = json_int(req.body, "related_round_id", json_int(req.body, "current_round_id", 0));
    int payload = json_int(req.body, "variant_id", 0);
    if (method == "PUTFLAG") {
        std::string flag = json_string(req.body, "flag");
        if (flag.empty())
            return json(200, "{\"result\":\"INTERNAL_ERROR\",\"message\":\"missing flag\"}");
        std::string info = state.put_flag(tick, payload, flag);
        return json(200, std::string("{\"result\":\"OK\",\"attack_info\":\"") + vg::json_escape(info) + "\"}");
    }
    if (method == "GETFLAG") {
        bool ok = state.get_flag(tick, payload, json_string(req.body, "flag"));
        return json(200, std::string("{\"result\":\"") + (ok ? "OK" : "MUMBLE") + "\"}");
    }
    if (method == "PUTNOISE") {
        state.put_noise(tick, payload);
        return json(200, "{\"result\":\"OK\"}");
    }
    if (method == "GETNOISE") {
        bool ok = state.get_noise(tick, payload);
        return json(200, std::string("{\"result\":\"") + (ok ? "OK" : "MUMBLE") + "\"}");
    }
    if (method == "HAVOC") {
        bool ok = state.havoc(tick, payload);
        return json(200, std::string("{\"result\":\"") + (ok ? "OK" : "MUMBLE") + "\"}");
    }
    return json(200, "{\"result\":\"OK\"}");
}

HttpResponse list_objects() {
    auto& state = global_state();
    std::lock_guard<std::mutex> guard(state.db.mu);
    std::ostringstream out;
    out << "{\"objects\":[";
    bool first = true;
    for (const auto& [_, obj] : state.objects) {
        if (!first) out << ",";
        first = false;
        out << "{\"object\":\"" << obj.id << "\",\"meta\":\"" << obj.meta_id
            << "\",\"lease\":\"" << obj.lease_id << "\",\"payload\":" << obj.payload
            << ",\"public\":" << (obj.public_object ? "true" : "false") << "}";
    }
    out << "]}";
    return json(200, out.str());
}

HttpResponse proxy_to(const std::string& host, int port, const HttpRequest& req) {
    std::string path = req.path;
    if (!req.query.empty()) {
        path += "?";
        bool first = true;
        for (const auto& [k, v] : req.query) {
            if (!first) path += "&";
            first = false;
            path += k + "=" + v;
        }
    }
    std::map<std::string, std::string> headers;
    auto ct = req.headers.find("content-type");
    if (ct != req.headers.end()) headers["content-type"] = ct->second;
    auto resp = vg::http_request(req.method, host, port, path, req.body, headers);
    if (resp.status == 0) {
        return json(502, "{\"error\":\"sidecar_unavailable\"}");
    }
    return HttpResponse{resp.status, resp.content_type.empty() ? "application/json" : resp.content_type, resp.body, {}};
}

HttpResponse handle_audit_recent(const HttpRequest& req) {
    auto& state = global_state();
    auto user = vg::accounts_current_user(state.db, state.checker_secret, req);
    if (!user || user->role != "admin") return json(403, "{\"error\":\"admin_only\"}");
    std::lock_guard<std::mutex> guard(state.db.mu);
    auto rows = vg::audit_recent(state.db, std::stoll(query_param(req, "limit").empty() ? "50" : query_param(req, "limit")));
    std::ostringstream out;
    out << "{\"entries\":[";
    bool first = true;
    for (const auto& row : rows) {
        if (!first) out << ",";
        first = false;
        out << "{\"id\":" << row.id << ",\"actor\":\"" << vg::json_escape(row.actor)
            << "\",\"action\":\"" << vg::json_escape(row.action)
            << "\",\"target\":\"" << vg::json_escape(row.target)
            << "\",\"ts\":" << row.ts << "}";
    }
    out << "]}";
    return json(200, out.str());
}

}  // namespace

HttpResponse route_request(const HttpRequest& req) {
    auto& state = global_state();
    if (req.path == "/" && req.method == "GET") return {200, "text/html; charset=utf-8", index_html(), {}};
    if (req.path == "/static/styles.css") return {200, "text/css", read_static("styles.css"), {}};
    if (req.path == "/static/app.js") return {200, "application/javascript", read_static("app.js"), {}};
    if (req.path == "/health")
        return json(200, "{\"status\":\"up\",\"name\":\"vaultgrid\",\"service\":\"" + state.team + "/" + state.service + "\"}");
    if (req.path == "/whoami")
        return json(200, "{\"team\":\"" + state.team + "\",\"service\":\"" + state.service + "\",\"runtime\":\"cpp20-polyglot\"}");
    if (req.path == "/service") {
        if (!authorized(req, state)) return json(403, "{\"error\":\"forbidden\"}");
        return json(200, "{\"serviceName\":\"vaultgrid\",\"flagVariants\":3,\"noiseVariants\":3,\"havocVariants\":9}");
    }
    if (req.path == "/" && req.method == "POST") return eno_task(req);
    if (req.path == "/api/objects") return list_objects();

    auto parts = split_path(req.path);
    if (parts.size() == 4 && parts[0] == "api" && parts[1] == "repair") {
        std::lock_guard<std::mutex> guard(state.db.mu);
        std::string object_id = parts[2], shard = parts[3], ticket = query_param(req, "ticket");
        auto it = state.objects.find(object_id);
        if (it == state.objects.end()) return json(404, "{\"error\":\"missing\"}");
        if (ticket.rfind(object_id + ":repair:", 0) != 0) return json(403, "{\"error\":\"bad_ticket\"}");
        int idx = shard == "s0" ? 0 : (shard == "s1" ? 1 : (shard == "s2" ? 2 : -1));
        if (idx < 0) return json(404, "{\"error\":\"missing_shard\"}");
        return json(200, "{\"shard\":\"" + shard + "\",\"hex\":\"" + it->second.shards[static_cast<size_t>(idx)] + "\"}");
    }
    if (parts.size() == 4 && parts[0] == "api" && parts[1] == "lease" && parts[3] == "ticket") {
        std::lock_guard<std::mutex> guard(state.db.mu);
        auto it = state.lease_to_object.find(parts[2]);
        if (it == state.lease_to_object.end()) return json(404, "{\"error\":\"missing_lease\"}");
        return json(200, "{\"ticket\":\"" + it->second + ":repair:s0\"}");
    }
    if (req.path == "/api/rebuild" && req.method == "POST") {
        std::lock_guard<std::mutex> guard(state.db.mu);
        auto object_id = json_string(req.body, "object");
        auto it = state.objects.find(object_id);
        if (it == state.objects.end()) return json(404, "{\"error\":\"missing\"}");
        return json(200, "{\"preview_hex\":\"" + to_hex(xor_shards(it->second.shards)) + "\",\"mode\":\"quorum-preview\"}");
    }
    if (parts.size() == 3 && parts[0] == "api" && parts[1] == "meta") {
        std::lock_guard<std::mutex> guard(state.db.mu);
        auto it = state.meta_to_object.find(parts[2]);
        if (it == state.meta_to_object.end()) return json(404, "{\"error\":\"missing_meta\"}");
        const auto& obj = state.objects[it->second];
        std::string view = query_param(req, "view");
        std::string limit_str = query_param(req, "limit");
        int limit = limit_str.empty() ? 32 : std::stoi(limit_str);
        if (view == "truncated" && limit > 4096) {
            return json(200, "{\"meta\":\"" + obj.meta_id + "\",\"overflow_hex\":\"" + to_hex(obj.body) + "\"}");
        }
        return json(200, "{\"meta\":\"" + obj.meta_id + "\",\"class\":\"erasure-v2\"}");
    }

    if (req.path == "/api/accounts/register" && req.method == "POST")
        return vg::accounts_register(state.db, state.checker_secret, req);
    if (req.path == "/api/accounts/login" && req.method == "POST")
        return vg::accounts_login(state.db, state.checker_secret, req);
    if (req.path == "/api/accounts/me" && req.method == "GET")
        return vg::accounts_me(state.db, state.checker_secret, req);
    if (req.path == "/api/accounts/logout" && req.method == "POST")
        return vg::accounts_logout(state.db, state.checker_secret, req);

    if (req.path == "/api/audit/recent" && req.method == "GET") return handle_audit_recent(req);

    if (parts.size() >= 2 && parts[0] == "api" && parts[1] == "crypt") {
        return proxy_to(state.crypt_host, state.crypt_port, req);
    }
    if (parts.size() >= 2 && parts[0] == "api" && parts[1] == "feed") {
        return proxy_to(state.feed_host, state.feed_port, req);
    }

    if (req.path == "/api/indexer/stats") {
        std::lock_guard<std::mutex> guard(state.db.mu);
        int64_t objects_count = 0, audit_count = 0;
        {
            vg::Statement stmt(state.db, "SELECT COUNT(*) FROM objects");
            if (stmt.step()) objects_count = stmt.column_int(0);
        }
        {
            vg::Statement stmt(state.db, "SELECT COUNT(*) FROM audit");
            if (stmt.step()) audit_count = stmt.column_int(0);
        }
        std::ostringstream out;
        out << "{\"objects\":" << objects_count << ",\"audit\":" << audit_count
            << ",\"ts\":" << state.db.now_ms() << "}";
        return json(200, out.str());
    }

    return json(404, "{\"error\":\"not_found\"}");
}
