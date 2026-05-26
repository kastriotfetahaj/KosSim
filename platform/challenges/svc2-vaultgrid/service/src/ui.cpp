#include "ui.hpp"

#include <fstream>
#include <sstream>

std::string read_static(const std::string& name) {
    std::ifstream in("/app/static/" + name);
    std::stringstream buffer;
    buffer << in.rdbuf();
    return buffer.str();
}

std::string index_html() {
    auto html = read_static("index.html");
    return html.empty() ? "<!doctype html><title>VaultGrid</title><h1>VaultGrid</h1>" : html;
}
