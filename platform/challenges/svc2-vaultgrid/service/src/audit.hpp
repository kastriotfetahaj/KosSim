#pragma once
#include "db.hpp"
#include <string>
#include <vector>

namespace vg {

struct AuditRow {
    int64_t id;
    std::string actor;
    std::string action;
    std::string target;
    int64_t ts;
};

void audit_record(Database& db, const std::string& actor, const std::string& action, const std::string& target);
std::vector<AuditRow> audit_recent(Database& db, int64_t limit);
void audit_trim(Database& db, int64_t keep);

}  // namespace vg
