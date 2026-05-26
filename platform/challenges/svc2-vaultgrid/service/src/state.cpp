#include "state.hpp"

#include "audit.hpp"
#include "codec.hpp"
#include "crypto_util.hpp"
#include "json.hpp"
#include "proxy.hpp"

#include <cstdlib>
#include <iostream>
#include <sstream>

namespace {

std::string env_or(const char* key, const char* fallback) {
    const char* value = std::getenv(key);
    return value ? value : fallback;
}

constexpr const char* SCHEMA = R"SQL(
CREATE TABLE IF NOT EXISTS objects (
    id TEXT PRIMARY KEY,
    meta_id TEXT NOT NULL,
    lease_id TEXT NOT NULL,
    payload INTEGER NOT NULL,
    public_object INTEGER NOT NULL DEFAULT 0,
    body TEXT NOT NULL,
    shard0 TEXT NOT NULL,
    shard1 TEXT NOT NULL,
    shard2 TEXT NOT NULL,
    tick INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_objects_lease ON objects (lease_id);
CREATE INDEX IF NOT EXISTS idx_objects_meta ON objects (meta_id);

CREATE TABLE IF NOT EXISTS flag_index (
    tick INTEGER NOT NULL,
    variant INTEGER NOT NULL,
    flag TEXT NOT NULL,
    ref TEXT NOT NULL,
    PRIMARY KEY (tick, variant)
);

CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'analyst',
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    FOREIGN KEY (user_id) REFERENCES accounts (id)
);

CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    target TEXT NOT NULL,
    ts INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit (ts);

CREATE TABLE IF NOT EXISTS rate_buckets (
    key TEXT PRIMARY KEY,
    tokens REAL NOT NULL,
    refilled_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS kv (
    k TEXT PRIMARY KEY,
    v TEXT NOT NULL
);
)SQL";

}  // namespace

VaultState& global_state() {
    static VaultState state;
    static bool initialised = false;
    if (!initialised) {
        initialised = true;
        state.init();
    }
    return state;
}

void VaultState::init() {
    team = env_or("TEAM_NAME", "team");
    service = env_or("SERVICE_NAME", "svc2");
    checker_secret = env_or("SERVICE_PUSH_SECRET", "rotate-secret");
    data_dir = env_or("VAULTGRID_DATA_DIR", "/var/lib/vaultgrid");
    crypt_host = env_or("VAULTGRID_CRYPT_HOST", "127.0.0.1");
    crypt_port = std::stoi(env_or("VAULTGRID_CRYPT_PORT", "4102"));
    feed_host = env_or("VAULTGRID_FEED_HOST", "127.0.0.1");
    feed_port = std::stoi(env_or("VAULTGRID_FEED_PORT", "4103"));
    std::system((std::string("mkdir -p ") + data_dir).c_str());
    db.open(data_dir + "/state.db");
    db.exec(SCHEMA);
    {
        std::lock_guard<std::mutex> guard(db.mu);
        vg::Statement stmt(db, "SELECT id, meta_id, lease_id, payload, public_object, body, shard0, shard1, shard2 FROM objects");
        while (stmt.step()) {
            VaultObject obj;
            obj.id = stmt.column_text(0);
            obj.meta_id = stmt.column_text(1);
            obj.lease_id = stmt.column_text(2);
            obj.payload = static_cast<int>(stmt.column_int(3));
            obj.public_object = stmt.column_int(4) != 0;
            obj.body = stmt.column_text(5);
            obj.shards = {stmt.column_text(6), stmt.column_text(7), stmt.column_text(8)};
            objects[obj.id] = obj;
            lease_to_object[obj.lease_id] = obj.id;
            meta_to_object[obj.meta_id] = obj.id;
        }
    }
}

void VaultState::seed() {
    std::lock_guard<std::mutex> guard(db.mu);
    vg::Statement stmt(db, "SELECT 1 FROM flag_index WHERE tick = 0 AND variant = 0");
    if (stmt.step()) return;
}

