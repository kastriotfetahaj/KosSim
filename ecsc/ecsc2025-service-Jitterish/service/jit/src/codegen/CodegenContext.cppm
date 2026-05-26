module;

#include <iostream>
#include <ranges>
#include <stack>
#include "../rtlib/jit_values.h"

export module CodegenContext;

export enum Register {
    None = 0,
    RAX,
    RDI,
    RSI,
    RDX,
    RCX,
    R8,
    R9,
    R10,
    R11,
    RBX,
    R12,
    R13,
    R14,
    R15,

    MAX_REGISTER_VALUE
};

struct RegisterInfo {
    const char *name;
    bool callerSaved;
};

static RegisterInfo infos[MAX_REGISTER_VALUE] = {
        {"INVALID-REGISTER", false},
        {"%rax",             true},
        {"%rdi",             true},
        {"%rsi",             true},
        {"%rdx",             true},
        {"%rcx",             true},
        {"%r8",              true},
        {"%r9",              true},
        {"%r10",             true},
        {"%r11",             true},
        {"%rbx",             false},
        {"%r12",             false},
        {"%r13",             false},
        {"%r14",             false},
        {"%r15",             false},
};

export std::ostream &operator<<(std::ostream &out, const Register &r) {
    out << infos[r].name;
    return out;
}


export class CodegenContext {
    std::array<bool, MAX_REGISTER_VALUE> registerTaken;
    int labelCount = 0;
public:
    std::ostream &out;

    explicit CodegenContext(std::ostream &out) : out(out) {
        for (int r = None; r < MAX_REGISTER_VALUE; r++) {
            releaseRegister((Register) r);
        }
    }

    Register takeRegister() {
        for (int r = Register::R15; r > Register::None; r--) {
            if (!registerTaken[r]) {
                registerTaken[r] = true;
                return (Register) r;
            }
        }
        throw std::runtime_error("no registers available");
    }

    void releaseRegister(Register r) {
        registerTaken[r] = false;
    }

    // === overall functions ===
    void start() {
        out << ".section .note.GNU-stack,\"\",@progbits\n";
        out << ".text\n";
    }

    void end() {}

    void startFunction(std::string name, int stackSize) {
        if (stackSize % 16 == 0) stackSize += 8;
        out << ".globl " << name << "\n";
        out << ".p2align 4\n";
        out << ".type " << name << ", @function\n";
        out << name << ":\n";
        out << "enter $" << stackSize << ", $0\n";
        out << "pushq %rbx\n";
        out << "pushq %r12\n";
        out << "pushq %r13\n";
        out << "pushq %r14\n";
        out << "pushq %r15\n";
    }

    void returnFunction(Register r) {
        if (r == Register::None) {
            out << "movq $0, %rax\n";
        } else if (r != Register::RAX) {
            out << "movq " << r << ", %rax\n";
        }
        endFunction();
    }

    void endFunction() {
        out << "popq %r15\n";
        out << "popq %r14\n";
        out << "popq %r13\n";
        out << "popq %r12\n";
        out << "popq %rbx\n";
        out << "leave\n";
        out << "ret\n\n";
    }

    // === asm utility functions ===

    std::stack<Register> pushTakenRegistersBeforeCall() {
        std::stack<Register> result;
        for (int i = 0; i < registerTaken.size(); i++) {
            if (registerTaken[i] && infos[i].callerSaved) {
                out << "pushq " << (Register) i << "\n";
                result.push((Register) i);
            }
        }
        if (result.size() % 2 == 1) {
            out << "pushq " << Register::RDI << "\n";
            result.push(Register::RDI);
        }
        return result;
    }

    void popTakenRegistersAfterCall(std::stack<Register> registers) {
        while (!registers.empty()) {
            out << "popq " << registers.top() << "\n";
            registers.pop();
        }
    }

    void prepareCallArgs(int count) {
        int bytes = ((count + 1) / 2) * 16;
        out << "subq $" << bytes << ", %rsp\n";
    }

    void removeCallArgs(int count) {
        int bytes = ((count + 1) / 2) * 16;
        out << "addq $" << bytes << ", %rsp\n";
    }

    void writeCallArg(int num, Register r) {
        out << "movq " << r << ", " << (num * 8) << "(%rsp)\n";
        releaseRegister(r);
    }

    Register call(std::string name) {
        out << "call " << name << "\n";

        auto result = Register::RAX;
        if (registerTaken[Register::RAX]) {
            result = takeRegister();
            out << "movq " << Register::RAX << ", " << result << "\n";
        } else {
            registerTaken[Register::RAX] = true;
        }
        return result;
    }

    Register callRuntime(std::string name, Register arg1 = Register::None, Register arg2 = Register::None, Register arg3 = Register::None) {
        if (arg1 != Register::None && arg1 != Register::RDI) {
            out << "movq " << arg1 << ", " << Register::RDI << "\n";
            releaseRegister(arg1);
        }
        if (arg2 != Register::None && arg2 != Register::RSI) {
            out << "movq " << arg2 << ", " << Register::RSI << "\n";
            releaseRegister(arg2);
        }
        if (arg3 != Register::None && arg3 != Register::RDX) {
            out << "movq " << arg3 << ", " << Register::RDX << "\n";
            releaseRegister(arg3);
        }

        auto storedRegisters = pushTakenRegistersBeforeCall();
        auto result = call(name);
        popTakenRegistersAfterCall(storedRegisters);

        return result;
    }

    Register constantValue(Value v) {
        auto reg = takeRegister();
        out << "movq $" << v.raw() << ", " << reg << "\n";
        return reg;
    }

    Register constantFromJson(const std::string &json) {
        labelToRegister(stringConstant(json), Register::RDI);
        out << "movq $" << json.size() << ", " << Register::RSI << "\n";
        return callRuntime("jit_rt_constant", Register::RDI, Register::RSI);
    }

    Register stackLoad(int offset) {
        auto reg = takeRegister();
        out << "movq " << offset << "(%rbp), " << reg << "\n";
        return reg;
    }

    void stackStore(int offset, Register reg) {
        out << "movq " << reg << ", " << offset << "(%rbp)\n";
    }

    std::string stringConstant(const std::string &s) {
        auto label = ".L.str" + std::to_string(labelCount++);
        out << ".section .rodata,\"a\",@progbits\n";
        out << label << ": .asciz \"" << std::oct;
        for (auto c: s) out << "\\" << (int) c;
        out << "\"\n" << std::dec;
        out << ".text\n";
        return label;
    }

    void labelToRegister(const std::string &label, Register reg) {
        if (label.contains("@GOTPCREL")) { 
            out << "movq " << label << "(%rip), " << reg << "\n";
        } else { 
            out << "leaq " << label << "(%rip), " << reg << "\n";
        }
    }

    std::string createLabel() {
        return "lbl" + std::to_string(labelCount++);
    }

    void emitLabel(const std::string& label) {
        out << label << ":\n";
    }

    void jump(const std::string &label) {
        out << "jmp " << label << "\n";
    }

    void jumpIfZero(Register r, const std::string &label) {
        out << "test " << r << ", " << r << "\n";
        out << "jz " << label << "\n";
        releaseRegister(r);
    }

};
