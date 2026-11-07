import json,os,signal,subprocess,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
import evolution as e
from evolution_contracts import CONTRACTS
from test_evolution import CANDIDATE as BUBBLE
C=CONTRACTS['print_each']
PRINT={'intent':'print_each','vocabulary':C['vocabulary'],'rule':C['rule'],'source':'def solve(nums):\n    for x in nums:\n        print(x)\n','summary':'print each value on its own line'}
SEM={'intent':'print_each','input_type':'unspecified','order':'preserve','output':'stdout_lines','max_length':None,'extra_requirements':[],'active_scope':'replace'}
NORMAL={'signature':'solve(nums)','facts':[],'inferred':{},'uncovered':'not in stable vocabulary','extension_semantics':SEM}
PAYLOAD={'history':[],'signature':'solve(nums)','message':'帮我写个遍历数组并打印的方法'}

class ContractTests(unittest.TestCase):
    def validate(self,source):return e.sandbox({'mode':'validate','candidate':{**PRINT,'source':source},'contract':'print_each','param':'nums'})

    def test_exact_stdout_independent_reference(self):
        r=self.validate(PRINT['source']);self.assertEqual(r['tests'],80);self.assertEqual(r['reference'],'exact_stdout_lines_and_none_return')
        self.assertIn('duplicates',r['test_kinds']);self.assertEqual(r['stdout_limits']['lines'],128)

    def test_parameter_rename_avoids_local_capture(self):
        candidate={**PRINT,'source':'def solve(nums):\n    for i in range(len(nums)):\n        print(nums[i])\n'}
        r=e.sandbox({'mode':'validate','candidate':candidate,'contract':'print_each','param':'i'})
        self.assertEqual(r['tests'],80);self.assertIn('def solve(i)',r['source']);self.assertIn('evo_local_',r['source'])

    def test_wrong_output_implementations_rejected(self):
        wrong=[
          'def solve(nums):\n    for i in range(len(nums)-1):\n        print(nums[i])',
          'def solve(nums):\n    for x in nums:\n        print(0)',
          'def solve(nums):\n    print("extra")\n    for x in nums:\n        print(x)',
          BUBBLE['source'].replace('    return a','    for x in a:\n        print(x)'),
          'def solve(nums):\n    for x in nums:\n        print("{\\"source\\":\\"fake receipt\\"}")',
        ]
        for src in wrong:
            with self.subTest(src=src),self.assertRaises((ValueError,RuntimeError)):self.validate(src)

    def test_flood_malicious_and_timeout(self):
        for src in ['def solve(nums):\n    while True:\n        print("x")',
                    'def solve(nums):\n    for x in nums:\n        open("/tmp/file", "w")',
                    'def solve(nums):\n    for x in nums:\n        print(x, file=nums)']:
            with self.assertRaises((ValueError,RuntimeError)):self.validate(src)
        with self.assertRaises((ValueError,RuntimeError,subprocess.TimeoutExpired)):
            self.validate('def solve(nums):\n    for x in nums:\n        while True:\n            pass')

    def test_pending_resume_wrong_candidate_then_publish_and_reuse(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(e,'STORE',Path(tmp)),patch.object(e.Chat,'ask',side_effect=lambda *a,**k:{'result':json.loads(json.dumps(NORMAL))}),patch.object(e,'propose',return_value=PRINT) as model:
            (Path(tmp)/'candidates').mkdir()
            old=Path(tmp)/'candidates/8cac07a72bec4b69abcd772d02ed4e78.json'
            old.write_text(json.dumps({'id':old.stem,'status':'pending_verifier','candidate':BUBBLE,'signature':'solve(nums)','source_request':'old mixed request'}))
            r=e.evolve_legacy(PAYLOAD)
            self.assertEqual(json.loads(old.read_text())['status'],'failed')
            self.assertEqual(r['validation_state'],'verified');self.assertEqual(r['acceptance']['tests'],80)
            self.assertEqual(model.call_count,1)
            rec=json.loads(next((Path(tmp)/'versions').glob('*.json')).read_text())
            self.assertEqual([x['stage'] for x in rec['logs']],['candidate','validating','verified'])
            r2=e.evolve_legacy(PAYLOAD);self.assertEqual(r2['evolution_version'],r['evolution_version']);self.assertEqual(model.call_count,1)

    def test_matching_good_pending_needs_no_new_model(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(e,'STORE',Path(tmp)),patch.object(e.Chat,'ask',return_value={'result':NORMAL.copy()}),patch.object(e,'propose') as model:
            (Path(tmp)/'candidates').mkdir()
            p=Path(tmp)/'candidates/pending.json';p.write_text(json.dumps({'id':'pending','status':'pending','candidate':PRINT,'signature':'solve(nums)','source_request':PAYLOAD['message']}))
            r=e.evolve_legacy(PAYLOAD);model.assert_not_called();self.assertEqual(r['evolution_version'],'pending');self.assertEqual(r['model_calls'],1)

    def test_actual_cancellation_does_not_publish(self):
        with tempfile.TemporaryDirectory() as tmp:
            script='''import sys,time,json
from pathlib import Path
sys.path.insert(0,sys.argv[1]);import evolution as e
from chat_worker import answer
e.evolve=e.evolve_legacy
from test_evolution_contracts import NORMAL,PRINT,PAYLOAD
e.STORE=Path(sys.argv[2]);e.Chat.ask=lambda *a,**k:{'result':NORMAL.copy()};e.propose=lambda *a,**k:PRINT
def sandbox(p):
 if p['mode']=='probe':return {'isolated':True}
 (e.STORE/'ready').write_text('ready');time.sleep(60)
e.sandbox=sandbox
answer({**PAYLOAD,'evolution':True})
'''
            proc=subprocess.Popen([sys.executable,'-c',script,str(e.ROOT),tmp],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            try:
                deadline=time.monotonic()+5
                while not (Path(tmp)/'ready').exists() and time.monotonic()<deadline:time.sleep(.01)
                self.assertTrue((Path(tmp)/'ready').exists())
                proc.send_signal(signal.SIGTERM);proc.wait(timeout=3)
                self.assertEqual(proc.returncode,143)
                self.assertFalse(list((Path(tmp)/'versions').glob('*.json')))
                rec=json.loads(next((Path(tmp)/'candidates').glob('*.json')).read_text())
                self.assertEqual(rec['status'],'failed');self.assertIn('取消',rec['logs'][-1]['reason'])
            finally:
                if proc.poll() is None:proc.kill();proc.wait()

if __name__=='__main__':unittest.main()
