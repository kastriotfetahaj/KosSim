#include "http.hpp"
#include "state.hpp"

#include <chrono>
#include <iostream>
#include <thread>

int main() {
    try {
        auto& state = global_state();
        state.seed();
        std::thread([&state]() {
            while (true) {
                std::this_thread::sleep_for(std::chrono::seconds(60));
                std::lock_guard<std::mutex> guard(state.db.mu);
                try {
                    state.db.exec("DELETE FROM sessions WHERE expires_at < strftime('%s', 'now')");
                    state.db.exec("DELETE FROM rate_buckets WHERE refilled_at < strftime('%s', 'now') * 1000 - 3600000");
                    state.db.exec("DELETE FROM audit WHERE id NOT IN (SELECT id FROM audit ORDER BY id DESC LIMIT 5000)");
                } catch (const std::exception& ex) {
                    std::cerr << "indexer cycle failed: " << ex.what() << std::endl;
                }
            }
        }).detach();
        run_http_server(8080);
    } catch (const std::exception& ex) {
        std::cerr << "vaultgrid failed: " << ex.what() << "\n";
        return 1;
    }
    return 0;
}
