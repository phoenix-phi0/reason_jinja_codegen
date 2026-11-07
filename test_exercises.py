"""Fourteen programming tasks: execute generated artifacts against independent expectations."""
import asyncio
from collections import OrderedDict
from decimal import Decimal
import json
from pathlib import Path
import random
import runpy
import tempfile
import unittest

from generate import ROOT, generate


class ExerciseTests(unittest.TestCase):
    counts = {}

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        output = Path(cls.temp.name)
        spec = json.loads((ROOT/'examples/exercises.json').read_text())
        cls.paths = generate(spec, output, ROOT/'packs/exercises')
        cls.modules = {Path(p).stem: runpy.run_path(str(output/p)) for p in cls.paths}

    def setUp(self):
        self.counts[self._testMethodName] = 0
        self.rng = random.Random(42)

    def eq(self, actual, expected):
        self.counts[self._testMethodName] += 1
        self.assertEqual(actual, expected)

    def raises(self, exception, fn, *args):
        self.counts[self._testMethodName] += 1
        with self.assertRaises(exception):
            fn(*args)

    def fn(self, name):
        return self.modules[name]['solve']

    def test_binary_search(self):
        fn=self.fn('binary_search')
        self.eq(fn([],1),-1)
        for _ in range(100):
            values=sorted(self.rng.randrange(-20,21) for _ in range(self.rng.randrange(30)))
            target=self.rng.randrange(-25,26)
            self.eq(fn(values,target),values.index(target) if target in values else -1)

    def test_merge_intervals(self):
        fn=self.fn('merge_intervals')
        self.eq(fn([]),[])
        self.eq(fn([[1,3],[2,6],[8,10],[10,12]]),[[1,6],[8,12]])
        self.eq(fn([[1,10],[2,3],[1,10]]),[[1,10]])
        self.raises(ValueError,fn,[[3,1]])
        for _ in range(50):
            values=[sorted([self.rng.randrange(10),self.rng.randrange(10)]) for _ in range(10)]
            result=fn(values)
            self.eq({x for a,b in result for x in range(a,b+1)},
                    {x for a,b in values for x in range(a,b+1)})
            self.eq(all(result[i][1] < result[i+1][0] for i in range(len(result)-1)),True)

    def test_topological_sort(self):
        fn=self.fn('topological_sort')
        self.eq(fn({}),[])
        self.raises(ValueError,fn,{'a':['b'],'b':['a']})
        self.raises(ValueError,fn,{'a':['a']})
        for _ in range(50):
            graph={i:[j for j in range(i+1,12) if self.rng.random()<.2] for i in range(12)}
            result=fn(graph)
            positions={v:i for i,v in enumerate(result)}
            self.eq(set(result),set(graph))
            self.eq(all(positions[a]<positions[b] for a,bs in graph.items() for b in bs),True)
        self.eq(fn({'a':['b']}),['a','b'])

    def test_shortest_path(self):
        fn=self.fn('shortest_path')
        self.eq(fn({'a':['b','c'],'b':['d'],'c':['e'],'e':['d']},'a','d'),['a','b','d'])
        self.eq(fn({'a':['a']},'a','z'),None)
        self.eq(fn({},'a','a'),['a'])
        self.eq(fn({0:[1],1:[0,2],2:[]},0,2),[0,1,2])
        self.eq(fn({'a':['b'],'b':['a']},'a','c'),None)

    def test_csv_totals(self):
        fn=self.fn('csv_totals')
        self.eq(fn('category,amount\nfood,0.1\nfood,0.2\nbook,5\n'),{'food':Decimal('.3'),'book':Decimal(5)})
        self.eq(fn('category,amount\n'),{})
        self.eq(fn('category,amount\n"a,b",2\n"a,b",-1\n'),{'a,b':Decimal(1)})
        self.raises(KeyError,fn,'category\na\n')
        self.raises(Exception,fn,'category,amount\na,invalid\n')

    def test_moving_average(self):
        fn=self.fn('moving_average')
        self.eq(fn([],3),[])
        self.eq(fn([1,2],3),[])
        for bad in [0,-1,True,1.5]:self.raises(ValueError,fn,[1],bad)
        for _ in range(50):
            values=[self.rng.randrange(-10,11) for _ in range(20)]
            window=self.rng.randrange(1,10)
            self.eq(fn(iter(values),window),[sum(values[i:i+window])/window for i in range(len(values)-window+1)])

    def test_flatten(self):
        fn=self.fn('flatten')
        self.eq(fn([]),[])
        self.eq(fn([1,[2,(3,[])],'abc',None]),[1,2,3,'abc',None])
        nested=7
        for _ in range(1500):nested=[nested]
        self.eq(fn(nested),[7])

    def test_chunks(self):
        fn=self.fn('chunks')
        self.eq(list(fn([],2)),[])
        self.eq(list(fn(iter(range(5)),2)),[[0,1],[2,3],[4]])
        for bad in [0,-1,True,1.5]:self.raises(ValueError,lambda:list(fn([1],bad)))
        for size in range(1,20):
            chunks=list(fn(range(31),size))
            self.eq([v for chunk in chunks for v in chunk],list(range(31)))
            self.eq(all(len(c)==size for c in chunks[:-1]),True)

    def test_retry(self):
        fn=self.fn('retry')
        calls=[]
        def operation():
            calls.append(1)
            if len(calls)<3:raise RuntimeError('retry')
            return 42
        self.eq(fn(operation,3),42)
        self.eq(len(calls),3)
        calls.clear()
        self.raises(RuntimeError,fn,operation,2)
        self.eq(len(calls),2)
        self.raises(ValueError,fn,operation,0)
        self.eq(fn(lambda:None,1),None)

    def test_lru_cache(self):
        Cache=self.modules['lru_cache']['Cache']
        self.raises(ValueError,Cache,0)
        cache=Cache(3)
        reference=OrderedDict()
        for _ in range(200):
            key=self.rng.randrange(6)
            if self.rng.random()<.6:
                value=self.rng.randrange(100)
                cache.put(key,value)
                reference[key]=value
                reference.move_to_end(key)
                if len(reference)>3:reference.popitem(last=False)
            elif key in reference:
                self.eq(cache.get(key),reference[key])
                reference.move_to_end(key)
            else:self.raises(KeyError,cache.get,key)
            self.eq(list(cache.items.items()),list(reference.items()))

    def test_bank_account(self):
        Account=self.modules['bank_account']['Account']
        account=Account()
        account.deposit('0.1');account.deposit('0.2')
        self.eq(account.balance,Decimal('.3'))
        account.withdraw('.3')
        self.eq(account.balance,Decimal(0))
        self.raises(ValueError,account.withdraw,1)
        for bad in [0,-1,'NaN','Infinity']:
            self.raises(ValueError,account.deposit,bad)
            self.raises(ValueError,account.withdraw,bad)
        self.eq(account.balance,Decimal(0))

    def test_async_map(self):
        fn=self.fn('async_map')
        async def scenario():
            active=peak=0
            async def operation(value):
                nonlocal active,peak
                active+=1;peak=max(peak,active)
                await asyncio.sleep(0)
                active-=1
                return value*2
            result=await fn(operation,range(20),3)
            self.eq(result,list(range(0,40,2)))
            self.eq(peak,3)
            self.eq(await fn(operation,[],3),[])
            try:await fn(operation,[1],0)
            except ValueError:self.eq(True,True)
            else:self.fail('invalid concurrency accepted')
            async def bad(value):raise RuntimeError('failed')
            try:await fn(bad,[1],1)
            except RuntimeError:self.eq(True,True)
            else:self.fail('exception swallowed')
        asyncio.run(scenario())

    def test_config_validation(self):
        fn=self.fn('config_validation')
        self.eq(fn('{"host":"localhost","port":8080}'),{'host':'localhost','port':8080})
        for value in [[],{}, {'host':'','port':80},{'host':'x','port':True},
                      {'host':'x','port':0},{'host':'x','port':65536}]:
            self.raises(ValueError,fn,json.dumps(value))
        self.raises(ValueError,fn,'invalid json')

    def test_stable_unique(self):
        fn=self.fn('stable_unique')
        self.eq(fn([]),[])
        self.eq(fn(['b','a','b','c','a']),['b','a','c'])
        for _ in range(100):
            values=[self.rng.randrange(20) for _ in range(30)]
            self.eq(fn(iter(values)),list(dict.fromkeys(values)))


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ExerciseTests))
    report={'tasks':result.testsRun,'failed':len(result.failures),'errors':len(result.errors),
            'checks':sum(ExerciseTests.counts.values()),'per_task_checks':ExerciseTests.counts,
            'failures':[{'test':str(t),'traceback':e} for t,e in result.failures+result.errors],
            'scope':'Algorithms are predefined Jinja templates selected by Datalog rules; no function bodies are supplied by the task input. This does not test synthesis of unseen algorithms.'}
    (ROOT/'exercise_results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    raise SystemExit(not result.wasSuccessful())