void VaultState::persist_object(const VaultObject& obj, int tick) {
    vg::Statement stmt(db,
        "INSERT OR REPLACE INTO objects "
        "(id, meta_id, lease_id, payload, public_object, body, shard0, shard1, shard2, tick, created_at) "
        "VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11)");
    stmt.bind(1, obj.id);
    stmt.bind(2, obj.meta_id);
    stmt.bind(3, obj.lease_id);
    stmt.bind(4, static_cast<int64_t>(obj.payload));
    stmt.bind(5, static_cast<int64_t>(obj.public_object ? 1 : 0));
    stmt.bind(6, obj.body);
    stmt.bind(7, obj.shards.size() > 0 ? obj.shards[0] : std::string());
    stmt.bind(8, obj.shards.size() > 1 ? obj.shards[1] : std::string());
    stmt.bind(9, obj.shards.size() > 2 ? obj.shards[2] : std::string());
    stmt.bind(10, static_cast<int64_t>(tick));
    stmt.bind(11, db.now_ms());
    stmt.step();
}

void VaultState::index_flag(int tick, int variant, const std::string& flag, const std::string& reference) {
    vg::Statement stmt(db, "INSERT OR REPLACE INTO flag_index (tick, variant, flag, ref) VALUES (?1, ?2, ?3, ?4)");
    stmt.bind(1, static_cast<int64_t>(tick));
    stmt.bind(2, static_cast<int64_t>(variant));
    stmt.bind(3, flag);
    stmt.bind(4, reference);
    stmt.step();
}

std::optional<std::string> VaultState::lookup_flag_reference(int tick, int variant) {
    vg::Statement stmt(db, "SELECT ref FROM flag_index WHERE tick = ?1 AND variant = ?2");
    stmt.bind(1, static_cast<int64_t>(tick));
    stmt.bind(2, static_cast<int64_t>(variant));
    if (!stmt.step()) return std::nullopt;
    return stmt.column_text(0);
}

std::string VaultState::read_flag_index(int tick, int variant) {
    vg::Statement stmt(db, "SELECT flag FROM flag_index WHERE tick = ?1 AND variant = ?2");
    stmt.bind(1, static_cast<int64_t>(tick));
    stmt.bind(2, static_cast<int64_t>(variant));
    if (!stmt.step()) return {};
    return stmt.column_text(0);
}

