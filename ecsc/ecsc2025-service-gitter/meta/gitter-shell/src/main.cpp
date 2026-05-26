#include <cpr/cpr.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdlib.h>
#include <unistd.h>
#include <nlohmann/json.hpp>

#include <openssl/evp.h>

#include <fstream>
#include <ios>
#include <iostream>
#include <optional>
#include <string>

#define INFO(msg) (std::cerr << msg << std::endl)
#define ERR(msg) (std::cerr << msg << std::endl)

#define ENABLE_DBG 0

#if ENABLE_DBG
#define DEBUG(msg) INFO("DEBUG: " << msg)
#else
#define DEBUG(msg)
#endif

static std::optional<std::string> get_pubkey() {
	const char *path = getenv("SSH_USER_AUTH");

	if (!path) {
		ERR("Not invoked via SSH");
		return std::nullopt;
	}

	std::ifstream f(path);
	if (!f.is_open()) {
		ERR("Cannot open SSH credentials");
		return std::nullopt;
	}

	std::string type;
	f >> type;

	if (type != "publickey") {
		ERR("Not authenticated by public key");
		return std::nullopt;
	}

	// discard whitespace
	f.ignore();

	std::string pubkey;
	std::getline(f, pubkey);

	return pubkey;
}

static std::optional<std::pair<std::string, std::string>> identify() {
	auto pubkey = get_pubkey();
	if (!pubkey) {
		return std::nullopt;
	}

	auto r = cpr::Get(cpr::Url{"http://internal:3000/identify/" + cpr::util::urlEncode(*pubkey)});
	if (r.status_code != 200) {
		return std::nullopt;
	}

	return std::make_pair(r.text, *pubkey);
}

static void git_post_message(const char *format, ...) {
	va_list ap;

	va_start(ap, format);
	int len = vsnprintf(NULL, 0, format, ap);
	va_end(ap);

	if (len < 0) {
		perror("vsprintf");
		exit(EXIT_FAILURE);
	}

	if (len > 65520) {
		ERR("git output line too long.");
		puts("0016ERR Internal Error");
		exit(EXIT_FAILURE);
	}

	printf("%04x", (uint16_t)(len + 4));

	va_start(ap, format);
	vprintf(format, ap);
	va_end(ap);
}

enum class GitPermission {
	READ = 0,
	WRITE = 1,
};

struct GitCommand {
	GitPermission permission;

	std::string repository;
	std::string user;

	std::string permissionString() const {
		switch (permission) {
			case GitPermission::READ:
				return "read";
			case GitPermission::WRITE:
				return "write";
		}

		return "";
	}
};

std::optional<GitCommand> parse_command(std::string user, const char *arg) {
	std::string input(arg);
	size_t offset = input.find(' ');

	if (offset == std::string::npos) {
		return std::nullopt;
	}

	struct GitCommand result;
	result.user = user;

	std::string_view command(input.data(), offset);
	if (command == "git-upload-pack") {
		result.permission = GitPermission::READ;
	} else if (command == "git-receive-pack") {
		result.permission = GitPermission::WRITE;
	} else {
		return std::nullopt;
	}

	std::string_view repo = input;
	repo.remove_prefix(offset + 2);
	offset = repo.find_first_not_of('/');
	if (offset != std::string::npos) {
		repo.remove_prefix(offset);
	}
	result.repository = std::string(repo);
	result.repository.pop_back();

	return result;
}

bool check_access(const GitCommand &command) {
	auto request = cpr::Get(
			   cpr::Url{"http://internal:3000/get-repositories"},
			   cpr::Parameters{{"user", command.user}});

	nlohmann::json repositories = nlohmann::json::parse(request.text);

	for (const auto& repo : repositories) {
		DEBUG("Repository: " << repo.dump());

		if (repo["name"] == command.repository) {
			return true;
		}
	}

	INFO("You don't have access to this repository.\nMaybe try one of these:");
	for (const auto& repo : repositories) {
		std::string name = repo["name"];
		std::string public_description = repo["public_description"];
		std::string private_description = repo["private_description"];
		INFO("* " << name << ": " << public_description << " - " << private_description);
	}
	
	return false;
}

