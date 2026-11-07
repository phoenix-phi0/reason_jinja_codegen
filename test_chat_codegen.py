import ast
import unittest
from unittest.mock import patch
from chat_codegen import add_code,code_text
import general

class CodeTests(unittest.TestCase):
    def result(self,positive=False):
        facts=[['arg','numbers','int_list'],['iterate','numbers'],['aggregate','sum'],['size','numbers','tiny']]
        if positive:facts.append(['keep','positive'])
        return {'facts':facts,'inferred':{'schema':[['p','seq_fold']]}}

    def test_full_code_signature_and_positive_static_only(self):
        with patch('general.run_tests',side_effect=AssertionError('must never execute')):
            a=add_code(self.result(),'solve(numbers)')
            b=add_code(self.result(True),'solve(numbers)')
        src=a['code_files'][0]['source'];tree=ast.parse(src)
        fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef))
        self.assertEqual(fn.name,'solve');self.assertEqual(fn.args.args[0].arg,'numbers')
        self.assertNotIn('x > 0',src);self.assertIn('x > 0',b['code_files'][0]['source'])
        self.assertIn('```python',code_text(b))

    def test_multiturn_code_and_failed_translation_history(self):
        from chat import Chat
        c=Chat();sid=c.create()
        first=self.result()['facts'];second=self.result(True)['facts']
        with patch('general.extract',side_effect=[(first,None),(second,None),RuntimeError('failure')]):
            a=c.ask(sid,'对 numbers 求和','solve(numbers)')
            b=c.ask(sid,'只求正数之和','solve(numbers)')
            self.assertNotIn('x > 0',a['result']['code_files'][0]['source'])
            self.assertIn('x > 0',b['result']['code_files'][0]['source'])
            history=list(c.session(sid)['history'])
            with self.assertRaises(RuntimeError):c.ask(sid,'失败输入','solve(numbers)')
            self.assertEqual(c.session(sid)['history'],history)

    def test_blocked_uncovered_no_candidate_no_codegen(self):
        samples=[{'facts':[],'inferred':{}},self.result(),self.result()]
        samples[1]['inferred']['error']=[['unmet_precondition','p']]
        samples[2]['uncovered']='not supported'
        with patch('general.generate',side_effect=AssertionError('must not generate')):
            for r in samples:
                add_code(r,'solve(numbers)');self.assertNotIn('code_files',r)

    def test_actual_engine_rejects_missing_premise(self):
        facts=[['arg','coins','int_list'],['arg','target','int'],['items','coins'],['target','target'],['ask','min_count']]
        d=general.engine_for({'signature':'solve(coins, target)'},facts)
        r={'facts':facts,'inferred':{p:[list(x) for x in rows] for p,rows in d.db.items() if p in ['schema','error','unmet']}}
        add_code(r,'solve(coins, target)');self.assertNotIn('code_files',r)

    def test_failure_and_incomplete_history(self):
        with patch('general.generate',side_effect=ValueError('no template')):
            r=add_code(self.result(),'solve(numbers)')
        self.assertNotIn('code_files',r);self.assertIn('没有使用伪代码',r['code_note'])
        r=add_code(self.result());self.assertNotIn('code_files',r)
        self.assertIn('未保存完整参数签名',r['code_note'])

if __name__=='__main__':unittest.main()
