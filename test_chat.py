import json
import threading
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from http.server import ThreadingHTTPServer
import chat

FACTS=[['arg','nums','sequence'],['input','nums','sequence']]

class ChatTests(unittest.TestCase):
    def setUp(self):
        self.c=chat.Chat();self.a=self.c.create();self.b=self.c.create()

    def test_multi_isolation_reset(self):
        seen=[]
        def extract(p,*args,**kwargs): seen.append(p['statement']);return [],'not covered'
        with patch('general.extract',side_effect=extract):
            first=self.c.ask(self.a,'数组 nums 求和','solve(nums)')
            self.c.ask(self.a,'只统计正数','solve(nums)')
            self.c.ask(self.b,'另一题','solve(nums)')
            self.assertIn('数组 nums 求和',seen[1]);self.assertNotIn('数组 nums 求和',seen[2])
            self.assertIn('explanation',first['result'])
            self.c.reset(self.a);self.c.ask(self.a,'新的问题','solve(nums)')
            self.assertNotIn('只统计正数',seen[3])

    def test_validation(self):
        with patch('general.extract') as m:
            for value in ['',None,'x'*6001,[]]:
                with self.assertRaises(ValueError):self.c.ask(self.a,value,'solve(nums)')
            for sig in ['x','solve(a,a)','solve(a); rm -rf /','solve()']:
                with self.assertRaises(ValueError):self.c.ask(self.a,'题目',sig)
            m.assert_not_called()

    def test_errors_and_busy(self):
        with patch('general.extract',side_effect=RuntimeError('sensitive stderr')):
            with self.assertRaisesRegex(RuntimeError,'模型翻译失败') as e:self.c.ask(self.a,'题目','solve(nums)')
            self.assertNotIn('sensitive',str(e.exception))
        self.assertEqual(self.c.session(self.a)['history'],[])
        self.c.worker.acquire()
        try:
            with self.assertRaises(BlockingIOError):self.c.ask(self.a,'题目','solve(nums)')
        finally:self.c.worker.release()
        with patch('general.extract',return_value=([['unknown','x']],None)):
            with self.assertRaises(RuntimeError):self.c.ask(self.a,'题目','solve(nums)')

    def test_real_engine_missing_premise(self):
        facts=[['arg','coins','int_list'],['arg','target','int'],['items','coins'],['target','target'],['ask','min_count']]
        with patch('general.extract',return_value=(facts,None)):
            r=self.c.ask(self.a,'用硬币凑目标','solve(coins, target)')['result']
        self.assertTrue(r['inferred'].get('unmet'))
        self.assertIn(['unmet_precondition','p'], r['inferred']['error'])
        self.assertEqual(r['status'],'blocked')

    def test_http(self):
        s=ThreadingHTTPServer(('127.0.0.1',0),chat.Handler);s.chat=self.c
        t=threading.Thread(target=s.serve_forever,daemon=True);t.start()
        base=f'http://127.0.0.1:{s.server_port}'
        try:
            with urlopen(base) as r:self.assertIn('推理机',r.read().decode())
            req=Request(base+'/api/session',b'{}',{'Content-Type':'application/json'})
            with urlopen(req) as r:self.assertIn('session',json.load(r))
            for headers,body in [({'Content-Type':'application/json','Origin':'https://evil.example'},b'{}'),({'Content-Type':'application/json'},b'[]')]:
                with self.assertRaises(HTTPError):urlopen(Request(base+'/api/session',body,headers))
        finally:s.shutdown();s.server_close();t.join()

if __name__=='__main__':unittest.main()