const char *BANNER =
	"           _  _    _             \n"
	"     __ _ (_)| |_ | |_  ___  _ _ \n"
	"    / _` || ||  _||  _|/ -_)| '_|\n"
	"    \\__. ||_| \\__| \\__|\\___||_|  \n"
	"    |___/ \n\n";

int main(int argc, const char *argv[]) {
	alarm(5);
	auto userResult = identify();

	if (!userResult) {
		ERR("No user");
		exit(EXIT_FAILURE);
	}

	const auto& [user, pubkey] = *userResult;

	if (argc < 2) {
		INFO("Hi " << user << ". You may only access this service via git.");
		exit(EXIT_FAILURE);
	}

	INFO(BANNER);
	INFO("Welcome to gitter \"" << user << "\"!\n");
	DEBUG("Got command \"" << argv[2] << "\"");

	// Little hack to force the compiler to make the buffer overlay the option below
	// by adding an additional scope
	{
		unsigned char raw_key[4096];
		size_t first_pos = pubkey.find(' ');
		if (first_pos == std::string::npos) {
			ERR("Invalid public key");
			exit(EXIT_FAILURE);
		}
		size_t last_pos = pubkey.find(' ', first_pos + 1);

		std::string base64 = pubkey.substr(first_pos, last_pos - first_pos);
		if (base64.size() >= sizeof(raw_key) / 3 * 4) {
			ERR("Pubkey too big");
			exit(EXIT_FAILURE);
		}
		int size = EVP_DecodeBlock(raw_key, (unsigned char *)base64.c_str(), base64.size());
		if (size == -1) {
			ERR("Failed to compute fingerprint");
			exit(EXIT_FAILURE);
		}

		unsigned char fingerprint[EVP_MAX_MD_SIZE];
		unsigned int fingerprint_size = 0;

		EVP_MD_CTX *mdctx = EVP_MD_CTX_create();

		if (!mdctx) {
			ERR("Failed to compute fingerprint");
			exit(EXIT_FAILURE);
		}

		if (!EVP_DigestInit_ex(mdctx, EVP_sha256(), NULL)) {
			ERR("Failed to compute fingerprint");
			exit(EXIT_FAILURE);
		}
		if (!EVP_DigestUpdate(mdctx, raw_key, size)) {
			ERR("Failed to compute fingerprint");
			exit(EXIT_FAILURE);
		}
		if (!EVP_DigestFinal_ex(mdctx, fingerprint, &fingerprint_size)) {
			ERR("Failed to compute fingerprint");
			exit(EXIT_FAILURE);
		}

		EVP_MD_CTX_destroy(mdctx);

		unsigned char fingerprint_base64[64];
		size = EVP_EncodeBlock(fingerprint_base64, fingerprint, fingerprint_size);
		while (size && fingerprint_base64[size - 1] == '=') {
			fingerprint_base64[--size] = 0;
		}
		INFO("Used SSH-Key Fingerprint: SHA256:" << fingerprint_base64);
	}

	struct {
		char padding[0x40];
		std::optional<GitCommand> command;
	} data;
	data.command = parse_command(user, argv[2]);

	DEBUG("User: " << data.command->user);
	if (!check_access(*data.command)) {
		exit(EXIT_FAILURE);
	}

	if (!data.command) {
		ERR("Invalid git command");
		exit(EXIT_FAILURE);
	}

	if (data.command->permission == GitPermission::READ) {
		data.command->repository = "repositories/" + data.command->repository;
		
		char *const args[] = {(char *)"git-upload-pack", data.command->repository.data(), NULL};
		execvp(args[0], args);
		perror("execvp");
	} else {
		data.command->repository = "repositories/" + data.command->repository;

		char *const args[] = {(char *)"git-receive-pack", data.command->repository.data(), NULL};
		execvp(args[0], args);
		perror("execvp");
	}

	return 0;
}
