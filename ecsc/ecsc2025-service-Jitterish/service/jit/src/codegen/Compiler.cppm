module;

#include <string>
#include <ranges>
#include <any>
#include "antlr4-runtime.h"
#include "../generated/JitterishLexer.h"
#include "../generated/JitterishParser.h"
#include "../generated/JitterishBaseVisitor.h"
#include "../rtlib/jit_values.h"

export module Compiler;

import CodegenContext;

using namespace antlr4;
using namespace generated_parser;


class Variables : public JitterishBaseVisitor {
    int stackCount = 0;
    int paramCount = 0;
public:
    std::map<std::string, int> offsets;

    int stackSize() const { return stackCount * 8; }

    std::any visitAssignToNamed(JitterishParser::AssignToNamedContext *ctx) override {
        auto name = ctx->NAME()->getText();
        if (offsets.find(name) == offsets.end()) {
            offsets[name] = (++stackCount) * -8;
        }
        return {};
    }

    void addParam(std::string name) {
        offsets[name] = (++paramCount) * 8 + 8;
    }
};


class CodegenVisitor : public JitterishBaseVisitor {
    std::stringstream ss;

    CodegenContext codegen;

    Variables vars;

protected:
    std::any defaultResult() override {
        return std::any(Register::None);
    }

    std::any aggregateResult(std::any aggregate, std::any nextResult) override {
        auto r1 = any_cast<Register>(aggregate);
        auto r2 = any_cast<Register>(nextResult);
        if (r1 == Register::None) return r2;
        if (r2 == Register::None) return r1;
        throw std::runtime_error("not implemented");
    }

    template<class T>
    Register compile(T *ctx) {
        return std::any_cast<Register>(ctx->accept(this));
    }

public:
    CodegenVisitor() : codegen(ss) {}

    std::string str() const { return ss.str(); }

    std::any visitMain(JitterishParser::MainContext *ctx) override {
        codegen.start();
        for (auto f: ctx->func()) {
            compile(f);
        }
        for (auto q: ctx->query()) {
            compile(q);
        }
        codegen.end();
        return Register::None;
    }

    // === Functions ===

    std::any visitFunc(JitterishParser::FuncContext *ctx) override {
        vars = Variables();
        vars.visit(ctx->body);
        for (auto arg: ctx->NAME())
            if (arg->getSymbol() != ctx->name)
                vars.addParam(arg->getText());
        codegen.startFunction(ctx->name->getText(), vars.stackSize());
        compile(ctx->body);
        codegen.returnFunction(Register::None);
        return Register::None;
    }

    std::any visitReturnStmt(JitterishParser::ReturnStmtContext *ctx) override {
        auto reg = compile(ctx->expr());
        codegen.returnFunction(reg);
        codegen.releaseRegister(reg);
        return Register::None;
    }

    std::any visitCallExpr(JitterishParser::CallExprContext *ctx) override {
        if (ctx->callee->getText() == "print")
            return codegen.callRuntime("jit_rt_print", compile(ctx->expr(0)));

        auto saved = codegen.pushTakenRegistersBeforeCall();
        codegen.prepareCallArgs(ctx->expr().size());
        for (size_t i = 0; i < ctx->expr().size(); i++) {
            codegen.writeCallArg(i, compile(ctx->expr(i)));
        }

        auto result = codegen.call(ctx->callee->getText());

        codegen.removeCallArgs(ctx->expr().size());
        codegen.popTakenRegistersAfterCall(saved);
        return result;
    }

    // === Statements ===
    std::any visitIfStmt(JitterishParser::IfStmtContext *ctx) override {
        auto lblElse = codegen.createLabel();
        auto lblEnd = codegen.createLabel();

        auto reg = codegen.callRuntime("jit_rt_bool", compile(ctx->expr()));
        codegen.jumpIfZero(reg, lblElse);
        compile(ctx->caseTrue);
        if (ctx->caseFalse) {
            codegen.jump(lblEnd);
            codegen.emitLabel(lblElse);
            compile(ctx->caseFalse);
        } else {
            codegen.emitLabel(lblElse);
        }
        codegen.emitLabel(lblEnd);

        return Register::None;
    }

