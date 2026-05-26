import json
import random
import secrets
import subprocess
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest import TestCase

from .codegen import Expr, CodeGenerator, Context, Function, expr_value, undefined


def find_compiler() -> Path:
    for p in ('cmake-build-debug', 'build', ''):
        candidate = JIT_ROOT / p / 'jit'
        if candidate.exists():
            print(f'Compiler: {candidate}')
            return candidate
    raise Exception('Compiler not found, please build it first!')


JIT_ROOT: Path = Path(__file__).absolute().parent.parent.parent / 'service' / 'jit'
COMPILER: Path = find_compiler()


def read_json_lines(s: str) -> list[Any]:
    return [json.loads(l) for l in s.strip().split('\n') if l]


class Compiler:
    def compile(self, code: str, output: Path) -> None:
        p = subprocess.Popen([str(COMPILER), '/dev/stdin', str(output)], stdin=subprocess.PIPE)
        p.communicate(input=code.encode(), timeout=5)
        p.wait()
        if p.returncode != 0:
            raise Exception(f'Compilation failed with code {p.returncode}')

    def run_prog(self, code: str, function: str = 'jit_entrypoint', param: Any = None,
                 collections: dict[str, str | list] = {}) -> str:
        with TemporaryDirectory(dir='/dev/shm') as tmpdir_str:
            tmpdir = Path(tmpdir_str)
            for n, c in collections.items():
                if isinstance(c, list):
                    c = '\n'.join(json.dumps(_) for _ in c) + '\n'
                (tmpdir / f'{n}.ndjson').write_text(c)

            self.compile(code, tmpdir / 'code.so')
            cmd: list[str] = [str(tmpdir / 'code.so'), function, json.dumps(param)]
            return subprocess.check_output(cmd, cwd=tmpdir).decode().strip()


