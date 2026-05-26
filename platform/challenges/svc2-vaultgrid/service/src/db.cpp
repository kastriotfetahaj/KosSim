#include "db.hpp"

#include <chrono>
#include <sqlite3.h>
#include <stdexcept>

namespace vg {

Database::Database() = default;
Database::Database(const std::string& path) { open(path); }

Database::~Database() {
    if (handle) sqlite3_close(handle);
}

void Database::open(const std::string& path) {
    if (sqlite3_open(path.c_str(), &handle) != SQLITE_OK) {
        std::string err = sqlite3_errmsg(handle);
        sqlite3_close(handle);
        handle = nullptr;
        throw std::runtime_error("sqlite open: " + err);
    }
    exec("PRAGMA journal_mode=WAL;");
    exec("PRAGMA synchronous=NORMAL;");
    exec("PRAGMA foreign_keys=ON;");
    exec("PRAGMA busy_timeout=5000;");
}

void Database::exec(const std::string& sql) {
    char* err = nullptr;
    if (sqlite3_exec(handle, sql.c_str(), nullptr, nullptr, &err) != SQLITE_OK) {
        std::string message = err ? err : "exec failed";
        sqlite3_free(err);
        throw std::runtime_error("sqlite exec: " + message);
    }
}

int64_t Database::last_insert_rowid() {
    return sqlite3_last_insert_rowid(handle);
}

int64_t Database::now_ms() {
    using namespace std::chrono;
    return duration_cast<milliseconds>(system_clock::now().time_since_epoch()).count();
}

Statement::Statement(Database& db, const std::string& sql) : parent(&db) {
    if (sqlite3_prepare_v2(db.handle, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        std::string err = sqlite3_errmsg(db.handle);
        throw std::runtime_error("prepare: " + err + " (" + sql + ")");
    }
}

Statement::~Statement() {
    if (stmt) sqlite3_finalize(stmt);
}

void Statement::bind(int index, int64_t value) {
    sqlite3_bind_int64(stmt, index, value);
}

void Statement::bind(int index, const std::string& value) {
    sqlite3_bind_text(stmt, index, value.data(), static_cast<int>(value.size()), SQLITE_TRANSIENT);
}

void Statement::bind_null(int index) {
    sqlite3_bind_null(stmt, index);
}

bool Statement::step() {
    int rc = sqlite3_step(stmt);
    if (rc == SQLITE_ROW) return true;
    if (rc == SQLITE_DONE) return false;
    throw std::runtime_error(std::string("step: ") + sqlite3_errmsg(parent->handle));
}

int64_t Statement::column_int(int index) {
    return sqlite3_column_int64(stmt, index);
}

std::string Statement::column_text(int index) {
    const unsigned char* text = sqlite3_column_text(stmt, index);
    int n = sqlite3_column_bytes(stmt, index);
    if (!text) return {};
    return std::string(reinterpret_cast<const char*>(text), static_cast<size_t>(n));
}

void Statement::reset() {
    sqlite3_reset(stmt);
    sqlite3_clear_bindings(stmt);
}

}  // namespace vg
