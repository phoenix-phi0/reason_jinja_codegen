import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import evolution as E
import general_evolution as G

SCORE={'active_scope':'continue','signature':'solve(score)','clarification':None,'contract':{'intent':'score_threshold','summary':'单个分数达到60分即及格','parameters':[{'name':'score','type':'number'}],'returns':'bool：及格True，否则False','constants':{'threshold':60},'preconditions':[],'requirements':['score >= 60'],'assumptions':['默认单个数值输入，返回布尔值'],'execution_policy':'pure'},'stable_facts':[],'stable_covered':False,'extension':{'intent':'other'},'candidate_source':'def solve(score):\n    return score >= 60\n','tests':[{'args':[59],'expected':False},{'args':[60],'expected':True},{'args':[61],'expected':True}],'properties':['deterministic']}
PAY={'message':'帮我做个考试分数及格判定，60分及格。','history':[],'signature':'solve(nums)'}

class GeneralTests(unittest.TestCase):
    def context(self,tmp,plans):
        return patch.multiple(G,ask=unittest.mock.Mock(side_effect=plans),progress=unittest.mock.Mock())

    def test_scalar_boundary_limited_never_trusted(self):
        p=copy.deepcopy(SCORE);p['trusted']=True;p['tests'][0]['origin']='trusted'
        with tempfile.TemporaryDirectory() as tmp,patch.object(E,'STORE',Path(tmp)),self.context(tmp,[p]):
            r=G.run(PAY)
            self.assertEqual(r['signature'],'solve(score)');self.assertEqual(r['validation_state'],'limited_tests_passed')
            self.assertEqual(r['evidence']['passed_count'],3);self.assertEqual(r['evidence']['sources']['model_generated'],3)
            self.assertFalse(list((Path(tmp)/'versions').glob('*.json')));self.assertEqual(len(list((Path(tmp)/'limited').glob('*.json'))),1)

    def test_multi_parameter_and_explicit_signature(self):
        p=copy.deepcopy(SCORE);p['signature']='solve(a, b)';p['contract']['parameters']=[{'name':'a','type':'number'},{'name':'b','type':'number'}];p['contract']['intent']='sum_difference';p['contract']['constants']={};p['contract']['requirements']=['return [a+b,a-b]'];p['candidate_source']='def solve(a,b):\n    return [a+b,a-b]';p['tests']=[{'args':[3,2],'expected':[5,1]},{'args':[0,-1],'expected':[-1,1]}]
        with tempfile.TemporaryDirectory() as tmp,patch.object(E,'STORE',Path(tmp)),self.context(tmp,[p]):
            r=G.run({**PAY,'message':'给定两个数a和b，返回和与差的列表'})
            self.assertEqual(r['validation_state'],'limited_tests_passed');self.assertEqual(r['evidence']['total'],2)
        with tempfile.TemporaryDirectory() as tmp,patch.object(E,'STORE',Path(tmp)),self.context(tmp,[SCORE]):
            r=G.run({**PAY,'message':'solve(score)\n60分及格'})
            self.assertEqual(r['signature_origin'],'explicit')

    def test_repair_uses_frozen_expected_values(self):
        p=copy.deepcopy(SCORE);p['candidate_source']='def solve(score):\n    return score > 60'
        repair={'candidate_source':SCORE['candidate_source'],'tests':[{'args':[60],'expected':False}]}
        with tempfile.TemporaryDirectory() as tmp,patch.object(E,'STORE',Path(tmp)),self.context(tmp,[p,repair]):
            r=G.run(PAY);self.assertEqual(r['validation_state'],'limited_tests_passed');self.assertEqual(r['model_calls'],2)
            rec=json.loads(next((Path(tmp)/'limited').glob('*.json')).read_text());self.assertTrue(rec['tests'][1]['expected'])

    def test_clarify_then_continue_and_no_tests(self):
        p=copy.deepcopy(SCORE);p['clarification']='输入是单个分数还是一批分数？';p['candidate_source']='';p['tests']=[]
        with tempfile.TemporaryDirectory() as tmp,patch.object(E,'STORE',Path(tmp)),self.context(tmp,[p,SCORE]):
            a=G.run({**PAY,'message':'做个判定器'});self.assertEqual(a['validation_state'],'pending')
            b=G.run({**PAY,'history':['做个判定器'],'message':'单个考试分数，60分及格','previous_contract':a['contract']})
            self.assertEqual(b['validation_state'],'limited_tests_passed')
        p=copy.deepcopy(SCORE);p['tests']=[]
        with tempfile.TemporaryDirectory() as tmp,patch.object(E,'STORE',Path(tmp)),self.context(tmp,[p]):
            self.assertEqual(G.run(PAY)['validation_state'],'pending')

    def test_reuse_requires_same_contract_range_and_signature(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(E,'STORE',Path(tmp)),self.context(tmp,[SCORE]):r=G.run(PAY)
        with tempfile.TemporaryDirectory() as tmp,patch.object(E,'STORE',Path(tmp)):
            with self.context(tmp,[SCORE]):a=G.run(PAY)
            record=json.loads(next((Path(tmp)/'limited').glob('*.json')).read_text())
            p=copy.deepcopy(SCORE);p['reuse_id']=record['id'];p['candidate_source']='';p['tests']=[]
            with self.context(tmp,[p]):b=G.run(PAY)
            self.assertEqual(b['validation_state'],'limited_tests_passed');self.assertIn('未升级',b['evolution_note'])
            p['contract']['constants']['threshold']=70
            with self.context(tmp,[p]):c=G.run(PAY)
            self.assertEqual(c['validation_state'],'pending')

    def test_user_json_examples_and_unsafe_text_only(self):
        p=copy.deepcopy(SCORE);p['tests']=[]
        with tempfile.TemporaryDirectory() as tmp,patch.object(E,'STORE',Path(tmp)),self.context(tmp,[p]):
            r=G.run({**PAY,'message':PAY['message']+'\n```tests\n[{"args":[60],"expected":true}]\n```'})
            self.assertEqual(r['evidence']['sources']['user_authorized_json'],1);self.assertEqual(r['validation_state'],'limited_tests_passed')
        p=copy.deepcopy(SCORE);p['contract']['execution_policy']='text_only';p['candidate_source']='import os\ndef solve(score):\n    return os.listdir("/home")'
        with tempfile.TemporaryDirectory() as tmp,patch.object(E,'STORE',Path(tmp)),self.context(tmp,[p]):
            r=G.run({**PAY,'message':'读取文件并处理'})
            self.assertEqual(r['validation_state'],'pending');self.assertIn('未验证文本',r['code_note'])
            self.assertFalse(list((Path(tmp)/'limited').glob('*.json')))

    def test_runtime_limits_and_malicious_candidates(self):
        for source in ['def solve(score):\n    return open("/home/box/.token").read()', 'def solve(score):\n    while True:\n        print("x")']:
            r=E.sandbox({'mode':'general_validate','source':source,'params':['score'],'tests':[{'args':[60],'expected':True}],'properties':[]})
            self.assertFalse(r.get('passed'));self.assertFalse(r.get('safe') and not r.get('failures'))

    def test_infinite_loop_is_limited(self):
        import time
        start=time.monotonic()
        try:r=E.sandbox({'mode':'general_validate','source':'def solve(score):\n    while True:\n        pass','params':['score'],'tests':[{'args':[60],'expected':True}],'properties':[]})
        except Exception:r={'passed':False}
        self.assertFalse(r.get('passed'));self.assertLess(time.monotonic()-start,15)

    def test_new_task_drops_old_explicit_signature(self):
        p=copy.deepcopy(SCORE);p['active_scope']='replace'
        with tempfile.TemporaryDirectory() as tmp,patch.object(E,'STORE',Path(tmp)),self.context(tmp,[p]):
            r=G.run({**PAY,'history':['solve(nums)\n冒泡排序'],'signature':'solve(nums)','signature_explicit':True})
            self.assertEqual(r['signature'],'solve(score)');self.assertEqual(r['signature_origin'],'inferred')
            self.assertEqual(r['context_mode'],'replace')

    def test_actual_general_cancellation_is_atomic(self):
        import subprocess,sys,signal,time
        script="""import sys,time
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import evolution as E,general_evolution as G
from chat_worker import answer
from test_general_evolution import SCORE,PAY
E.STORE=Path(sys.argv[2]);G.ask=lambda *a,**k:SCORE
G.progress=lambda *a:None
def sandbox(p):
 if p['mode']=='probe':return {'isolated':True}
 (E.STORE/'ready').write_text('ready');time.sleep(60)
E.sandbox=sandbox
answer({**PAY,'evolution':True})
"""
        with tempfile.TemporaryDirectory() as tmp:
            proc=subprocess.Popen([sys.executable,'-c',script,str(E.ROOT),tmp],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            try:
                deadline=time.monotonic()+5
                while not (Path(tmp)/'ready').exists() and time.monotonic()<deadline:time.sleep(.01)
                self.assertTrue((Path(tmp)/'ready').exists());proc.send_signal(signal.SIGTERM);proc.wait(timeout=3)
                self.assertEqual(proc.returncode,143)
                self.assertFalse(list((Path(tmp)/'limited').glob('*.json')));self.assertFalse(list((Path(tmp)/'versions').glob('*.json')))
                rec=json.loads(next((Path(tmp)/'candidates').glob('*.json')).read_text())
                self.assertEqual(rec['status'],'failed');self.assertIn('取消',rec['logs'][-1]['reason'])
            finally:
                if proc.poll() is None:proc.kill();proc.wait()

    def test_production_trusted_catalog_reuse(self):
        records=E.catalog_records()
        self.assertTrue(records)
        p=copy.deepcopy(SCORE);p['signature']='solve(nums)';p['contract']['parameters']=[{'name':'nums','type':'int_list'}]
        p['contract']['summary']='整数数组升序冒泡排序';p['extension']={'intent':'bubble_sort','input_type':'unspecified','order':'unspecified','output':'return_list','max_length':None,'extra_requirements':[]}
        p['candidate_source']='';p['tests']=[]
        with tempfile.TemporaryDirectory() as tmp,patch.object(E,'STORE',Path(tmp)),patch.object(E,'catalog_records',return_value=records),self.context(tmp,[p]):
            r=G.run({**PAY,'message':'帮我做个冒泡算法'})
            self.assertEqual(r['validation_state'],'verified');self.assertEqual(r['model_calls'],1)
            self.assertIn('没有重复生成',r['evolution_note']);self.assertTrue(r['code_files'])
            self.assertFalse(list((Path(tmp)/'candidates').glob('*.json')))

    def test_production_stable_rules_first(self):
        p=copy.deepcopy(SCORE);p['signature']='solve(nums)';p['contract']['parameters']=[{'name':'nums','type':'int_list'}]
        p['stable_covered']=True;p['stable_facts']=[['arg','nums','int_list'],['iterate','nums'],['keep','positive'],['map','square'],['aggregate','sum'],['size','nums','tiny']]
        with tempfile.TemporaryDirectory() as tmp,patch.object(E,'STORE',Path(tmp)),self.context(tmp,[p]):
            r=G.run({**PAY,'message':'整数数组长度不超过100，只对正数平方后求和，空数组返回0。'})
            self.assertEqual(r['validation_state'],'rule_generated');self.assertIn('x > 0',r['code_files'][0]['source'])
            self.assertFalse(list((Path(tmp)/'limited').glob('*.json')))

    def test_reported_bubble_extra_properties_and_real_unknown(self):
        records=E.catalog_records()
        for extras in [['preserves_input'],['保留重复元素、不修改原输入列表']]:
            p=copy.deepcopy(SCORE);p['signature']='solve(nums)';p['contract']['parameters']=[{'name':'nums','type':'int_list'}]
            p['extension']={'intent':'bubble_sort','input_type':'unspecified','order':'unspecified','output':'return_list','max_length':None,'extra_requirements':extras}
            p['candidate_source']='';p['tests']=[]
            with tempfile.TemporaryDirectory() as tmp,patch.object(E,'STORE',Path(tmp)),patch.object(E,'catalog_records',return_value=records),self.context(tmp,[p]):
                r=G.run({**PAY,'message':'帮我生成冒泡算法。'})
                self.assertEqual(r['validation_state'],'verified');self.assertTrue(r['code_files']);self.assertEqual(r['evolution_version'],next(x['id'] for x in records if x['candidate']['intent']=='bubble_sort'))
                self.assertFalse(list((Path(tmp)/'candidates').glob('*.json')))
                self.assertTrue(r['acceptance']['input_preserved']);self.assertTrue(r['acceptance']['returns_new_list'])
            p['extension']['extra_requirements'].append('额外统计交换次数')
            with tempfile.TemporaryDirectory() as tmp,patch.object(E,'STORE',Path(tmp)),self.context(tmp,[p]):
                r=G.run({**PAY,'message':'冒泡排序并统计交换次数'})
                self.assertEqual(r['validation_state'],'pending');self.assertFalse(r['code_files'])

if __name__=='__main__':unittest.main()
