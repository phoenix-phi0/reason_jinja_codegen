"""Bounded general workflow: requirement data -> rules/learned code -> isolated evidence -> answer."""
import fcntl,hashlib,json,math,re,subprocess,tempfile,time,uuid
from pathlib import Path
import evolution as E
import general
from chat_codegen import add_code
from chat_scope import scoped
from evolution_contracts import CONTRACTS

MAX_TESTS=32

def progress(text):
    print(json.dumps({'event':{'t':'info','d':text}},ensure_ascii=False),flush=True)


def ask(prompt):
    p=subprocess.run(['claude','-p','--model','haiku','--tools','','--no-session-persistence','--strict-mcp-config'],input=prompt,capture_output=True,text=True,timeout=140,cwd=tempfile.gettempdir())
    if p.returncode or len(p.stdout)>100000:raise RuntimeError('模型调用失败或回复过大，未启用候选')
    try:return general.first_json_object(p.stdout)
    except Exception:raise RuntimeError('模型未返回有效结构化需求，未执行代码') from None


def params(signature):
    if not isinstance(signature,str) or not re.fullmatch(r'solve\((?:[A-Za-z][A-Za-z0-9_]*(?:\s*,\s*[A-Za-z][A-Za-z0-9_]*)*)?\)',signature):raise ValueError('需要有效的solve参数签名')
    names=general.params_of(signature)
    if len(names)>8 or len(set(names))!=len(names) or any(x in {'print','len','range','list','str','int','float','bool','dict','set','tuple','sum','max','min'} for x in names):raise ValueError('参数不唯一、过多或与保留名称冲突')
    return names


def safe_value(x,depth=0):
    if depth>5:return False
    if x is None or type(x) is bool:return True
    if type(x) in (int,float):return math.isfinite(x) and abs(x)<=1000000
    if isinstance(x,str):return len(x)<=512
    if isinstance(x,list):return len(x)<=64 and all(safe_value(y,depth+1) for y in x)
    if isinstance(x,dict):return len(x)<=32 and all(isinstance(k,str) and len(k)<=64 and safe_value(v,depth+1) for k,v in x.items())
    return False


def clean_tests(raw,origin,names):
    result=[]
    if not isinstance(raw,list):return result
    for t in raw[:MAX_TESTS]:
        if not isinstance(t,dict) or not isinstance(t.get('args'),list) or len(t['args'])!=len(names):continue
        if not ('expected' in t or 'stdout' in t) or not safe_value(t['args']):continue
        if 'expected' in t and not safe_value(t['expected']):continue
        stdout=t.get('stdout','')
        if not isinstance(stdout,str) or len(stdout.encode())>8192 or stdout.count('\n')>128:continue
        case={'args':t['args'],'stdout':stdout,'origin':origin}
        if 'expected' in t:case['expected']=t['expected']
        result.append(case)
    return result


def user_cases(active,names):
    cases=[]
    for text in active:
        for body in re.findall(r'```tests\s*\n(.*?)```',text,re.S):
            try:cases+=clean_tests(json.loads(body),'user_authorized_json',names)
            except (ValueError,TypeError):pass
    return cases[:16]


def digest(x):return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def request_hash(text):return digest(re.sub(r'\s+',' ',text.strip()))


def base_result(signature,contract,scope_note,mode):
    return {'workflow':'general_code','signature':signature,'contract':contract,'context_mode':mode,'context_note':scope_note,
            'signature_origin':'inferred','model_calls':1,'facts':[],'inferred':{},'code_files':[],'assumptions':contract.get('assumptions',[])}


def present(r):
    labels={'verified':'已验证：有独立可信参考','limited_tests_passed':'有限测试通过：仅草稿，不是已验证能力','rule_generated':'已有规则生成','pending':'待确认：尚未可靠验证','failed':'候选未通过测试'}
    lines=[r.get('context_note',''),labels.get(r.get('validation_state'),'需求处理中')]
    c=r.get('contract',{})
    if c.get('summary'):lines+=['题意理解（模型归纳，请核对）：'+str(c['summary'])]
    lines+=['采用函数签名：'+r.get('signature','待确认')]
    if c.get('parameters'):lines+=['输入：'+'；'.join(str(x.get('name'))+'（'+str(x.get('type','未明确'))+'）' for x in c['parameters'] if isinstance(x,dict))]
    if c.get('returns'):lines+=['输出：'+str(c['returns'])]
    if r.get('assumptions'):lines+=['明确假设：'+'；'.join(map(str,r['assumptions']))]
    if r.get('question'):lines+=['请补充：'+r['question']]
    if r.get('evolution_note'):lines+=[r['evolution_note']]
    evidence=r.get('evidence',{})
    if evidence.get('total'):
        lines+=['受控测试：'+str(evidence.get('passed_count',evidence['total']))+'/'+str(evidence['total'])+'组通过；来源：'+str(evidence.get('sources',{}))+'。']
    if r.get('validation_state')=='limited_tests_passed':lines+=['这些期望值来自模型或明确提供的用户例子，不能证明普适正确；没有进入已验证库或稳定规则。']
    lines+=['只运行受控合成测试/明确授权的示例，没有运行你的实际输入；有限测试不是数学证明。']
    r['human_answer']='\n\n'.join(x for x in lines if x)
    return r


