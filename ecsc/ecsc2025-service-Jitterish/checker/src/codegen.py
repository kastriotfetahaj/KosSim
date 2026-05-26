import json
import random
import re
import string
from abc import abstractmethod, ABC
from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import wraps
from types import UnionType
from typing import Any, Generator, TypeAlias, Type, get_args, Callable, TypeVar, Hashable, cast

Value: TypeAlias = int | str | list | dict | None
T = TypeVar('T', bound=Hashable)
T2 = TypeVar('T2', bound=Hashable)


class Undefined:
    def __str__(self) -> str:
        return 'undefined'

    def __repr__(self) -> str:
        return 'undefined'

    def __eq__(self, other: Any) -> bool:
        return other is undefined

    def __bool__(self) -> bool:
        return False


undefined = Undefined()


@dataclass(frozen=True)
class Expr:
    expr: str
    value: Value
    output: tuple[Value, ...] = field(default_factory=lambda: ())
    unmodifiable: bool = False

    def to_json(self) -> dict:
        return {
            'expr': self.expr,
            'value': self.value,
            'output': list(self.output),
        }

    @classmethod
    def from_json(cls, d: dict) -> 'Expr':
        return Expr(d['expr'], d['value'], tuple(d['output']))

    def clone(self) -> 'Expr':
        return Expr(self.expr, clone(self.value), tuple(cast(list, clone(list(self.output)))), unmodifiable=self.unmodifiable)

    def sealed(self) -> 'Expr':
        return Expr(self.expr, self.value, tuple(self.output), unmodifiable=self.unmodifiable or not is_sealed_type(self.value))


@dataclass(frozen=True)
class Stmt:
    code: list[str]
    ctx: 'Context'
    output: list[Value] = field(default_factory=list)


@dataclass(frozen=True)
class Function:
    name: str
    code: str
    params: list[Expr]
    value: Value | Undefined
    output: list[Value] = field(default_factory=list)

    def as_script(self) -> str:
        params = ' '.join(json.dumps(_.value) for _ in self.params)
        code = f'// EXECUTE {self.name} {params}\n\n' + self.code + '\n'
        code += f'\n// Result: {json.dumps(self.value) if self.value is not undefined else "undefined"}'
        for o in self.output:
            code += f'\n// output: {json.dumps(o)}'
        return code


INT_MASK = 0xffffffffffffff


def expr_value(v: Any) -> Value:
    if isinstance(v, Expr):
        return v.value
    if isinstance(v, dict):
        return {expr_value(k): expr_value(v) for k, v in v.items()}
    if isinstance(v, list):
        return [expr_value(_) for _ in v]
    return v


def make_unique(c: Callable[[], T], key: Callable[[T], T2] = lambda x: x) -> Callable[[], T]:
    used: set[T2] = set()

    @wraps(c)
    def wrapper() -> T:
        while True:
            s = c()
            k = key(s)
            if k not in used:
                used.add(k)
                return s

    return wrapper


def clone(x: Value) -> Value:
    if isinstance(x, list):
        return [clone(_) for _ in x]
    if isinstance(x, dict):
        return {k: clone(v) for k, v in x.items()}
    return x


def is_sealed_type(v: Value) -> bool:
    return not isinstance(v, dict) and not isinstance(v, list)


class AliasSensitiveClone:
    def __init__(self) -> None:
        self._d: dict[int, Value] = {}

    def clone(self, x: Value) -> Value:
        if isinstance(x, list):
            if id(x) not in self._d:
                self._d[id(x)] = [self.clone(_) for _ in x]
            return self._d[id(x)]
        if isinstance(x, dict):
            if id(x) not in self._d:
                self._d[id(x)] = {k: self.clone(v) for k, v in x.items()}
            return self._d[id(x)]
        return x


@dataclass
class Collection:
    name: str
    items: list[dict[Expr, Expr]]
    ident_key: Expr
    flag_key: Expr
    flag_item: dict[Expr, Expr]

    def to_ndjson(self) -> str:
        return '\n'.join(json.dumps(expr_value(item)) for item in self.items)

    @property
    def private(self) -> bool:
        return 'private' in self.name

    def to_json(self) -> dict:
        return {
            'name': self.name,
            'items': [[(k.to_json(), v.to_json()) for k, v in item.items()] for item in self.items],
            'ident_key': self.ident_key.to_json(),
            'flag_key': self.flag_key.to_json(),
            'flag_item': [(k.to_json(), v.to_json()) for k, v in self.flag_item.items()],
        }

    @classmethod
    def from_json(cls, d: dict) -> 'Collection':
        return cls(
            name=d['name'],
            items=[{Expr.from_json(k): Expr.from_json(v) for k, v in item} for item in d['items']],
            ident_key=Expr.from_json(d['ident_key']),
            flag_key=Expr.from_json(d['flag_key']),
            flag_item={Expr.from_json(k): Expr.from_json(v) for k, v in d['flag_item']},
        )