class CodegenTestCases(TestCase):
    FUNC_ITERATIONS = 100
    EXPR_ITERATIONS = 10
    EXPR_CHUNKS = 2000

    START_SEED = int(secrets.randbits(32))

    def seed_random(self) -> int:
        print(f'SEED {self.START_SEED}')
        random.seed(self.START_SEED)
        self.START_SEED += 1
        return self.START_SEED - 1

    def setUp(self):
        self.compiler = Compiler()
        self.gen = CodeGenerator()

    def _run_prog(self, *args, **kwargs) -> list[Any]:
        lines = self.compiler.run_prog(*args, **kwargs)
        return read_json_lines(lines)

    def _test_expr(self, expr: Expr) -> None:
        output = self._run_prog(f'func jit_entrypoint() {{ return {expr.expr}; }}')
        if output[-1] != expr.value:
            print(expr.expr)
            self.assertEqual(expr.value, output[-1], f'output of {expr.expr} is wrong')
        self.assertEqual(1, len(output))

    def _test_func(self, func: Function, collections: dict[str, str]) -> Any:
        try:
            param = None if len(func.params) == 0 else func.params[0].value
            output = self._run_prog(func.code, func.name, param=param, collections=collections)
            if func.value is not undefined:
                result = output[-1]
                self.assertEqual(expr_value(func.value), result)
                output = output[:-1]
            else:
                result = undefined
            expected_output = expr_value(func.output)
            self.assertEqual(expected_output, output, f'output of {func.name} is wrong')
            return result
        except:
            print(func.as_script())
            for name, coll in collections.items():
                print(f'=== {name} ===\n{coll}\n================')
            raise

    def test_expressions_int(self) -> None:
        for _ in range(self.EXPR_ITERATIONS):
            self.seed_random()
            ctx = Context({})
            code = self.gen.int_expr.generate(ctx)
            self._test_expr(code)

    def test_expressions_str(self) -> None:
        for _ in range(self.EXPR_ITERATIONS):
            self.seed_random()
            ctx = Context({})
            code = self.gen.str_expr.generate(ctx)
            self._test_expr(code)

    def test_expressions_bool(self) -> None:
        for _ in range(self.EXPR_ITERATIONS):
            self.seed_random()
            ctx = Context({})
            code = self.gen.bool_expr.generate(ctx)
            self._test_expr(code)

    def _test_expr_chunks(self, gen) -> None:
        self.seed_random()
        code = 'func jit_entrypoint() {\n'
        exprs = []
        for _ in range(self.EXPR_CHUNKS):
            ctx = Context({})
            expr = gen.generate(ctx)
            exprs.append(expr)
            code += 'print(' + expr.expr + ');\n'
        code += 'return {}[""]; }'
        output = self._run_prog(code)
        if len(output) != len(exprs):
            raise Exception('Wrong number of output lines')
        for e, o in zip(exprs, output):
            self.assertEqual(e.value, o, f'Output of {e.expr}')

    def test_bool_chunked(self) -> None:
        self._test_expr_chunks(self.gen.bool_expr)

    def test_str_chunked(self) -> None:
        self._test_expr_chunks(self.gen.str_expr)

    def test_int_chunked(self) -> None:
        self._test_expr_chunks(self.gen.int_expr)

    def test_functions(self) -> None:
        for _ in range(self.FUNC_ITERATIONS):
            self.gen = CodeGenerator()
            self.seed_random()
            func = self.gen.function_many(max_params=1)
            self._test_func(func, {})

    def test_functions_threaded(self) -> None:
        executor = ThreadPoolExecutor(max_workers=8)
        futures = []
        for _ in range(self.FUNC_ITERATIONS):
            self.gen = CodeGenerator()
            seed = self.seed_random()
            func = self.gen.function_many(max_params=1)
            future = executor.submit(self._test_func, func, {})
            futures.append((future, seed))
        for f, s in futures:
            try:
                f.result()
            except:
                print(f'FAIL with seed {s}')
                raise

    def test_functions_uglified(self) -> None:
        for _ in range(self.FUNC_ITERATIONS):
            self.gen = CodeGenerator()
            self.seed_random()
            func = self.gen.function_many(max_params=1)
            func = Function(func.name, self.gen.uglify(func.code), func.params, func.value, func.output)
            self._test_func(func, {})

    def test_queries(self) -> None:
        for _ in range(self.FUNC_ITERATIONS):
            self.gen = CodeGenerator()
            self.seed_random()
            coll = self.gen.collection('FLAG{abc}')
            qry = self.gen.flag_query(coll)
            flg = self._test_func(qry, {coll.name: coll.to_ndjson()})
            # print(flg)

    def test_queries_threaded(self) -> None:
        executor = ThreadPoolExecutor(max_workers=8)
        futures = []
        for _ in range(self.FUNC_ITERATIONS):
            self.gen = CodeGenerator()
            seed = self.seed_random()
            coll = self.gen.collection('FLAG{abc}')
            qry = self.gen.flag_query(coll)
            future = executor.submit(self._test_func, qry, {coll.name: coll.to_ndjson()})
            futures.append((future, seed))
        for f, s in futures:
            try:
                f.result()
            except:
                print(f'FAIL with seed {s}')
                raise

    def test_func_query_combinations(self) -> None:
        for _ in range(self.FUNC_ITERATIONS):
            self.gen = CodeGenerator()
            coll = self.gen.collection('FLAG{abc}')
            self.seed_random()
            func = self.gen.function_many(max_params=1)
            qry = self.gen.flag_query(coll)
            joined = Function(func.name, f'{func.code}\n{qry.code}', func.params, func.value, func.output)
            self._test_func(joined, {})


    '''
    def test_bughunt(self) -> None:
        code = (Path(__file__).parent / 'codegen_test.qry').read_text()
        func = Function("J4NThsi1YMt7", code, [Expr('', 72057594037927547)], 828, [])
        # EXECUTE oqL9TVxM__0t {"SiKz_tmF": 491}
        # Result: [650, "mk2QXU54l"]
        # output: {"SiKz_tmF": 491, "baXxkopUj_": 1}
        # output: "9"
        # output: "9"
        # output: {"SiKz_tmF": 491, "baXxkopUj_": {}}
        self._test_func(func, {})
    '''


if __name__ == '__main__':
    unittest.main()
