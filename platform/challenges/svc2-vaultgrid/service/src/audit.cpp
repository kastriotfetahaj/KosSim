#include "audit.hpp"

namespace vg {

void audit_record(Database& db, const std::string& actor, const std::string& action, const std::string& target) {
    Statement stmt(db, "INSERT INTO audit (actor, action, target, ts) VALUES (?1, ?2, ?3, ?4)");
    stmt.bind(1, actor);
    stmt.bind(2, action);
    stmt.bind(3, target);
    stmt.bind(4, db.now_ms());
    stmt.step();
}

std::vector<AuditRow> audit_recent(Database& db, int64_t limit) {
    if (limit < 1) limit = 1;
    if (limit > 200) limit = 200;
    Statement stmt(db, "SELECT id, actor, action, target, ts FROM audit ORDER BY id DESC LIMIT ?1");
    stmt.bind(1, limit);
    std::vector<AuditRow> rows;
    while (stmt.step()) {
        rows.push_back(AuditRow{
            stmt.column_int(0),
            stmt.column_text(1),
            stmt.column_text(2),
            stmt.column_text(3),
            stmt.column_int(4),
        });
    }
    return rows;
}

void audit_trim(Database& db, int64_t keep) {
    Statement stmt(db, "DELETE FROM audit WHERE id NOT IN (SELECT id FROM audit ORDER BY id DESC LIMIT ?1)");
    stmt.bind(1, keep);
    stmt.step();
}

}  // namespace vg