def plan_prompt(active,signature,explicit,previous,records,drafts):
    catalog=[{'id':r['id'],'intent':r['candidate']['intent'],'scope':CONTRACTS[r['candidate']['intent']]['scope']} for r in records]
    return '''Build a Python FUNCTION for the final active user requirement. You have no tools; do not execute anything. Return JSON data and Python source only, never a runner, oracle implementation, or trusted=true claim.
Do not default to arrays. Infer scalar/multiple inputs and a natural solve(...) signature. Explicit user signature is mandatory only in the final active scope; when replacing a task and the latest message has no signature, do not force an old task signature. Otherwise infer names/types. Use reasonable minor defaults (e.g. threshold classification returns bool) and disclose assumptions; ask one clear question only when essential semantics are missing. For numeric threshold T synthesize boundary T-1,T,T+1 (include exact integers for integer thresholds), negative/zero/normal examples. Never execute actual supplied user data; tests must be small synthetic cases or an explicit fenced tests block.
A new standalone method request replaces prior unrelated tasks; supplements/corrections/withdrawals modify the current task. State active_scope replace/continue/ambiguous. Do not repeat a previously answered clarification. Preserve explicit requirements, including constants, types, return representation and bounds.
Prefer existing stable rules when they truly cover the final task. Stable facts must use ONLY the stable vocabulary below. Learned capabilities are separately available and not rejected just because stable vocabulary lacks them. Do not list behaviors already guaranteed by a trusted contract as extra requirements: sorting preserves duplicates; this published bubble implementation returns a fresh list without mutating input. Validation length<=100 is a verified range, never a user-supplied condition. If a verified match is compatible you can leave candidate_source/tests empty. Otherwise generate a reusable pure function and controlled tests (args,expected,stdout). No imports, classes, annotations, decorators or file/network/system access in executable candidates. Only pure Python data operations and safe standard builtins; print is captured. Helpers are allowed. File/network/system requirements may get text-only unverified drafts, never automatic execution.
Return schema:
{"active_scope":"continue|replace|ambiguous", "signature":"solve(score)", "clarification":null_or_question,
 "contract":{"intent":"free canonical id", "summary":"Chinese requirement", "parameters":[{"name":"score","type":"number|integer|string|boolean|int_list|list|dict|json"}], "returns":"type and exact representation", "constants":{}, "preconditions":[], "requirements":[], "assumptions":[], "execution_policy":"pure|text_only"},
 "stable_facts":[],"stable_covered":false,"stable_uncovered":null,
 "extension":{"intent":"bubble_sort|print_each|other", "input_type":"int_list|unspecified|other", "order":"ascending|descending|preserve|unspecified|other", "output":"return_list|stdout_lines|unspecified|other", "max_length":null, "extra_requirements":[]},
 "candidate_source":"def solve(score):...", "tests":[{"args":[59],"expected":false,"stdout":""}], "properties":["deterministic","preserves_input"], "reuse_id":null}
The tests and their expected values YOU create are MODEL evidence only, never independently trusted. Do not change test expected values to fit code. For a matching limited draft you may reuse_id and echo its contract exactly, but it remains LIMITED evidence. No code if essential semantic clarification is needed.
'''+json.dumps({'active_messages':active,'signature':signature,'signature_is_explicit':explicit,'previous_contract':previous,
               'verified_catalog':catalog,'trusted_contracts':{k:v['scope'] for k,v in CONTRACTS.items()},'limited_drafts':drafts,
               'stable_vocabulary':general.vocab()},ensure_ascii=False)