    std::any visitWhileStmt(JitterishParser::WhileStmtContext *ctx) override {
        auto lblBegin = codegen.createLabel();
        auto lblEnd = codegen.createLabel();

        codegen.emitLabel(lblBegin);
        auto reg = codegen.callRuntime("jit_rt_bool", compile(ctx->expr()));
        codegen.jumpIfZero(reg, lblEnd);
        compile(ctx->stmt());
        codegen.jump(lblBegin);
        codegen.emitLabel(lblEnd);

        return Register::None;
    }

    // === Expressions ===

    std::any visitExprStmt(JitterishParser::ExprStmtContext *ctx) override {
        codegen.releaseRegister(compile(ctx->expr()));
        return Register::None;
    }

    std::any visitBinaryOp(JitterishParser::BinaryOpContext *ctx) override {
        auto op = ctx->op->getText();
        auto lft = compile(ctx->left);
        auto rght = compile(ctx->rght);
        if (op == "+") {
            return codegen.callRuntime("jit_rt_add", lft, rght);
        } else if (op == "-") {
            return codegen.callRuntime("jit_rt_sub", lft, rght);
        } else if (op == "*") {
            return codegen.callRuntime("jit_rt_mul", lft, rght);
        } else if (op == "/") {
            return codegen.callRuntime("jit_rt_div", lft, rght);
        } else if (op == "==") {
            return codegen.callRuntime("jit_rt_equal", lft, rght);
        } else if (op == "!=") {
            return codegen.callRuntime("jit_rt_not", codegen.callRuntime("jit_rt_equal", lft, rght));
        } else if (op == "<") {
            return codegen.callRuntime("jit_rt_lt", lft, rght);
        } else if (op == ">") {
            return codegen.callRuntime("jit_rt_lt", rght, lft);
        } else if (op == "<=") {
            return codegen.callRuntime("jit_rt_not", codegen.callRuntime("jit_rt_lt", rght, lft));
        } else if (op == ">=") {
            return codegen.callRuntime("jit_rt_not", codegen.callRuntime("jit_rt_lt", lft, rght));
        } else if (op == "&&") {
            return codegen.callRuntime("jit_rt_and", lft, rght);
        } else if (op == "||") {
            return codegen.callRuntime("jit_rt_or", lft, rght);
        } else if (op == "?:") {
            return codegen.callRuntime("jit_rt_default", lft, rght);
        }
        throw std::runtime_error("unknown operator: " + op);
    }

    std::any visitUnaryOp(JitterishParser::UnaryOpContext *ctx) override {
        auto op = ctx->op->getText();
        auto expr = compile(ctx->unary_expr());
        if (op == "!") {
            return codegen.callRuntime("jit_rt_not", expr);
        } else if (op == "-") {
            return codegen.callRuntime("jit_rt_sub", codegen.constantValue(Value {ValueType::INT, 0}), expr);
        } else if (op == "len") {
            return codegen.callRuntime("jit_rt_len", expr);
        } else if (op == "defined") {
            return codegen.callRuntime("jit_rt_defined", expr);
        }
        throw std::runtime_error("unknown operator: " + op);
    }

    std::any visitPropertyGet(JitterishParser::PropertyGetContext *ctx) override {
        auto lft = compile(ctx->left);
        auto rght = compile(ctx->rght);
        return codegen.callRuntime("jit_rt_getproperty", lft, rght);
    }

    std::any visitConstantInt(JitterishParser::ConstantIntContext *ctx) override {
        return codegen.constantValue(Value {ValueType::INT, stoi(ctx->getText())});
    }

    std::any visitConstantExpr(JitterishParser::ConstantExprContext *ctx) override {
        return codegen.constantFromJson(ctx->getText());
    }

