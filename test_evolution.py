import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import evolution as e
CANDIDATE={'intent':'bubble_sort','vocabulary':{'intent':['bubble_sort'],'order':['ascending'],'input':['int_list']},'rule':e.RULE,'source':'''def solve(nums):
    a = list(nums)
    for i in range(len(a)):
        for j in range(len(a)-1-i):
            if a[j] > a[j+1]:
                a[j], a[j+1] = a[j+1], a[j]
    return a
''','summary':'integer ascending bubble sort'}
BASE={'facts':[['arg','nums','int_list']],'signature':'solve(nums)','inferred':{},'uncovered':'not supported','extension_semantics':{'intent':'bubble_sort','input_type':'int_list','order':'ascending','max_length':100,'extra_requirements':[]}}
PAYLOAD={'history':[],'signature':'solve(nums)','message':'整数数组长度不超过100，使用冒泡排序按升序返回结果。'}

class EvolutionTests(unittest.TestCase):
    def test_real_isolation_and_oracle(self):
        self.assertTrue(e.sandbox({'mode':'probe'})['isolated'])
        r=e.sandbox({'mode':'validate','candidate':CANDIDATE,'param':'numbers'})
        self.assertEqual(r['tests'],80);self.assertIn('solve(numbers)',r['source'])
        for source in ['def solve(nums):\n import os\n return nums', 'def solve(nums):\n return sorted(nums)', 'def solve(nums):\n while True: pass']:
            with self.assertRaises(ValueError):e.sandbox({'mode':'validate','candidate':{**CANDIDATE,'source':source}})

    def test_publish_reuse_no_second_growth(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(e,'STORE',Path(tmp)),patch.object(e.Chat,'ask',side_effect=lambda *a,**kw:{'result':json.loads(json.dumps(BASE))}),patch.object(e,'propose',return_value=CANDIDATE) as model:
            a=e.evolve_legacy(PAYLOAD);self.assertEqual(a['status'],'evolved');self.assertEqual(model.call_count,1)
            b=e.evolve_legacy(PAYLOAD);self.assertEqual(b['evolution_version'],a['evolution_version']);self.assertEqual(model.call_count,1)
            self.assertEqual(len(list((Path(tmp)/'versions').glob('*.json'))),1)

    def test_failure_cancel_pending_do_not_publish(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(e,'STORE',Path(tmp)),patch.object(e.Chat,'ask',return_value={'result':BASE.copy()}):
            with patch.object(e,'propose',return_value={**CANDIDATE,'source':'def solve(nums):\n return []'}):
                r=e.evolve_legacy(PAYLOAD);self.assertNotIn('code_files',r)
            self.assertFalse(list((Path(tmp)/'versions').glob('*.json')))
            with patch.object(e,'propose',side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt):e.evolve_legacy(PAYLOAD)
            self.assertFalse(list((Path(tmp)/'versions').glob('*.json')))
            with patch.object(e,'propose',return_value=CANDIDATE):
                with patch.object(e.Chat,'ask',return_value={'result':{**BASE,'extension_semantics':{'intent':'other'}}}):
                    r=e.evolve_legacy({**PAYLOAD,'message':'实现一个新算法，说明尚不完整'})
                self.assertIn('待验证',r['evolution_note'])
            self.assertFalse(list((Path(tmp)/'versions').glob('*.json')))

    def test_stable_shortcut_and_qualification(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(e,'STORE',Path(tmp)),patch.object(e.Chat,'ask',return_value={'result':{'code_files':[{'source':'trusted stable'}]}}),patch.object(e,'propose') as model:
            self.assertIn('稳定规则',e.evolve_legacy(PAYLOAD)['evolution_note']);model.assert_not_called()
        sem=BASE['extension_semantics']
        self.assertFalse(e.admission({**sem,'extra_requirements':['求和']},'solve(nums)',PAYLOAD['message'])[0])
        self.assertFalse(e.admission({**sem,'max_length':100000},'solve(nums)','长度100000')[0])

class LearnedRoutingTests(unittest.TestCase):
    def test_short_variants_reuse_without_candidate_or_fake_size(self):
        sem={'intent':'bubble_sort','input_type':'unspecified','order':'unspecified','max_length':None,'extra_requirements':[]}
        with tempfile.TemporaryDirectory() as tmp,patch.object(e,'STORE',Path(tmp)):
            (Path(tmp)/'versions').mkdir()
            (Path(tmp)/'versions/v.json').write_text(json.dumps({'id':'v','status':'validated','candidate':CANDIDATE,'validation':{'tests':80,'rule_selected':True,'contract':'bubble_sort'}}))
            before=list((Path(tmp)/'versions').iterdir())
            for text in ['帮我做个冒泡算法','生成冒泡排序代码','写一个冒泡排序函数']:
                with patch.object(e.Chat,'ask',return_value={'result':{**BASE,'extension_semantics':sem}}),patch.object(e,'propose') as grow:
                    r=e.evolve_legacy({**PAYLOAD,'message':text})
                    grow.assert_not_called();self.assertEqual(r['model_calls'],1)
                    self.assertTrue(r['code_files']);self.assertEqual(len(r['assumptions']),2)
                    self.assertFalse(any(f[0]=='size' for f in r['facts']))
                    self.assertEqual(r['fact_sources']['size'],'unspecified')
            self.assertEqual(before,list((Path(tmp)/'versions').iterdir()))
            self.assertFalse(list((Path(tmp)/'candidates').glob('*.json')))

    def test_incompatible_semantics_do_not_default_or_grow(self):
        sem={'intent':'bubble_sort','input_type':'unspecified','order':'unspecified','max_length':None,'extra_requirements':[]}
        cases=[({**sem,'order':'descending'},'降序冒泡'),({**sem,'input_type':'float_list'},'浮点冒泡'),
               ({**sem,'input_type':'objects'},'对象冒泡'),({**sem,'max_length':1000},'长度1000冒泡'),
               ({**sem,'extra_requirements':['输出每一步']},'输出每一步冒泡')]
        for semantics,text in cases:
            with tempfile.TemporaryDirectory() as tmp,patch.object(e,'STORE',Path(tmp)),patch.object(e.Chat,'ask',return_value={'result':{**BASE,'extension_semantics':semantics}}),patch.object(e,'propose') as grow:
                r=e.evolve_legacy({**PAYLOAD,'message':text});grow.assert_not_called();self.assertNotIn('code_files',r)
        self.assertFalse(e.admission(sem,'solve(a, b)','冒泡')[0])
        self.assertTrue(e.admission(sem,'solve(items)','冒泡')[0])

    def test_followup_and_explicit_switch_keep_correct_scope(self):
        sem={'intent':'bubble_sort','input_type':'unspecified','order':'unspecified','max_length':None,'extra_requirements':[]}
        seen=[]
        def factory(catalog,state):
            self.assertTrue(catalog)
            def translate(problem,*a,**kw):
                seen.append(problem['statement'])
                state['extension']={**sem,'order':'descending' if '降序' in problem['statement'] else 'unspecified'}
                return [],'not in stable vocabulary'
            return translate
        with tempfile.TemporaryDirectory() as tmp,patch.object(e,'STORE',Path(tmp)),patch.object(e,'translator',side_effect=factory),patch.object(e,'propose') as grow:
            (Path(tmp)/'versions').mkdir();(Path(tmp)/'versions/v.json').write_text(json.dumps({'id':'v','status':'validated','candidate':CANDIDATE,'validation':{'tests':80,'rule_selected':True,'contract':'bubble_sort'}}))
            first=e.evolve_legacy({**PAYLOAD,'message':'帮我做个冒泡算法'})
            self.assertIn('code_files',first)
            second=e.evolve_legacy({**PAYLOAD,'history':['帮我做个冒泡算法'],'message':'补充：要求降序'})
            self.assertNotIn('code_files',second);self.assertIn('帮我做个冒泡算法',seen[-1])
            third=e.evolve_legacy({**PAYLOAD,'history':['帮我做个冒泡算法','补充：要求降序'],'message':'换题\n生成冒泡排序代码'})
            self.assertIn('code_files',third);self.assertNotIn('降序',seen[-1])
            grow.assert_not_called()

    def test_catalog_is_in_the_same_model_translation(self):
        from evolution_translate import translator
        from types import SimpleNamespace
        state={};response={'facts':[],'uncovered':None,'extension':{'intent':'bubble_sort','input_type':'unspecified','order':'unspecified','max_length':None,'extra_requirements':[]}}
        with patch('evolution_translate.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout=json.dumps(response))) as model:
            fn=translator([{'version':'v','vocabulary':CANDIDATE['vocabulary']}],state)
            fn({'signature':'solve(nums)','statement':'帮我做个冒泡算法'},'haiku',e.general.vocab())
            self.assertEqual(model.call_count,1)
            self.assertIn('Validated catalog:',model.call_args.kwargs['input'])
            self.assertIn('bubble_sort',model.call_args.kwargs['input'])
            self.assertEqual(state['extension']['intent'],'bubble_sort')

if __name__=='__main__':unittest.main()
