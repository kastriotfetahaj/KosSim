#pragma once
#include <memory>
#include <mutex>
#include <string>
#include <vector>

struct sqlite3;
struct sqlite3_stmt;

namespace vg {

class Database;

struct Statement {
    Statement(Database& db, const std::string& sql);
    Statement(Statement&&) = default;
    Statement& operator=(Statement&&) = default;
    ~Statement();
    Statement(const Statement&) = delete;
    Statement& operator=(const Statement&) = delete;

    void bind(int index, int64_t value);
    void bind(int index, const std::string& value);
    void bind_null(int index);
    bool step();
    int64_t column_int(int index);
    std::string column_text(int index);
    void reset();

    sqlite3_stmt* stmt = nullptr;
    Database* parent = nullptr;
};

class Database {
public:
    Database();
    explicit Database(const std::string& path);
    ~Database();

    void open(const std::string& path);
    void exec(const std::string& sql);

    int64_t last_insert_rowid();
    int64_t now_ms();

    std::mutex mu;
    sqlite3* handle = nullptr;
};

}  // namespace vg