    std::any visitArrayExpr(JitterishParser::ArrayExprContext *ctx) override {
        auto array = codegen.callRuntime("jit_rt_array_new");
        for (auto e: ctx->expr()) {
            auto value = compile(e);
            array = codegen.callRuntime("jit_rt_append", array, value);
        }
        return array;
    }

    std::any visitObjectExpr(JitterishParser::ObjectExprContext *ctx) override {
        auto obj = codegen.callRuntime("jit_rt_object_new");
        for (size_t i = 0; i < ctx->STRING_LITERAL().size(); i++) {
            auto value = compile(ctx->expr(i));
            auto key = codegen.constantFromJson(ctx->STRING_LITERAL(i)->getText());
            codegen.out << "movq " << obj << ", " << Register::RDI << "\n";  
            codegen.releaseRegister(codegen.callRuntime("jit_rt_setproperty", Register::RDI, key, value));
        }
        return obj;
    }

    // === Variables ===

    std::any visitNamed(JitterishParser::NamedContext *ctx) override {
        auto name = ctx->NAME()->getText();
        return codegen.stackLoad(vars.offsets.at(name));
    }

    std::any visitAssignment(JitterishParser::AssignmentContext *ctx) override {
        auto value = compile(ctx->rght);
        if (auto named = dynamic_cast<JitterishParser::AssignToNamedContext *>(ctx->left)) {
            codegen.stackStore(vars.offsets.at(named->NAME()->getText()), value);
            return value;
        } else if (auto property = dynamic_cast<JitterishParser::AssignToPropertyContext *>(ctx->left)) {
            auto object = compile(property->left);
            auto key = compile(property->right);
            return codegen.callRuntime("jit_rt_setproperty", object, key, value);
        } else if (auto append = dynamic_cast<JitterishParser::AssignAppendContext *>(ctx->left)) {
            auto array = compile(append->left);
            return codegen.callRuntime("jit_rt_append", array, value);
        } else {
            throw std::runtime_error("not implemented");
        }
    }

    // === Queries ===
    std::any visitQuery(JitterishParser::QueryContext *ctx) override {
        codegen.startFunction(ctx->name->getText(), vars.stackSize());

        codegen.labelToRegister(codegen.stringConstant(ctx->collection->getText()), Register::RDI);
        if (ctx->filter) {
            codegen.labelToRegister(ctx->filter->getText() + "@GOTPCREL", Register::RSI);
        } else {
            codegen.out << "movq $0, " << Register::RSI << "\n";
        }
        if (ctx->map) {
            codegen.labelToRegister(ctx->map->getText() + "@GOTPCREL", Register::RDX);
        } else {
            codegen.out << "movq $0, " << Register::RDX << "\n";
        }
        if (ctx->reduce) {
            codegen.labelToRegister(ctx->reduce->getText() + "@GOTPCREL", Register::RCX);
        } else {
            codegen.out << "movq $0, " << Register::RCX << "\n";
        }
        size_t limit = ctx->limit ? std::stoi(ctx->limit->getText()) : 0xffffffff;
        codegen.out << "movq $" << limit << ", " << Register::R8 << "\n";
        codegen.out << "movq 16(%rbp), " << Register::R9 << "\n";
        codegen.releaseRegister(codegen.call("jit_rt_query"));

        codegen.endFunction();
        return Register::None;
    }
};


class ErrorListener : public BaseErrorListener {
    void syntaxError(Recognizer *recognizer, Token *offendingSymbol, size_t line, size_t charPositionInLine,
                     const std::string &msg, std::exception_ptr e) override {
        throw std::runtime_error("line " + std::to_string(line) + ":" + std::to_string(charPositionInLine) + " " + msg);
    }
};


export std::string compile_string(const std::string &s) {
    ANTLRInputStream input(s);
    JitterishLexer lexer(&input);
    CommonTokenStream tokens(&lexer);
    tokens.fill();

    JitterishParser parser(&tokens);
    ErrorListener errors;
    parser.addErrorListener(&errors);
    tree::ParseTree *tree = parser.main();

    CodegenVisitor v;
    tree->accept(&v);
    return v.str();
}
