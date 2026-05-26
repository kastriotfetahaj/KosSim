#pragma once
#include <string>
#include <vector>

std::string short_hash(const std::string& input);
std::string to_hex(const std::string& bytes);
std::string from_hex(const std::string& hex);
std::vector<std::string> split_secret(const std::string& flag, const std::string& object_id);
std::string xor_shards(const std::vector<std::string>& shards);
