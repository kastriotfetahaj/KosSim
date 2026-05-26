#pragma once
#include "db.hpp"
#include <map>
#include <mutex>
#include <optional>
#include <string>
#include <vector>

struct VaultObject {
    std::string id;
    std::string meta_id;
    std::string lease_id;
    std::vector<std::string> shards;
    std::string body;
    int payload = 0;
    bool public_object = false;
};

struct VaultState {
    std::string team;
    std::string service;
    std::string checker_secret;
    std::string data_dir;
    std::string crypt_host;
    int crypt_port = 4102;
    std::string feed_host;
    int feed_port = 4103;
    std::map<std::string, VaultObject> objects;
    std::map<std::string, std::string> lease_to_object;
    std::map<std::string, std::string> meta_to_object;
    vg::Database db;

    void init();
    void seed();

    std::string put_flag(int tick, int payload, const std::string& flag);
    bool get_flag(int tick, int payload, const std::string& expected);
    void put_noise(int tick, int payload);
    bool get_noise(int tick, int payload);
    bool havoc(int tick, int payload);

    void persist_object(const VaultObject& obj, int tick);
    void index_flag(int tick, int variant, const std::string& flag, const std::string& reference);
    std::optional<std::string> lookup_flag_reference(int tick, int variant);
    std::string read_flag_index(int tick, int variant);
};

VaultState& global_state();