@dataclass
class Context:
    vars: dict[str, Value] = field(default_factory=dict)
    funcs: dict[str, Function] = field(default_factory=dict)
    unmodifiable_vars: set[str] = field(default_factory=set)  # names of current function's parameters, and its aliases

    def update_var(self, name: str, value: Value, unmodifiable: bool = False) -> 'Context':
        if unmodifiable and is_sealed_type(value):
            unmodifiable = False
        unmod_vars = self.unmodifiable_vars
        if name in unmod_vars and not unmodifiable:
            unmod_vars = unmod_vars - {name}
        elif name not in unmod_vars and unmodifiable:
            unmod_vars = unmod_vars | {name}
        return Context(vars=self.vars | {name: value}, funcs=self.funcs, unmodifiable_vars=unmod_vars)

    def fork(self) -> 'Context':
        cloner = AliasSensitiveClone()
        return Context(vars=cast(dict, cloner.clone(self.vars)), funcs=self.funcs,
                       unmodifiable_vars=set(self.unmodifiable_vars))


class IdentifierGenerator:
    FIRST_CHAR = string.ascii_letters + "____"
    ALLOWED_CHARS = string.ascii_letters + string.digits + "__"
    CANDIDATES = [
        'undefined',
        'NaN',
        'Infinity',
        'NUL',

        'system',
        'execve',
        'exec',
        'shell_exec',
        'eval',
        'puts',

        'SELECT',
        'INSERT',
        'UPDATE',

        'ProcessBuilder',
    ]

    KEYWORDS = {'query', 'on', 'filter', 'map', 'reduce', 'limit',
                'func', 'return', 'if', 'else', 'while',
                'len', 'defined', 'null', 'true', 'false'}

    def __init__(self) -> None:
        self.used: set[str] = set()
        self.candidates = list(self.CANDIDATES)

    def get(self) -> str:
        while True:
            if len(self.candidates) > 1 and random.randint(0, 100) < 8:
                s = random.choice(self.candidates)
                self.candidates.remove(s)
            else:
                l = random.randint(3, 12)
                s = random.choice(self.FIRST_CHAR) + ''.join(random.choice(self.ALLOWED_CHARS) for _ in range(l - 1))
            if s not in self.used and s not in self.KEYWORDS:
                self.used.add(s)
                return s


class ExprGen(ABC):
    def __init__(self, gen: 'CodeGenerator') -> None:
        self.gen = gen

    def applicable(self, ctx: Context) -> bool:
        return True

    @abstractmethod
    def generate(self, ctx: Context) -> Expr:
        pass


class ExprGenGroup(ExprGen):
    def __init__(self, gens: list[ExprGen]) -> None:
        super().__init__(gens[0].gen)
        self.gens = gens

    def generate(self, ctx: Context) -> Expr:
        if self.gen.current_depth > self.gen.MAX_EXPR_DEPTH:
            return self.gens[0].generate(ctx)
        with self.gen.depth():
            gens = [_ for _ in self.gens if _.applicable(ctx)]
            return random.choice(gens).generate(ctx)


class TypedGen(ExprGen, ABC):
    def __init__(self, gen: 'CodeGenerator', generated_type: Type | UnionType | Any) -> None:
        super().__init__(gen)
        if generated_type == Any:
            self.generated_types: tuple[Type, ...] = ()
        elif isinstance(generated_type, UnionType):
            self.generated_types = tuple(get_args(generated_type))
        else:
            self.generated_types = (generated_type,)

    def match(self, value: Value | Undefined) -> bool:
        return (self.generated_types == () and value is not undefined) or any(type(value) == t for t in self.generated_types)


