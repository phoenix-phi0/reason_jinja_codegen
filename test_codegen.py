import json
from pathlib import Path
import runpy
import asyncio
import importlib.util
import sys
import tempfile
import unittest

from generate import ROOT, generate


class CodegenTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.spec = json.loads((ROOT / 'examples/entities.json').read_text())

    def test_dataclass_behavior(self):
        output = self.root / 'python'
        self.assertEqual(len(generate(self.spec, output)), 2)
        User = runpy.run_path(str(output / 'models/user.py'))['User']
        User('Alice', 20, True).validate()
        with self.assertRaises(ValueError):
            User('', 20, True).validate()
        with self.assertRaises(TypeError):
            User('Alice', True, True).validate()

    def test_general_python_package(self):
        spec = json.loads((ROOT / 'examples/python.json').read_text())
        output = self.root / 'example'
        self.assertEqual(len(generate(spec, output)), 3)
        loader = importlib.util.spec_from_file_location('generated_example', output / '__init__.py')
        module = importlib.util.module_from_spec(loader)
        sys.modules[loader.name] = module
        try:
            loader.loader.exec_module(module)
            self.assertEqual(module.total([1, 2, 3]), 6)
            self.assertEqual(module.Multiplier(3).apply(4), 12)
            self.assertEqual(asyncio.run(module.double(5)), 10)
        finally:
            for name in list(sys.modules):
                if name == loader.name or name.startswith(loader.name + '.'):
                    del sys.modules[name]

    def pack(self, rule, template='MESSAGE = {{ item.message|pyrepr }}'):
        pack = self.root / 'pack'
        (pack / 'templates').mkdir(parents=True)
        (pack / 'pack.json').write_text('{"rules": ["rules.dl"]}')
        (pack / 'rules.dl').write_text(rule)
        (pack / 'templates/plain.j2').write_text(template)
        return pack

    def test_new_domain_uses_only_rules_and_template(self):
        pack = self.pack('emit(plain.j2,P,K) :- document(K,P).')
        spec = {'facts': {'document': [['hello', 'hello.py']]},
                'data': {'hello': {'message': '你好'}}}
        generate(spec, self.root / 'out', pack)
        self.assertEqual(runpy.run_path(str(self.root / 'out/hello.py'))['MESSAGE'], '你好')

    def test_traversal_and_collision_rejected(self):
        for path in ['../escape.py', '/tmp/escape.py', 'inference.json']:
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.spec['facts']['entity'][0][1] = path
                generate(self.spec, self.root / 'out')
        self.assertFalse((self.root / 'out').exists())

    def test_render_failure_writes_nothing(self):
        self.spec['data']['user']['fields'].append('unknown')
        with self.assertRaises(ValueError):
            generate(self.spec, self.root / 'out')
        self.assertFalse((self.root / 'out').exists())

    def test_rule_error_and_arity(self):
        pack = self.pack('error(K) :- forbidden(K).')
        with self.assertRaisesRegex(ValueError, 'rejected'):
            generate({'facts': {'forbidden': [['x']]}}, self.root / 'out', pack)
        self.spec['facts']['field'].append(['bad'])
        with self.assertRaisesRegex(ValueError, 'arity'):
            generate(self.spec, self.root / 'out')

    def test_only_python_and_compile_before_write(self):
        pack = self.pack('emit(plain.j2,P,K) :- document(K,P).', 'return 1')
        spec = {'facts': {'document': [['x', 'output.txt']]}, 'data': {'x': {}}}
        with self.assertRaisesRegex(ValueError, 'Only Python'):
            generate(spec, self.root / 'out', pack)
        spec['facts']['document'][0][1] = 'output.py'
        with self.assertRaises(SyntaxError):
            generate(spec, self.root / 'out', pack)
        self.assertFalse((self.root / 'out').exists())


if __name__ == '__main__':
    unittest.main()