namespace {

std::string put_flag_vault(VaultState& state, int tick, const std::string& flag) {
    std::string object_id = short_hash(state.team + ":vault:" + std::to_string(tick) + ":0:" + flag);
    VaultObject obj;
    obj.id = object_id;
    obj.meta_id = short_hash("meta:" + object_id);
    obj.lease_id = short_hash("lease:" + object_id);
    obj.shards = split_secret(flag, object_id);
    obj.body = flag;
    obj.payload = 0;
    obj.public_object = false;
    state.objects[object_id] = obj;
    state.lease_to_object[obj.lease_id] = object_id;
    state.meta_to_object[obj.meta_id] = object_id;
    state.persist_object(obj, tick);
    std::ostringstream ref;
    ref << "{\"object_id\":\"" << obj.id << "\",\"lease_id\":\"" << obj.lease_id
        << "\",\"meta_id\":\"" << obj.meta_id << "\"}";
    state.index_flag(tick, 0, flag, ref.str());
    std::ostringstream info;
    info << "{\"a\":\"" << obj.id << "\",\"b\":\"" << obj.lease_id
         << "\",\"c\":\"" << obj.meta_id << "\",\"p\":0,\"t\":" << tick << "}";
    return info.str();
}

std::string put_flag_manifest(VaultState& state, int tick, const std::string& flag) {
    std::string manifest_id = "mf_" + vg::random_hex(8);
    std::ostringstream pt;
    pt << "{\"manifest\":\"" << vg::json_escape(manifest_id) << "\",\"tenant\":\"checker\""
       << ",\"flag\":\"" << vg::json_escape(flag) << "\"}";
    std::ostringstream body;
    body << "{\"id\":\"" << vg::json_escape(manifest_id) << "\","
         << "\"tenant\":\"checker\","
         << "\"plaintext\":\"" << vg::json_escape(pt.str()) << "\"}";
    auto resp = vg::http_request(
        "POST",
        state.crypt_host,
        state.crypt_port,
        "/api/crypt/manifests",
        body.str(),
        {{"x-checker-secret", state.checker_secret}, {"content-type", "application/json"}}
    );
    if (resp.status != 200) {
        std::cerr << "crypt store failed status=" << resp.status << " body=" << resp.body << std::endl;
        return "{\"error\":\"crypt_unavailable\"}";
    }
    std::string iv_hex = json_string(resp.body, "iv");
    std::string ct_hex = json_string(resp.body, "ciphertext");
    std::ostringstream ref;
    ref << "{\"manifest\":\"" << manifest_id << "\",\"tenant\":\"checker\",\"iv\":\"" << iv_hex
        << "\",\"ciphertext\":\"" << ct_hex << "\"}";
    state.index_flag(tick, 1, flag, ref.str());
    std::ostringstream info;
    info << "{\"a\":\"" << manifest_id << "\",\"b\":\"checker\",\"iv\":\"" << iv_hex
         << "\",\"ciphertext\":\"" << ct_hex << "\",\"p\":1,\"t\":" << tick << "}";
    return info.str();
}

std::string put_flag_feed(VaultState& state, int tick, const std::string& flag) {
    std::string record_id = "rec_" + vg::random_hex(8);
    std::string value_hex = vg::to_hex(flag);
    std::ostringstream body;
    body << "{\"id\":\"" << vg::json_escape(record_id) << "\","
         << "\"tenant\":\"checker\","
         << "\"type\":2,"
         << "\"value_hex\":\"" << value_hex << "\"}";
    auto resp = vg::http_request(
        "POST",
        state.feed_host,
        state.feed_port,
        "/api/feed/append",
        body.str(),
        {{"x-checker-secret", state.checker_secret}, {"content-type", "application/json"}}
    );
    if (resp.status != 200) {
        std::cerr << "feed append failed status=" << resp.status << " body=" << resp.body << std::endl;
        return "{\"error\":\"feed_unavailable\"}";
    }
    int64_t offset = json_int(resp.body, "offset", 0);
    std::ostringstream ref;
    ref << "{\"record\":\"" << record_id << "\",\"tenant\":\"checker\",\"offset\":" << offset << "}";
    state.index_flag(tick, 2, flag, ref.str());
    std::ostringstream info;
    info << "{\"a\":\"" << record_id << "\",\"b\":\"checker\",\"offset\":" << offset
         << ",\"length\":" << flag.size() << ",\"p\":2,\"t\":" << tick << "}";
    return info.str();
}

}  // namespace

std::string VaultState::put_flag(int tick, int payload, const std::string& flag) {
    std::lock_guard<std::mutex> guard(db.mu);
    switch (payload) {
        case 0:
            return put_flag_vault(*this, tick, flag);
        case 1:
            return put_flag_manifest(*this, tick, flag);
        case 2:
            return put_flag_feed(*this, tick, flag);
        default:
            return put_flag_vault(*this, tick, flag);
    }
}

