"""Reproducible capability checks; runs only locally authored test code."""
import asyncio
import json
from pathlib import Path
import runpy
import tempfile
import time

from datalog import Datalog, parse_rules
from generate import ROOT, generate


def main():
    results = []
    def check(name, category, fn):
        start = time.perf_counter()
        try:
            detail = fn()
            results.append(dict(name=name, category=category, passed=True,
                                seconds=round(time.perf_counter()-start, 4), detail=detail))
        except Exception as exc:
            results.append(dict(name=name, category=category, passed=False,
                                seconds=round(time.perf_counter()-start, 4), detail=f'{type(exc).__name__}: {exc}'))
        print(f'{name}: {results[-1]["passed"]}, {results[-1]["seconds"]}s', flush=True)

    def equal(actual, expected):
        if actual != expected:
            raise AssertionError(f'expected {expected!r}, got {actual!r}')

    cases = [
        ('arithmetic', ['a', 'b'], 'return a + b', (2, 3), 5),
        ('branch', ['x'], 'if x < 0:\n    return -x\nreturn x', (-5,), 5),
        ('loop', ['n'], 'result = 0\nfor i in range(n):\n    result += i\nreturn result', (5,), 10),
        ('comprehension', ['xs'], 'return [x*x for x in xs if x > 0]', ([-1,2,3],), [4,9]),
        ('exception', ['x'], 'try:\n    return 10 // x\nexcept ZeroDivisionError:\n    return 0', (0,), 0),
        ('generator', ['n'], 'for i in range(n):\n    yield i*i', (3,), [0,1,4]),
        ('recursion', ['n'], 'return 1 if n < 2 else n * recursion(n-1)', (5,), 120),
        ('nested_function', ['x'], 'def inner(y):\n    return y+1\nreturn inner(x)', (4,), 5),
        ('match_case', ['x'], 'match x:\n    case 1:\n        return "one"\n    case _:\n        return "other"', (1,), 'one'),
        ('context_manager', [], 'from contextlib import nullcontext\nwith nullcontext(7) as x:\n    return x', (), 7),
        ('keyword_only', ['x', '*', 'scale=2'], 'return x * scale', (3,), 6),
        ('variadic', ['*args', '**kwargs'], 'return sum(args) + sum(kwargs.values())', (1,2,3), 6),
        ('unicode', [], 'return "你好，Python"', (), '你好，Python'),
        ('async_function', ['x'], 'return x * 2', (4,), 8),
    ]
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        spec = {'facts': {'module': [['m', 'module.py']],
                          'function_mode': [['m', 'async_function', 'async']]},
                'data': {'m': {'constants': {'SETTINGS': {'enabled': True, 'missing': None}},
                               'functions': [dict(name=n, parameters=p, body=b) for n,p,b,_,_ in cases]}}}
        out = root / 'features'
        generate(spec, out)
        ns = runpy.run_path(str(out/'module.py'))
        for name, _, _, args, expected in cases:
            def run(name=name, args=args, expected=expected):
                value = ns[name](*args)
                if name == 'generator': value = list(value)
                if name == 'async_function': value = asyncio.run(value)
                equal(value, expected)
            check(name, 'python_body', run)
        check('constant_literals', 'python_structure', lambda: equal(ns['SETTINGS'], {'enabled':True,'missing':None}))

        classes = [
            {'name':'Base','methods':[{'name':'value','body':'return 3'}]},
            {'name':'Child','bases':['Base'],'attributes':{'label':'child'},'methods':[
                {'name':'value','body':'return super().value() + 1'},
                {'name':'twice','decorators':['staticmethod'],'parameters':['x'],'body':'return x*2'},
                {'name':'make','decorators':['classmethod'],'parameters':['cls'],'body':'return cls()'},
                {'name':'answer','decorators':['property'],'body':'return 42'},
                {'name':'fetch','async':True,'body':'return self.value()'}]},
            {'name':'Record','decorators':['dataclass'],'methods':[]},
        ]
        spec['data']['m'] = {'imports':['from dataclasses import dataclass'], 'classes':classes,
                             'functions':[{'name':'cached','parameters':['x'], 'decorators':['staticmethod'], 'body':'return x'}]}
        generate(spec,out)
        ns=runpy.run_path(str(out/'module.py'))
        child=ns['Child']()
        for name,fn in [
            ('inheritance',lambda:equal(child.value(),4)),
            ('static_method',lambda:equal(child.twice(5),10)),
            ('class_method',lambda:equal(type(child.make()),ns['Child'])),
            ('property',lambda:equal(child.answer,42)),
            ('async_method',lambda:equal(asyncio.run(child.fetch()),4)),
            ('class_decorator',lambda:equal(ns['Record'].__dataclass_fields__,{})),
        ]: check(name,'python_structure',fn)

        def infer(text,facts):
            engine=Datalog(parse_rules(text))
            for p,rows in facts.items():
                for row in rows:engine.add(p,*row)
            return engine.run()
        def rule_test(text,facts,predicate,expected):
            equal(infer(text,facts).get(predicate,set()),set(expected))
        rule_cases=[
            ('join','out(X,Z) :- left(X,Y), right(Y,Z).',{'left':[('a','b')],'right':[('b','c')]},'out',[('a','c')]),
            ('multi_hop','mid(X) :- seed(X).\nout(X) :- mid(X).',{'seed':[('a',)]},'out',[('a',)]),
            ('cycle_termination','a(X) :- b(X).\nb(X) :- a(X).',{'a':[('x',)]},'b',[('x',)]),
            ('wildcard','out(X) :- pair(X,_).',{'pair':[('a','1'),('a','2')]},'out',[('a',)]),
            ('repeated_variable','out(X) :- pair(X,X).',{'pair':[('a','a'),('b','c')]},'out',[('a',)]),
            ('transitive_closure','reach(X,Y) :- edge(X,Y).\nreach(X,Z) :- reach(X,Y), edge(Y,Z).',{'edge':[('a','b'),('b','c')]},'reach',[('a','b'),('b','c'),('a','c')]),
        ]
        for name,text,facts,pred,expected in rule_cases:
            check(name,'inference',lambda t=text,f=facts,p=pred,e=expected:rule_test(t,f,p,e))
        # Probes deliberately require unsupported syntax to reveal rejection or silent misinterpretation.
        probes=[
            ('negation','out(X) :- node(X), not blocked(X).',{'node':[('a',),('b',)],'blocked':[('b',)]},'out',[('a',)]),
            ('comparison','out(X) :- node(X), X > 3.',{'node':[('2',),('5',)]},'out',[('5',)]),
            ('quoted_comma','out("a,b") :- seed(x).',{'seed':[('x',)]},'out',[('a,b',)]),
        ]
        for name,text,facts,pred,expected in probes:
            check(name,'boundary_probe',lambda t=text,f=facts,p=pred,e=expected:rule_test(t,f,p,e))

        for count in [10,100,1000]:
            def scale(count=count):
                spec={'facts':{'module':[]},'data':{}}
                for i in range(count):
                    key=f'm{i}'
                    spec['facts']['module'].append([key,f'{key}.py'])
                    spec['data'][key]={'functions':[{'name':f'f{j}', 'parameters':['x'], 'body':f'return x + {j}'} for j in range(10)]}
                out=root/f'scale{count}'
                paths=generate(spec,out)
                equal(len(paths),count)
                for path in paths:
                    ns=runpy.run_path(str(out/path))
                    for j in range(10):equal(ns[f'f{j}'](5),5+j)
                return {'modules':count,'functions':count*10,'lines':sum(len((out/p).read_text().splitlines()) for p in paths),'bytes':sum((out/p).stat().st_size for p in paths),'runtime_calls':count*10}
            check(f'{count}_modules','scale',scale)
        for count in [100, 1000]:
            def inferred_models(count=count):
                spec={'facts':{'entity':[], 'field':[], 'required':[]},'data':{}}
                for i in range(count):
                    key=f'e{i}'
                    spec['facts']['entity'].append([key,f'{key}.py'])
                    spec['data'][key]={'name':f'Entity{i}', 'fields':[f'f{j}' for j in range(10)]}
                    for j in range(10):
                        spec['facts']['field'].append([key,f'f{j}','text'])
                        spec['facts']['required'].append([key,f'f{j}'])
                out=root/f'inferred{count}'
                paths=generate(spec,out)
                for i,path in enumerate(paths):
                    # runpy does not register dataclass modules; no postponed annotations are emitted.
                    ns=runpy.run_path(str(out/path))
                    cls=next(v for k,v in ns.items() if k.startswith('Entity'))
                    cls(*(['ok']*10)).validate()
                    try:cls(*(['']*10)).validate()
                    except ValueError:pass
                    else:raise AssertionError('missing inferred nonempty check')
                report=json.loads((out/'inference.json').read_text())
                return {'models':count,'fields':count*10,
                        'inferred_types':len(report['inferred']['python_type']),
                        'inferred_checks':len(report['inferred']['check']),
                        'lines':sum(len((out/p).read_text().splitlines()) for p in paths)}
            check(f'{count}_inferred_models','rule_driven_scale',inferred_models)

        def closure_scale():
            n=100
            result=infer('reach(X,Y) :- edge(X,Y).\nreach(X,Z) :- reach(X,Y), edge(Y,Z).',
                         {'edge':[(str(i),str(i+1)) for i in range(n-1)]})
            equal(len(result['reach']),n*(n-1)//2)
            return {'nodes':n,'derived_pairs':len(result['reach'])}
        check('100_node_closure','inference_scale',closure_scale)
    report={'results':results,'note':'Bodies supplied as Python source, not synthesized by reasoning. Scale includes generation, write, import and every function call. Boundary probes are intentionally unsupported.'}
    destination=ROOT/'benchmark_results.json'
    destination.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