def run(payload):
    E.CURRENT=None;E.STORE.mkdir(mode=0o700,exist_ok=True)
    for name in ['candidates','versions','limited']:(E.STORE/name).mkdir(mode=0o700,exist_ok=True)
    with open(E.STORE/'request.lock','a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('进化版正在处理另一请求，请稍后重试')
        E.sandbox({'mode':'probe'})
        progress('阶段1/4：识别输入、输出、条件与证据；不默认数组。')
        history=payload.get('history',[]);message=payload.get('message','')
        if not isinstance(message,str) or not message.strip() or len(message)>6000 or len(history)>20 or sum(map(len,history))>18000:raise ValueError('问题或上下文超出限制')
        active,old_sig,mode,note=scoped(history,message,payload.get('signature','solve(nums)'))
        explicit=False
        for text in active:
            match=re.match(r'^\s*(solve\([^\n]*\))\s*(?:\n|$)',text)
            if match:old_sig=match.group(1);explicit=True
        req_hash=request_hash(active[-1]);records=E.catalog_records()
        draft_records=[]
        for f in sorted((E.STORE/'limited').glob('*.json'))[:100]:
            rec=json.loads(f.read_text())
            if rec.get('request_hash')==req_hash:draft_records.append(rec)
        drafts=[{'id':d['id'],'contract':d['contract'],'signature':d['signature'],'evidence_level':'limited_tests_passed'} for d in draft_records]
        plan=ask(plan_prompt(active,old_sig,explicit,payload.get('previous_contract'),records,drafts))
        if plan.get('active_scope')=='replace':
            active,_,_,_=scoped([],message,old_sig);mode='replace';note='本轮按新的独立需求处理，旧题不参与；消息历史保留。'
            latest_signature=re.match(r'^\s*(solve\([^\n]*\))\s*(?:\n|$)',active[-1])
            explicit=latest_signature is not None
            if latest_signature:old_sig=latest_signature.group(1)
        signature=old_sig if explicit else plan.get('signature')
        names=params(signature)
        contract=plan.get('contract')
        if not isinstance(contract,dict) or len(json.dumps(contract))>16000:raise ValueError('需求契约格式无效')
        if [x.get('name') for x in contract.get('parameters',[]) if isinstance(x,dict)]!=names:raise ValueError('契约参数与函数签名不一致，请确认输入参数')
        r=base_result(signature,contract,note,mode);r['signature_origin']='explicit' if explicit else 'inferred'
        if plan.get('clarification') or plan.get('active_scope')=='ambiguous':
            r.update(validation_state='pending',question=str(plan.get('clarification') or '这条消息是替换旧需求还是继续补充？'),code_note='需求尚不明确，未执行或启用候选。')
            return present(r)
        facts=plan.get('stable_facts',[])
        if plan.get('stable_covered') is True and not plan.get('stable_uncovered') and isinstance(facts,list) and len(facts)<=200:
            try:
                if not general.validate(facts,names,general.vocab()):
                    problem={'id':'chat','signature':signature,'tests':[]};engine=general.engine_for(problem,facts)
                    inferred={p:[list(v) for v in rows] for p,rows in engine.db.items() if p in {'schema','answer_type','error','uses'}}
                    if inferred.get('schema') and not inferred.get('error'):
                        r.update(facts=facts,inferred=inferred);r.pop('code_files',None);add_code(r,signature)
                        if r.get('code_files'):
                            r.update(validation_state='rule_generated',evolution_note='已有规则与模板覆盖本题；没有调用新候选或运行用户输入。');return present(r)
            except Exception:pass
        progress('阶段2/4：规则未覆盖时尝试候选；已学能力优先复用，证据等级不会自动升级。')
        sem=plan.get('extension',{});allowed,why,scope=E.admission(sem,signature,'\n'.join(active));intent=sem.get('intent') if isinstance(sem,dict) else None
        if intent in CONTRACTS:
            if not allowed:
                r.update(validation_state='pending',evolution_note=why,question='请确认输入类型、范围或额外要求。',code_note='不兼容已验证契约，未按其他默认条件替代。');return present(r)
            known=next((x for x in records if x['candidate']['intent']==intent),None)
            if known:
                report=E.sandbox({'mode':'validate' if scope.get('requested_properties') else 'render','candidate':known['candidate'],'contract':intent,'param':names[0]})
                out=E.attach(r,report,known['id'],False,scope,report if scope.get('requested_properties') else known['validation']);out.update(workflow='general_code',validation_state='verified',contract=contract)
                return present(out)
            source=plan.get('candidate_source','')
            candidate={'intent':intent,'source':source,'vocabulary':CONTRACTS[intent]['vocabulary'],'rule':CONTRACTS[intent]['rule']}
            ident=uuid.uuid4().hex;rec={'id':ident,'candidate':candidate,'signature':signature,'source_request':'\n'.join(active),'model':'haiku','contract':intent,'created':time.time()}
            path=E.STORE/'candidates'/(ident+'.json');E.stage(path,rec,'candidate','模型候选，未启用')
            progress('阶段3/4：绑定独立可信行为契约，在无网络沙箱自动生成并核对测试。')
            report=E.validate_publish(rec,path,intent,names[0])
            if report:
                out=E.attach(r,report,ident,True,scope,report);out.update(workflow='general_code',contract=contract);progress('阶段4/4：独立参考通过，原子发布并返回当前问题的代码。');return present(out)
            r.update(validation_state='failed',evolution_note='候选未通过独立参考测试，未启用。',code_note='没有给出未通过验证的代码充当答案。');return present(r)
        # Generic fallback: independent evidence is NOT invented for a new task.
        source=plan.get('candidate_source','')
        tests=clean_tests(plan.get('tests',[]),'model_generated',names)
        authorized=user_cases(active,names)
        tests=(authorized+tests)[:MAX_TESTS]
        properties=[x for x in (plan.get('properties') or []) if isinstance(x,str) and x in {'deterministic','preserves_input'}]
        reuse=next((d for d in draft_records if d['contract']==contract and d['signature']==signature and (not plan.get('reuse_id') or d['id']==plan.get('reuse_id'))),None)
        if reuse:
            source=reuse['source'];tests=reuse['tests'];properties=reuse.get('properties',[])
        ident=reuse['id'] if reuse else uuid.uuid4().hex
        rec={'id':ident,'signature':signature,'contract':contract,'source':source,'tests':tests,'properties':properties,'logs':reuse.get('logs',[]) if reuse else [],
                                 'request_hash':req_hash,'scope_hash':digest({'signature':signature,'contract':contract}),
                                 'created':time.time(),'source_request':'\n'.join(active),'model':'haiku','evidence_level':'unverified'}
        path=E.STORE/'candidates'/(ident+'.json');E.stage(path,rec,'candidate','通用候选及测试数据；模型期望值不可信升级')
        text_only=contract.get('execution_policy')=='text_only' or bool(re.search(r'读取文件|写入文件|删除文件|联网|下载|执行.*命令|连接数据库',active[-1]))
        if text_only:
            E.sandbox({'mode':'general_inspect','source':source,'params':names})
            E.stage(path,rec,'pending','文件/网络/系统需求不自动执行')
            r.update(validation_state='pending',code_files=[{'name':'unverified_draft.py','source':source}] if isinstance(source,str) and source else [],code_note='仅未验证文本草稿；文件、网络和系统行为不会在服务器执行。',evolution_note='缺少可安全自动执行的纯函数契约。');return present(r)
        if not source or not tests:
            E.stage(path,rec,'pending','没有完整代码或有效判断依据，未执行')
            r.update(validation_state='pending',question='请提供期望行为或一个输入→输出例子；也可用```tests JSON数组```明确授权示例测试。',code_note='没有有效测试依据，未运行或启用候选。');return present(r)
        progress('阶段3/4：语法/安全检查和受控测试；模型生成期望值只算有限证据。')
        E.stage(path,rec,'validating','通用纯函数沙箱；原始测试及期望值冻结')
        report=None
        for attempt in range(2):
            try:report=E.sandbox({'mode':'general_validate','source':source,'params':names,'tests':tests,'properties':properties})
            except Exception:report={'passed':False,'reason':'沙箱资源上限或运行失败','failure_kind':'resource'}
            if report.get('passed'):break
            if attempt==1:break
            progress('测试未通过：最多修正一次代码；不允许改动原始测试期望值。')
            fixed=ask('Fix ONLY this pure Python function based on frozen tests. Return JSON {"candidate_source":"..."}. Do not change signature, requirements, tests, expected values, or write a runner. No imports/file/network/system/reflection.\n'+json.dumps({'signature':signature,'contract':contract,'source':source,'tests':tests,'feedback':report},ensure_ascii=False))
            r['model_calls']+=1;source=fixed.get('candidate_source','')
        rec.update(source=source,validation=report)
        if not report or not report.get('passed'):
            E.stage(path,rec,'failed','最多一次修正后仍未通过；没有发布',report)
            r.update(validation_state='failed',evolution_note='候选未通过冻结测试或安全/资源限制，未启用。请核对需求与例子。',evidence=report or {},code_note='失败代码未作为可用答案展示。');return present(r)
        sources={origin:sum(t['origin']==origin for t in tests) for origin in {'model_generated','user_authorized_json'}}
        rec.update(source=report['source'],evidence_level='limited_tests_passed',model_calls=r['model_calls'])
        E.stage(path,rec,'limited_tests_passed','仅有限测试；绝不写入已验证版本库',report)
        E.atomic(E.STORE/'limited'/(ident+'.json'),rec)
        progress('阶段4/4：有限测试通过，保存到独立草稿区并回答当前问题；不是已验证能力。')
        r.update(validation_state='limited_tests_passed',code_files=[{'name':'solution.py','source':report['source']}],
                 code_note='有限测试通过的模型草稿；适用范围以本轮契约和测试为准，不是普适正确性证明。没有进入稳定规则或已验证能力库。',
                 evidence={**report,'sources':sources},limited_draft_id=ident,evolution_note='复用同契约的有限验证草稿，证据等级未升级。' if reuse else '已完成候选→测试→有限修正→返回当前问题的流程。')
        return present(r)
