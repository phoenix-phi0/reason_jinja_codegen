import unittest
from unittest.mock import patch
from chat import Chat
from chat_scope import scoped

BASE=[['arg','nums','int_list'],['iterate','nums'],['aggregate','sum'],['size','nums','tiny']]
SQUARE=BASE+[['keep','positive'],['map','square']]

class ScopeTests(unittest.TestCase):
    def test_bubble_then_complete_new_question(self):
        c=Chat();sid=c.create();seen=[]
        def extract(p,*a,**kw):
            seen.append(p['statement'])
            return (BASE,'不支持冒泡排序') if len(seen)==1 else (SQUARE,None)
        with patch('general.extract',side_effect=extract):
            a=c.ask(sid,'生成冒泡排序','solve(nums)')
            self.assertNotIn('code_files',a['result'])
            b=c.ask(sid,'整数数组长度不超过100，只对正数平方后求和，空数组返回0。','solve(nums)')
        self.assertNotIn('冒泡',seen[1]);self.assertEqual(b['result']['context_mode'],'replace')
        source=b['result']['code_files'][0]['source']
        self.assertIn('x > 0',source);self.assertIn('x * x',source);self.assertIn('sum(values)',source)
        self.assertIn('平方',b['result']['answer'])

    def test_followup_withdrawal_and_real_unsupported(self):
        c=Chat();sid=c.create();seen=[]
        def extract(p,*a,**kw):
            self.assertIn('withdrawals',kw['hint']);seen.append(p['statement'])
            if len(seen)==4:return BASE,'要求指定冒泡排序仍不支持'
            return (SQUARE,None) if len(seen)==2 else (BASE,None)
        with patch('general.extract',side_effect=extract):
            c.ask(sid,'整数数组长度≤100求和','solve(nums)')
            c.ask(sid,'补充：只对正数平方后求和','solve(nums)')
            r=c.ask(sid,'撤销正数筛选和平方要求，所有元素直接求和','solve(nums)')
            self.assertIn('整数数组',seen[1]);self.assertIn('撤销',seen[2])
            self.assertNotIn('x > 0',r['result']['code_files'][0]['source'])
            self.assertNotIn('x * x',r['result']['code_files'][0]['source'])
            unsupported=c.ask(sid,'另外必须使用冒泡排序','solve(nums)')
            self.assertNotIn('code_files',unsupported['result'])

    def test_explicit_reset_signature_and_failure_atomicity(self):
        h=['要求冒泡']
        active,sig,mode,note=scoped(h,'换题\nsolve(s)\n字符串s判断回文','solve(nums)')
        self.assertNotIn('要求冒泡',active);self.assertEqual(sig,'solve(s)');self.assertEqual(mode,'replace')
        with self.assertRaises(ValueError):scoped(h,'solve(s)\n补充','solve(nums)')
        c=Chat();sid=c.create()
        with patch('general.extract',return_value=(BASE,None)):c.ask(sid,'求和','solve(nums)')
        old=list(c.session(sid)['history'])
        with patch('general.extract',side_effect=RuntimeError('failed')):
            with self.assertRaises(RuntimeError):c.ask(sid,'换题\n新问题','solve(nums)')
        self.assertEqual(c.session(sid)['history'],old)

if __name__=='__main__':unittest.main()