class VarUse(TypedGen):
    def variables(self, ctx: Context) -> list[tuple[str, Value]]:
        if self.gen.can_alias_unmodifiable:
            return [(k, v) for k, v in ctx.vars.items() if self.match(v)]
        else:
            return [(k, v) for k, v in ctx.vars.items() if k not in ctx.unmodifiable_vars and self.match(v)]

    def applicable(self, ctx: Context) -> bool:
        return len(self.variables(ctx)) > 0

    def generate(self, ctx: Context) -> Expr:
        name, value = random.choice(self.variables(ctx))
        return Expr(name, value, unmodifiable=name in ctx.unmodifiable_vars and not is_sealed_type(value))


class IntConst(ExprGen):
    def generate(self, ctx: Context) -> Expr:
        i = random.randint(0, 1000)
        return Expr(str(i), i)


class IntOp(ExprGen):
    def generate(self, ctx: Context) -> Expr:
        expr1 = self.gen.int_expr.generate(ctx)
        expr2 = self.gen.int_expr.generate(ctx)
        v1 = cast(int, expr1.value)
        v2 = cast(int, expr2.value)
        options = [
            ('+', (v1 + v2) & INT_MASK),
            ('-', (v1 - v2) & INT_MASK),
            ('*', (v1 * v2) & INT_MASK),
        ]
        if v2 > 0:
            options.append(('/', (v1 // v2) & INT_MASK))
        op, result = random.choice(options)
        return Expr(f'({expr1.expr} {op} {expr2.expr})', result, expr1.output + expr2.output)


class IntUnaryOp(ExprGen):
    def generate(self, ctx: Context) -> Expr:
        expr = self.gen.int_expr.generate(ctx)
        return Expr(f'-{expr.expr}', (-cast(int, expr.value)) & INT_MASK, expr.output)


class StringConst(ExprGen):
    STRING_CHARS = string.ascii_letters + string.digits + "._-:/*+%$"
    CANDIDATES = [
        "<script>",
        "/bin/sh",
        "/bin/bash",
        "/etc/passwd",
        "ncat",
        "wget",
        "curl",
        "%n%n%n",
        "%p%p%p%p%p",
        "<img src=x onerror=alert(2) />",
        "&lt;script&gt;alert(&#39;1&#39;);&lt;/script&gt;",
        "1;DROP TABLE users",
        "' OR 1=1 -- 1",
        "`touch /tmp/blns.fail`",
        "DROP TABLE",
        "Kernel.exec('ls -al /')",
        "$HOME",
        "$ENV{'HOME'}",
        "%d",
        "file:///",
        "{% print 'x' * 64 * 1024**3 %}",
        "{{ ''.__class__.__mro__[2].__subclasses__()[40]('/etc/passwd').read() }}",
    ]

    @classmethod
    def raw(cls) -> str:
        if random.randint(0, 100) <= 5:
            return random.choice(cls.CANDIDATES)
        return ''.join(random.choice(cls.STRING_CHARS) for _ in range(random.randint(0, 12)))

    def generate(self, ctx: Context) -> Expr:
        s = self.raw()
        return Expr(json.dumps(s), s)


class StringAdd(ExprGen):
    def generate(self, ctx: Context) -> Expr:
        expr1 = self.gen.str_expr.generate(ctx)
        expr2 = self.gen.str_expr.generate(ctx) if random.randint(0, 2) else self.gen.int_expr.generate(ctx)
        return Expr(f'({expr1.expr} + {expr2.expr})', str(expr1.value) + str(expr2.value), expr1.output + expr2.output)


class BoolConst(ExprGen):
    def generate(self, ctx: Context) -> Expr:
        c = random.choice((True, False))
        return Expr(json.dumps(c), c)


class BoolUnary(ExprGen):
    def generate(self, ctx: Context) -> Expr:
        expr = self.gen.bool_expr.generate(ctx)
        return Expr(f'!{expr.expr}', not expr.value, expr.output)


class BoolDefined(ExprGen):
    def generate(self, ctx: Context) -> Expr:
        options = [(_, True) for _ in ctx.vars]
        options += [(str(random.randint(0, 1000)), True), (f'({random.randint(0, 1000)} + true)', False)]
        e, r = random.choice(options)
        return Expr(f'defined {e}', r)


class BoolBinary(ExprGen):
    def generate(self, ctx: Context) -> Expr:
        op = random.randint(0, 3)
        expr1 = self.gen.bool_expr.generate(ctx)
        expr2 = self.gen.bool_expr.generate(ctx) if random.randint(0, 100) <= 80 or op >= 2 else self.gen.int_expr.generate(ctx)
        return [
            Expr(f'({expr1.expr} && {expr2.expr})', bool(expr1.value and expr2.value), expr1.output + expr2.output),
            Expr(f'({expr1.expr} || {expr2.expr})', bool(expr1.value or expr2.value), expr1.output + expr2.output),
            Expr(f'({expr1.expr} == {expr2.expr})', bool(expr1.value) == bool(expr2.value), expr1.output + expr2.output),
            Expr(f'({expr1.expr} != {expr2.expr})', bool(expr1.value) != bool(expr2.value), expr1.output + expr2.output),
        ][op]


class BoolComparison(ExprGen):
    def generate(self, ctx: Context) -> Expr:
        expr1 = self.gen.int_expr.generate(ctx)
        expr2 = self.gen.int_expr.generate(ctx)
        v1 = cast(int, expr1.value)
        v2 = cast(int, expr2.value)
        return random.choice([
            Expr(f'({expr1.expr} >= {expr2.expr})', v1 >= v2, expr1.output + expr2.output),
            Expr(f'({expr1.expr} <= {expr2.expr})', v1 <= v2, expr1.output + expr2.output),
            Expr(f'({expr1.expr} > {expr2.expr})', v1 > v2, expr1.output + expr2.output),
            Expr(f'({expr1.expr} < {expr2.expr})', v1 < v2, expr1.output + expr2.output),
        ])


class ArrayConstant(ExprGen):
    def generate(self, ctx: Context) -> Expr:
        a: list[Value] = []
        if random.randint(0, 100) <= 50:
            a.append(random.randint(0, 1000))
        if random.randint(0, 100) <= 50:
            a.append(StringConst.raw())
        return Expr(json.dumps(a), a)


class ObjectConstant(ExprGen):
    def generate(self, ctx: Context) -> Expr:
        a: dict[str, Value] = {}
        if random.randint(0, 100) <= 50:
            a[self.gen.field()] = random.randint(0, 1000)
        if random.randint(0, 100) <= 50:
            a[self.gen.field()] = StringConst.raw()
        return Expr(json.dumps(a), a)


class PickArray(TypedGen):
    def candidates(self, ctx: Context) -> list[tuple[str, int, Value, bool]]:
        result = []
        for var, v in ctx.vars.items():
            if isinstance(v, list):
                for i, v2 in enumerate(v):
                    if self.match(v2):
                        alias_unmodifiable = var in ctx.unmodifiable_vars and not is_sealed_type(v2)
                        if self.gen.can_alias_unmodifiable or not alias_unmodifiable:
                            result.append((var, i, v2, alias_unmodifiable))
        return result

    def applicable(self, ctx: Context) -> bool:
        return len(self.candidates(ctx)) > 0

    def generate(self, ctx: Context) -> Expr:
        candidates = self.candidates(ctx)
        var, i, v, alias_unmodifiable = random.choice(candidates)
        return Expr(f'{var}[{i}]', v, unmodifiable=alias_unmodifiable)


class PickObject(TypedGen):
    def candidates(self, ctx: Context) -> list[tuple[str, str, Value, bool]]:
        result = []
        for var, v in ctx.vars.items():
            if isinstance(v, dict):
                for k, v2 in v.items():
                    if self.match(v2):
                        alias_unmodifiable = var in ctx.unmodifiable_vars and not is_sealed_type(v2)
                        if self.gen.can_alias_unmodifiable or not alias_unmodifiable:
                            result.append((var, k, v2, alias_unmodifiable))
        return result

    def applicable(self, ctx: Context) -> bool:
        return len(self.candidates(ctx)) > 0

    def generate(self, ctx: Context) -> Expr:
        candidates = self.candidates(ctx)
        var, k, v, alias_unmodifiable = random.choice(candidates)
        return Expr(f'{var}[{json.dumps(k)}]', v, unmodifiable=alias_unmodifiable)


class Call(TypedGen):
    def applicable(self, ctx: Context) -> bool:
        return any(self.match(f.value) for f in ctx.funcs.values())

    def generate(self, ctx: Context) -> Expr:
        with self.gen.depth():
            candidates = [f for f in ctx.funcs.values() if self.match(f.value)]
            f: Function = random.choice(candidates)
            if f.value is undefined:
                raise ValueError('no undefined functions supported in calls')
            output: list[Value] = []
            for p in f.params:
                output += list(p.output)
            return Expr(f'{f.name}({", ".join(a.expr for a in f.params)})',
                        AliasSensitiveClone().clone(f.value), tuple(output + f.output))


class StmtGen(ABC):
    def __init__(self, gen: 'CodeGenerator') -> None:
        self.gen = gen

    def applicable(self, ctx: Context) -> bool:
        return True

    @abstractmethod
    def generate(self, ctx: Context) -> Stmt:
        pass


class StmtGenGroup(StmtGen):
    def __init__(self, gens: list[StmtGen]) -> None:
        super().__init__(gens[0].gen)
        self.gens = gens

    def generate(self, ctx: Context) -> Stmt:
        if self.gen.current_depth > self.gen.MAX_EXPR_DEPTH:
            return self.gens[0].generate(ctx)
        with self.gen.depth():
            gens = [_ for _ in self.gens if _.applicable(ctx)]
            return random.choice(gens).generate(ctx)


class VarDefine(StmtGen):
    def generate(self, ctx: Context) -> Stmt:
        name = self.gen.var_names.get()
        expr = self.gen.any_expr.generate(ctx)
        ctx = ctx.update_var(name, expr.value, expr.unmodifiable)
        return Stmt([f'{name} = {expr.expr};'], ctx, list(expr.output))


class VarAssign(StmtGen):
    def applicable(self, ctx: Context) -> bool:
        return len(ctx.vars) > 0

    def generate(self, ctx: Context) -> Stmt:
        name = random.choice(list(ctx.vars.keys()))
        expr = self.gen.any_expr_no_recursion.generate(ctx)
        ctx = ctx.update_var(name, expr.value, expr.unmodifiable)
        return Stmt([f'{name} = {expr.expr};'], ctx, list(expr.output))


class ArrayAppend(StmtGen):
    def applicable(self, ctx: Context) -> bool:
        return any(n not in ctx.unmodifiable_vars and isinstance(v, list) for n, v in ctx.vars.items())

    def generate(self, ctx: Context) -> Stmt:
        name, value = random.choice(
            [(n, v) for n, v in ctx.vars.items() if n not in ctx.unmodifiable_vars and isinstance(v, list)])
        expr = self.gen.any_expr_no_recursion.generate(ctx)
        value.append(expr.value)
        ctx = ctx.update_var(name, value, name in ctx.unmodifiable_vars or expr.unmodifiable)
        return Stmt([f'{name}[+] = {expr.expr};'], ctx, list(expr.output))


class ArrayAssign(StmtGen):
    def applicable(self, ctx: Context) -> bool:
        return any(n not in ctx.unmodifiable_vars and isinstance(v, list) and len(v) > 0 for n, v in ctx.vars.items())

    def generate(self, ctx: Context) -> Stmt:
        candidates = [(n, v) for n, v in ctx.vars.items() if
                      n not in ctx.unmodifiable_vars and isinstance(v, list) and len(v) > 0]
        name, value = random.choice(candidates)
        expr = self.gen.any_expr_no_recursion.generate(ctx)
        i = random.randint(0, len(value) - 1)
        value[i] = expr.value
        ctx = ctx.update_var(name, value, name in ctx.unmodifiable_vars or expr.unmodifiable)
        return Stmt([f'{name}[{i}] = {expr.expr};'], ctx, list(expr.output))


class ObjectAssign(StmtGen):
    def applicable(self, ctx: Context) -> bool:
        return any(n not in ctx.unmodifiable_vars and isinstance(v, dict) for n, v in ctx.vars.items())

    def generate(self, ctx: Context) -> Stmt:
        name, value = random.choice(
            [(n, v) for n, v in ctx.vars.items() if n not in ctx.unmodifiable_vars and isinstance(v, dict)])
        expr = self.gen.any_expr_no_recursion.generate(ctx)
        if random.randint(0, 100) < 30 or len(value) == 0:
            key = self.gen.field()
        else:
            key = random.choice(list(value.keys()))
        value[key] = expr.value
        ctx = ctx.update_var(name, value, name in ctx.unmodifiable_vars or expr.unmodifiable)
        return Stmt([f'{name}[{json.dumps(key)}] = {expr.expr};'], ctx, list(expr.output))


class PrintVar(StmtGen):
    def applicable(self, ctx: Context) -> bool:
        return len(ctx.vars) > 0

    def generate(self, ctx: Context) -> Stmt:
        name, value = random.choice(list(ctx.vars.items()))
        return Stmt([f'print({name});'], ctx, [clone(value)])


class If(StmtGen):
    def generate(self, ctx: Context) -> Stmt:
        with self.gen.depth():
            gen = (self.gen.stmt_basic if self.gen.current_depth >= self.gen.MAX_EXPR_DEPTH else self.gen.stmt_full)
            expr = self.gen.bool_expr.generate(ctx)
            code = ['if ' + expr.expr + ' {']
            output: list[Value] = list(expr.output)
            if expr.value:
                stmt1 = gen.generate(ctx)
                ctx = stmt1.ctx
                output += stmt1.output
            else:
                stmt1 = gen.generate(ctx.fork())
            code += ['    ' + _ for _ in stmt1.code]

            if random.randint(0, 100) <= 50:
                code.append('} else {')
                if not expr.value:
                    stmt2 = gen.generate(ctx)
                    ctx = stmt2.ctx
                    output += stmt2.output
                else:
                    stmt2 = gen.generate(ctx.fork())
                code += ['    ' + _ for _ in stmt2.code]
            code.append('}')
        return Stmt(code, ctx, list(output))


class While(StmtGen):
    def generate(self, ctx: Context) -> Stmt:
        with self.gen.depth():
            gen = (self.gen.stmt_basic if self.gen.current_depth >= self.gen.MAX_EXPR_DEPTH else self.gen.stmt_full)
            expr = self.gen.bool_expr.generate(ctx)
            var = self.gen.var_names.get()
            code = [f'{var} = {expr.expr};', f'while {var} {{']
            ctx.update_var(var, expr.value)
            output: list[Value] = list(expr.output)
            if expr.value:
                stmt = gen.generate(ctx)
                ctx = stmt.ctx.update_var(var, False)
                output += stmt.output
            else:
                stmt = gen.generate(ctx.fork())
            code += ['    ' + _ for _ in stmt.code]
            if expr.value:
                code.append(f'{var} = false;')
            code.append('}')
        return Stmt(code, ctx, list(output))


class TestExpressions(TypedGen):
    CONSTANTS = [
        Expr('(1+2*3+4-2)', 9),
        Expr('(1 && 2)', True),
        Expr('(1 && 0)', False),
        Expr('([!false, 5+-3, "a"+"b", "c"+7, 2*(1+1)])', [True, 2, "ab", "c7", 4]),
        Expr('([len {"a":0}, len [1,2], len "abc"])', [1, 2, 3]),
        Expr('([ [5,11,3][1], {"a":1,"b":2}["a"] ])', [11, 1]),
        Expr('([1==1,1!=1,1!=2, 1<2, 1>2, 1<=2, 1<=1, 1>=2])', [True, False, True, True, False, True, True, False]),
        Expr('(defined 1)', True),
        Expr('(defined {}["a"])', False),
        Expr('(-6 + 7)', 1),
        Expr('["a", {}, {"a":"b"}, null, 2, true, false]', ["a", {}, {"a": "b"}, None, 2, True, False]),
    ]

    def applicable(self, ctx: Context) -> bool:
        return any(self.match(_.value) for _ in self.CONSTANTS)

    def generate(self, ctx: Context) -> Expr:
        return random.choice([_ for _ in self.CONSTANTS if self.match(_.value)]).clone()


class TestStatements(StmtGen):
    CONSTANTS = [
        lambda ctx: Stmt(['a=[3,3,3];', 'a[0]=1;', 'a[1]=2;', 'a[2]=3;'], ctx.update_var('a', [1, 2, 3])),
        lambda ctx: Stmt(['a={"a":0};', 'a["a"]=1;', 'a["b"]=2;'], ctx.update_var('a', {"b": 2, "a": 1})),
        lambda ctx: Stmt(['a=[1];', 'a[+]=2;', 'a[+]=3;'], ctx.update_var('a', [1, 2, 3])),
        lambda ctx: Stmt(['a=[[], [], []];', 'a[0][+]=1;', 'a[1]=a[0];'], ctx.update_var('a', [[1], [1], []])),
        lambda ctx: Stmt(['i = 5; s = 0;', 'while i > 0 { s = s + i;  i = i - 1; }'],
                         ctx.update_var('s', 15).update_var('i', 0)),
    ]

    def generate(self, ctx: Context) -> Stmt:
        return random.choice(self.CONSTANTS)(ctx)


class CodeGenerator:
    MAX_EXPR_DEPTH = 5

    def __init__(self) -> None:
        self.current_depth = 0
        self.can_alias_unmodifiable = True

        self.func_names = IdentifierGenerator()
        self.var_names = IdentifierGenerator()
        self.str_expr = ExprGenGroup([StringConst(self), VarUse(self, str), StringAdd(self),
                                      PickArray(self, str), PickObject(self, str),
                                      Call(self, str), TestExpressions(self, str)])
        self.int_expr = ExprGenGroup([IntConst(self), VarUse(self, int), IntOp(self), IntUnaryOp(self),
                                      PickArray(self, int), PickObject(self, int),
                                      Call(self, int), TestExpressions(self, int)])
        self.bool_expr = ExprGenGroup([BoolConst(self), BoolUnary(self), BoolDefined(self),
                                       BoolBinary(self), BoolComparison(self), VarUse(self, bool),
                                       PickArray(self, bool), PickObject(self, bool),
                                       Call(self, bool), TestExpressions(self, bool)])
        self.any_expr_no_recursion = ExprGenGroup([
            self.str_expr, self.int_expr, self.bool_expr,
            ArrayConstant(self), ObjectConstant(self),
            Call(self, Any), TestExpressions(self, Any),

            VarUse(self, str | int | bool | None),
        ])
        self.any_expr = ExprGenGroup(self.any_expr_no_recursion.gens[:-1] + [VarUse(self, Any)])

        # statements without recursion/output
        self.stmt_basic = StmtGenGroup([VarDefine(self), VarAssign(self),
                                        ArrayAppend(self), ArrayAssign(self), ObjectAssign(self),
                                        TestStatements(self)])
        # + calls/control structures
        self.stmt_full = StmtGenGroup(self.stmt_basic.gens + [If(self), While(self)])
        # + output
        self.stmt_with_output = StmtGenGroup(self.stmt_full.gens + [PrintVar(self)])

    def field(self) -> str:
        s = random.choice(string.ascii_letters + '_')
        return s + ''.join(random.choice(string.ascii_letters + '_') for _ in range(random.randint(6, 11)))

    def collection(self, flag: str, private: bool = False) -> Collection:
        name = ''.join(random.choice(string.ascii_lowercase) for _ in range(random.randint(6, 12)))
        if private:
            name = 'private' + name
        items: list[dict[Expr, Expr]] = [{} for _ in range(random.randint(1, 5))]

        ctx = Context()
        # "key"
        key_gen = make_unique(lambda: self.str_expr.generate(ctx), lambda expr: expr.value)
        ident_key = key_gen()
        ident_key_gen = make_unique(lambda: self.str_expr.generate(ctx), lambda expr: expr.value)
        for item in items:
            item[ident_key] = ident_key_gen()
        # "data"
        flag_key = key_gen()
        for i, item in enumerate(items):
            item[flag_key] = self.str_expr.generate(ctx) if i > 0 else Expr(json.dumps(flag), flag)
        # more things?
        if random.randint(1, 100) <= 65:
            k = key_gen()
            for item in items:
                item[k] = self.int_expr.generate(ctx)
        if random.randint(1, 100) <= 65:
            k = key_gen()
            for item in items:
                item[k] = self.json_expr(ctx)
        flag_item = items[0]
        random.shuffle(items)
        return Collection(name, items=items, ident_key=ident_key, flag_key=flag_key, flag_item=flag_item)

    def query_filter_func(self, collection: Collection, ident: Expr) -> Function:
        name = self.func_names.get()
        var = self.var_names.get()
        code = f'func {name}({var}) {{\n'
        code += '    return ' + self.equality_test(f'{var}[{collection.ident_key.expr}]', ident) + ';\n'
        code += '}'
        return Function(name, code, [], True, [])

    def query_selector_func(self, collection: Collection) -> Function:
        name = self.func_names.get()
        var = self.var_names.get()
        code = f'func {name}({var}) {{\n'
        code += f'    return {var}[{collection.flag_key.expr}];\n'
        code += '}'
        return Function(name, code, [], collection.flag_item[collection.flag_key].value, [])

    def flag_query(self, collection: Collection) -> Function:
        name = self.func_names.get()
        code = f'query {name} on {collection.name}'
        data: list[Value] = [expr_value(_) for _ in collection.items]
        if random.randint(1, 100) <= 70:
            filter_function = self.query_filter_func(collection, collection.flag_item[collection.ident_key])
            code = filter_function.code + '\n\n' + code
            code += f' filter {filter_function.name}'
            data = [expr_value(collection.flag_item)]
        if random.randint(1, 100) <= 70:
            selector_function = self.query_selector_func(collection)
            code = selector_function.code + '\n\n' + code
            code += f' map {selector_function.name}'
            data = [_[collection.flag_key.value] for _ in data]
        if len(data) == 1 and random.randint(1, 100) <= 70:
            l = random.randint(1, 10)
            code += f' limit {l}'
            data = data[:l]
        code += ';'
        return Function(name, code, params=[], value=undefined, output=data)

    @contextmanager
    def depth(self) -> Generator[None, Any, None]:
        self.current_depth += 1
        yield
        self.current_depth -= 1

    @contextmanager
    def no_alias_unmodifiable(self) -> Generator[None, Any, None]:
        old = self.can_alias_unmodifiable
        self.can_alias_unmodifiable = False
        yield
        self.can_alias_unmodifiable = old

    def json_expr(self, ctx: Context) -> Expr:
        c = random.choice(['true', 'false', 'null',
                           '[]', f'[{random.randint(0, 1000)}]',
                           '{}', f'{{"{self.field()}": {random.randint(0, 1000)}}}'])
        return Expr(c, json.loads(c))

    def equality_test(self, expr1: str, expr2: Expr) -> str:
        if random.randint(1, 100) <= 50:
            return f'{expr1} == {expr2.expr}'
        else:
            return f'!({expr1} != {expr2.expr})'

    def function_any(self, ctx: Context, max_params: int = 5, with_print: bool = True) -> Function:
        self.var_names = IdentifierGenerator()
        name = self.func_names.get()
        output = []
        ctx = Context({}, ctx.funcs)
        param_values = [self.any_expr.generate(ctx).sealed() for _ in range(random.randint(0, max_params))]
        param_names = [self.var_names.get() for _ in range(len(param_values))]
        for n, v in zip(param_names, param_values):
            ctx.vars[n] = v.value
            if v.unmodifiable:
                ctx.unmodifiable_vars.add(n)
        code = f'func {name}({",".join(param_names)}) {{\n'

        for _ in range(10):
            stmt = (self.stmt_with_output if with_print else self.stmt_full).generate(ctx)
            code += ''.join(f'    {s}\n' for s in stmt.code)
            ctx = stmt.ctx
            output += stmt.output

        with self.no_alias_unmodifiable():
            result = self.any_expr.generate(ctx)
        output += result.output
        code += '    return ' + result.expr + ';\n'
        code += '}\n'
        return Function(name, code, param_values, result.value, output)

    def function_many(self, max_params: int = 5, max_additional_funcs: int = 9, with_print: bool = True) -> Function:
        ctx = Context()
        code = []
        for _ in range(random.randint(0, max_additional_funcs)):
            f = self.function_any(ctx, max_params=5, with_print=with_print)
            ctx.funcs[f.name] = f
            code.append(f.code)
        f = self.function_any(ctx, max_params=max_params, with_print=with_print)
        code.append(f.code)
        return Function(f.name, '\n\n'.join(code), f.params, f.value, f.output)

    @classmethod
    def uglify(cls, code: str) -> str:
        code = re.sub(r'".*?"', lambda m: m.group(0).replace(' ', '▅'), code)
        if random.randint(0, 100) <= 50:
            code = re.sub(r'\s+', ' ', code)
            code = re.sub(r' ([+*/=<>-]|&&|\|\||==|<=|>=) ', '\\1', code)
            code = re.sub('([;{}():,]) ', '\\1', code)
            code = re.sub(r' ([{(\[])', '\\1', code)
        else:
            rnd_whitespace = lambda m: ''.join(random.choice('   \r\n\t') for _ in range(random.randint(1, 4)))
            code = re.sub(r'\s+', rnd_whitespace, code)
        code = code.replace('▅', ' ')
        return code


def main() -> None:
    gen = CodeGenerator()
    func = gen.function_many(max_params=1)
    print(func.code)
    # print(CodeGenerator.uglify(func.code))
    print(f'// CALL {func.name} {" ".join(json.dumps(_.value) for _ in func.params)}')
    print(f'// => {json.dumps(func.value) if func.value is not undefined else "undefined"}')


if __name__ == '__main__':
    main()