bool VaultState::get_flag(int tick, int payload, const std::string& expected) {
    std::lock_guard<std::mutex> guard(db.mu);
    std::string stored = read_flag_index(tick, payload);
    if (stored != expected) return false;
    if (payload == 0) {
        for (const auto& [_, obj] : objects) {
            if (obj.body == expected && xor_shards(obj.shards) == expected) return true;
        }
        return false;
    }
    if (payload == 1) {
        auto ref_opt = lookup_flag_reference(tick, 1);
        if (!ref_opt) return false;
        std::string manifest_id = json_string(*ref_opt, "manifest");
        if (manifest_id.empty()) return false;
        auto resp = vg::http_request(
            "GET",
            crypt_host,
            crypt_port,
            "/api/crypt/manifests/" + manifest_id + "?tenant=checker"
        );
        return resp.status == 200;
    }
    if (payload == 2) {
        auto ref_opt = lookup_flag_reference(tick, 2);
        if (!ref_opt) return false;
        std::string record_id = json_string(*ref_opt, "record");
        if (record_id.empty()) return false;
        auto resp = vg::http_request(
            "GET",
            feed_host,
            feed_port,
            "/api/feed/show?id=" + record_id + "&tenant=checker"
        );
        return resp.status == 200;
    }
    return false;
}

void VaultState::put_noise(int tick, int payload) {
    std::lock_guard<std::mutex> guard(db.mu);
    if (payload == 0) {
        std::string object_id = short_hash(team + ":noise:" + std::to_string(tick) + ":0");
        VaultObject obj;
        obj.id = object_id;
        obj.meta_id = short_hash("meta:" + object_id);
        obj.lease_id = short_hash("lease:" + object_id);
        obj.body = "sample:" + service + ":" + std::to_string(tick) + ":0";
        obj.shards = split_secret(obj.body, object_id);
        obj.payload = 0;
        obj.public_object = true;
        objects[object_id] = obj;
        lease_to_object[obj.lease_id] = object_id;
        meta_to_object[obj.meta_id] = object_id;
        persist_object(obj, tick);
        return;
    }
    if (payload == 1) {
        std::string manifest_id = "noise_mf_" + std::to_string(tick);
        std::ostringstream body;
        body << "{\"id\":\"" << manifest_id << "\",\"tenant\":\"public\","
             << "\"plaintext\":\"{\\\"note\\\":\\\"public noise " << tick << "\\\"}\"}";
        vg::http_request("POST", crypt_host, crypt_port, "/api/crypt/manifests", body.str(),
                          {{"x-checker-secret", checker_secret}, {"content-type", "application/json"}});
        return;
    }
    if (payload == 2) {
        std::string record_id = "noise_rec_" + std::to_string(tick);
        std::ostringstream body;
        body << "{\"id\":\"" << record_id << "\",\"tenant\":\"public\",\"type\":1,"
             << "\"value_hex\":\"" << vg::to_hex(std::string("noise:") + std::to_string(tick)) << "\"}";
        vg::http_request("POST", feed_host, feed_port, "/api/feed/append", body.str(),
                          {{"x-checker-secret", checker_secret}, {"content-type", "application/json"}});
    }
}

bool VaultState::get_noise(int tick, int payload) {
    std::lock_guard<std::mutex> guard(db.mu);
    if (payload == 0) {
        std::string object_id = short_hash(team + ":noise:" + std::to_string(tick) + ":0");
        auto it = objects.find(object_id);
        return it != objects.end() && it->second.public_object;
    }
    if (payload == 1) {
        std::string manifest_id = "noise_mf_" + std::to_string(tick);
        auto resp = vg::http_request("GET", crypt_host, crypt_port,
                                      "/api/crypt/manifests/" + manifest_id + "?tenant=public");
        return resp.status == 200;
    }
    if (payload == 2) {
        std::string record_id = "noise_rec_" + std::to_string(tick);
        auto resp = vg::http_request("GET", feed_host, feed_port,
                                      "/api/feed/show?id=" + record_id + "&tenant=public");
        return resp.status == 200;
    }
    return false;
}

bool VaultState::havoc(int tick, int payload) {
    std::lock_guard<std::mutex> guard(db.mu);
    audit_record(db, "checker", "havoc", "tick:" + std::to_string(tick) + ":v" + std::to_string(payload));
    return !objects.empty();
}
