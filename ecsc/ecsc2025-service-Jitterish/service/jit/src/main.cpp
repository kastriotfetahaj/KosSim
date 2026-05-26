#include <iostream>
#include <filesystem>

import CodegenContext;
import Compiler;


std::string runtime_library_path() {
    return std::filesystem::absolute(program_invocation_name).parent_path().string();
}

void assemble(std::string code, std::string output) {
    auto runtime_path = runtime_library_path();

    auto assembly_file = output + ".s";
    std::ofstream f(assembly_file);
    f << code;
    f.close();

    std::string cmd = "cc";
    cmd += " -fPIC -g -pie -Wl,-export-dynamic";
    cmd += " -L" + runtime_path + " -Wl,-rpath," + runtime_path;
    cmd += " -ljit_rt";
    cmd += " " + assembly_file + " -o \"" + output + "\"";
    int rc = system(cmd.c_str());
    if (rc != 0)
        throw std::runtime_error("cc failed");
}

std::string load_file(const char *filename) {
    std::ostringstream oss;
    if (std::string(filename) == "-") {
        oss << std::cin.rdbuf();
    } else {
        std::ifstream ifs(filename);
        oss << ifs.rdbuf();
    }
    return oss.str();
}

void file_to_stdout(std::string filename) {
    std::ifstream ifs(filename);
    std::cout << ifs.rdbuf();
}

int main(int argc, const char *argv[]) {
    try {
        if (argc != 3) {
            std::cerr << "USAGE: " << argv[0] << " <INPUT> <OUTPUT>" << std::endl;
            return 1;
        }

        auto program = load_file(argv[1]);
        auto assembly = compile_string(program);
        std::string output = argv[2];
        if (output == "-") {
            assemble(assembly, "/tmp/tmp.so");
            file_to_stdout("/tmp/tmp.so");
        } else {
            assemble(assembly, output);
        }
        return 0;

    } catch (const std::runtime_error &e) {
        std::cerr << e.what() << std::endl;
        std::cout << e.what() << std::endl;
        return 1;
    }
}
