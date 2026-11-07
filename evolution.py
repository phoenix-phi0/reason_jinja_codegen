"""Bounded, versioned evolution overlay; never edits the stable pack."""
import fcntl,hashlib,json,os,re,subprocess,tempfile,time,uuid
from pathlib import Path
import general
from chat import Chat
from chat_scope import scoped
from evolution_translate import translator
from evolution_contracts import CONTRACTS
ROOT=Path(__file__).resolve().parent
STORE=ROOT/'evolution_library'
CURRENT=None
RULE='evolved(P,bubble_sort) :- intent(P,bubble_sort), order(P,ascending), input(P,int_list).'


def sandbox(payload):
    with tempfile.TemporaryDirectory(prefix='evolution_input_') as tmp:
        request=Path(tmp)/'request.json';request.write_text(json.dumps(payload))
        cmd=['prlimit','--as=268435456','--cpu=4','--fsize=1048576','--nofile=64','--',
             'bwrap','--unshare-all','--die-with-parent','--new-session','--ro-bind','/usr','/usr',
             '--ro-bind','/lib','/lib','--ro-bind','/lib64','/lib64','--proc','/proc','--dev','/dev',
             '--tmpfs','/tmp','--dir','/input','--ro-bind',str(request),'/input/request.json',
             '--ro-bind',str(ROOT/'evolution_sandbox.py'),'/input/runner.py',
             '--ro-bind',str(ROOT/'datalog.py'),'/input/datalog.py',
             '--ro-bind',str(ROOT/'evolution_contracts.py'),'/input/evolution_contracts.py',
             '--ro-bind',str(ROOT/'general_candidate_sandbox.py'),'/input/general_candidate_sandbox.py',
             '--clearenv','--setenv','PATH','/usr/bin:/bin','--chdir','/tmp',
             '/usr/bin/python3','-I','/input/runner.py']
        p=subprocess.run(cmd,capture_output=True,text=True,timeout=10)
        try:result=json.loads(p.stdout)
        except Exception:raise RuntimeError('隔离验证不可用或超时，候选不会生效') from None
        if p.returncode or result.get('error'):raise ValueError('候选未通过隔离验证，未发布')
        return result



def atomic(path,data):
    tmp=path.with_suffix('.tmp-'+uuid.uuid4().hex)
    with os.fdopen(os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'w') as f:json.dump(data,f,ensure_ascii=False,indent=2);f.flush();os.fsync(f.fileno())
    os.replace(tmp,path)


def propose(statement,signature,intent=None):
    contract=CONTRACTS.get(intent)
    prompt=('Propose a reusable isolated code extension. No tools, no execution. Reply JSON only: intent,vocabulary,rule,source,summary. '
            'source contains ONLY def solve(nums), no imports, attributes/methods, annotations, decorators, filesystem/network, exec/eval. '
            'Only the trusted contract allowed calls. Never provide expected test outputs: independent harness generates/tests them. '
            'Use loops implementing the behavior, not one-off outputs. Bubble sort: list(nums), nested loops and adjacent tuple swap, no sorted. '
            'print_each: traversal loop with print(value), exactly one line per element in original order, no extra text, no return value, no mutation. '
            'Trusted contract (copy intent/vocabulary/rule exactly; unknown contracts stay pending): '+
            json.dumps({'intent':intent,**contract} if contract else {},ensure_ascii=False)+'\nSignature: '+signature+'\nActive requirement:\n'+statement)
    p=subprocess.run(['claude','-p','--model','haiku','--tools','','--no-session-persistence','--strict-mcp-config'],input=prompt,capture_output=True,text=True,timeout=110,cwd=tempfile.gettempdir())
    if p.returncode:raise RuntimeError('成长模型调用失败')
    if len(p.stdout)>40000:raise ValueError('候选过大')
    return general.first_json_object(p.stdout)


def catalog_records():
    records=[]
    if (STORE/'versions').exists():
        for f in sorted((STORE/'versions').glob('*.json'))[:100]:
            rec=json.loads(f.read_text())
            if rec.get('status') in {'validated','verified'} and rec.get('candidate',{}).get('intent') in CONTRACTS and rec.get('validation',{}).get('tests')==80:records.append(rec)
    return records


def admission(semantics,signature,statement):
    if not isinstance(semantics,dict):return False,'没有可靠识别本轮需求，请说明当前行为。',None
    intent=semantics.get('intent');contract=CONTRACTS.get(intent)
    if not contract:return False,'还没有能独立核对该行为的参考契约；需要可信参考输出或独立性质组合，模型自给期望值不足以启用。',None
    if len(general.params_of(signature))!=1:return False,'已验证契约仅接受一个数组参数；不会改写你的签名。',None
    name=general.params_of(signature)[0]
    if name.startswith('_') or name in set(contract['calls']):return False,'参数名与受限模板冲突，请确认签名。',None
    kind=semantics.get('input_type');order=semantics.get('order');extras=semantics.get('extra_requirements')
    if kind not in {'int_list','unspecified'}:return False,'该契约只验证整数数组；其他数据类型待验证。',None
    if order not in {contract['order'],'unspecified'}:return False,'要求的顺序与当前契约不一致；不会换成另一个顺序冒充。',None
    output=semantics.get('output','unspecified')
    if output not in {contract['output'],'unspecified'}:return False,'要求的输出方式与现有独立参考不一致，待验证。',None
    recognized=[];unknown=[]
    aliases={'bubble_sort':{'preserves_input':'preserves_input','不修改原输入列表':'preserves_input','不修改输入':'preserves_input','不修改原数组':'preserves_input','不修改原列表':'preserves_input','保留重复元素':'preserves_duplicates','保留重复值':'preserves_duplicates','preserves_duplicates':'preserves_duplicates','返回新列表':'returns_new_list'}}
    for extra in extras if isinstance(extras,list) else []:
        for item in re.split(r'[、，,；;]',str(extra)):
            item=item.strip().rstrip('。')
            prop=aliases.get(intent,{}).get(item)
            (recognized if prop else unknown).append(prop or item)
    if not isinstance(extras,list) or unknown:return False,'额外要求尚未绑定独立参考：'+('、'.join(str(x) for x in extras) if isinstance(extras,list) else '需求信息不完整')+'。没有重复生成候选。',None
    limit=semantics.get('max_length')
    if limit is not None and (type(limit) is not int or limit<0):return False,'无法可靠理解规模上限。',None
    if limit is not None and str(limit) not in statement:limit=None
    if limit is not None and limit>contract['max_length']:return False,'长度上限超过100，超出现有验证范围；不会标记为已支持或重复生成相同候选。',None
    assumptions=[]
    if kind=='unspecified':assumptions.append('输入默认按整数数组处理')
    if order=='unspecified':assumptions.append('排序顺序默认升序' if intent=='bubble_sort' else '保持输入原顺序')
    if intent=='print_each' and output=='unspecified':assumptions.append('默认每个元素单独打印一行，空数组不输出，方法返回None')
    return True,'',{'intent':intent,'assumptions':assumptions,'explicit_max_length':limit,'input_type':kind,'order':order,'requested_properties':sorted(set(recognized))}


def stage(path,rec,status,reason,report=None):
    global CURRENT
    CURRENT=(path,rec)
    rec['status']=status
    rec.setdefault('logs',[]).append({'stage':status,'at':time.time(),'reason':reason,'tests':(report or {}).get('tests',0)})
    rec['logs']=rec['logs'][-20:]
    if report is not None:rec['validation']=report
    atomic(path,rec)


def validate_publish(rec,path,intent,param):
    stage(path,rec,'validating','绑定独立契约 '+intent+'；自动生成测试并在隔离环境精确核对')
    try:report=sandbox({'mode':'validate','candidate':rec['candidate'],'contract':intent,'param':param})
    except Exception:
        stage(path,rec,'failed','候选未通过目标契约的规则/静态安全/独立参考/资源限制核对；未启用')
        return None
    rec['sha256']=hashlib.sha256(json.dumps(rec['candidate'],sort_keys=True).encode()).hexdigest()
    stage(path,rec,'verified','通过独立参考有限用例；不是数学证明',report)
    atomic(STORE/'versions'/(rec['id']+'.json'),rec)
    return report


def matching_pending(statement,signature,intent):
    approved=STORE/'candidates'/'8cac07a72bec4b69abcd772d02ed4e78.json'
    files=[approved] if intent=='print_each' and approved.exists() else []
    normalize=lambda x:re.sub(r'[\s，。,.！!]+','',x)
    for f in sorted((STORE/'candidates').glob('*.json'))[:100]:
        if f in files:continue
        rec=json.loads(f.read_text())
        if rec.get('signature')==signature and normalize(rec.get('source_request',''))==normalize(statement):files.append(f)
    for f in files:
        rec=json.loads(f.read_text())
        if rec.get('status') in {'pending','pending_verifier','candidate','validating'}:return f,rec
    return None,None


def evolve_legacy(payload):
    global CURRENT
    CURRENT=None
    STORE.mkdir(mode=0o700,exist_ok=True)
    for n in ['candidates','versions']:(STORE/n).mkdir(mode=0o700,exist_ok=True)
    with open(STORE/'request.lock','a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('进化库正在处理另一请求，请稍后重试')
        sandbox({'mode':'probe'})
        records=catalog_records()
        catalog=[{'version':r['id'],'intent':r['candidate']['intent'],'vocabulary':r['candidate']['vocabulary'],
                  'verification_scope':CONTRACTS[r['candidate']['intent']]['scope']} for r in records]
        state={}
        c=Chat(translator=translator(catalog,state));sid=c.create()
        c.session(sid).update(history=payload.get('history',[]),signature=payload['signature'])
        normal=c.ask(sid,payload['message'],payload['signature'])['result'];normal['model_calls']=1
        semantics=state.get('extension') or normal.get('extension_semantics')
        active,sig,_,_=scoped(payload.get('history',[]),payload['message'],payload['signature'])
        if isinstance(semantics,dict) and semantics.get('active_scope')=='replace' and payload.get('history'):
            active,sig,_,_=scoped([],payload['message'],payload['signature'])
            normal['context_mode']='replace';normal['context_note']='已识别新的独立方法请求，旧题不参与本轮；历史仍保留。'
        statement='\n'.join(active);normal['extension_semantics']=semantics
        if isinstance(semantics,dict) and semantics.get('active_scope')=='ambiguous' and payload.get('history'):
            normal.update(evolution_note='无法确认这是换题还是补充，请点“换题”发送完整要求，或明确说明继续原题；没有执行验证或成长。',validation_state='pending')
            return normal
        if normal.get('code_files'):
            normal['evolution_note']='稳定规则已覆盖，没有成长或验证候选。';return normal
        allowed,reason,scope=admission(semantics,sig,statement)
        intent=semantics.get('intent') if isinstance(semantics,dict) else None
        if intent in CONTRACTS and not allowed:
            normal.update(evolution_note=reason,validation_state='pending');return normal
        if not isinstance(semantics,dict) or intent=='ambiguous':
            normal.update(evolution_note=reason or '需求关系不明确，未自动成长。',validation_state='pending');return normal
        param=general.params_of(sig)[0] if len(general.params_of(sig))==1 else None
        known=next((r for r in records if r['candidate']['intent']==intent),None)
        if allowed and known:
            report=sandbox({'mode':'render','candidate':known['candidate'],'contract':intent,'param':param})
            return attach(normal,report,known['id'],False,scope,known['validation'])
        path,previous=matching_pending(statement,sig,intent)
        resume_note=''
        if previous is not None:
            if allowed:
                report=validate_publish(previous,path,intent,param)
                if report:return attach(normal,report,previous['id'],True,scope,report)
                resume_note='已受控核对旧候选，但其内容未通过当前行为契约，未启用；已在本请求内继续提出一个新候选。'
            else:
                stage(path,previous,'pending',reason)
                normal.update(evolution_note='复用了已保存候选，没有重复成长。'+reason,validation_state='pending');return normal
        candidate=propose(statement,sig,intent);normal['model_calls']=2
        if not isinstance(candidate,dict):raise ValueError('候选格式无效')
        ident=uuid.uuid4().hex
        rec={'id':ident,'created':time.time(),'model':'haiku','source_request':statement,'signature':sig,
             'candidate':candidate,'stable_untouched':True,'validation':None,'contract':intent}
        path=STORE/'candidates'/(ident+'.json');stage(path,rec,'candidate','模型提出隔离候选；尚未启用')
        if not allowed:
            try:rec['static_validation']=sandbox({'mode':'inspect','candidate':candidate})
            except Exception:
                stage(path,rec,'failed','隔离静态检查失败')
                normal.update(evolution_note='候选静态检查失败，未启用。',validation_state='failed');return normal
            stage(path,rec,'pending',reason)
            normal.update(evolution_note='候选已静态检查，待验证、未启用。'+reason,validation_state='pending');return normal
        report=validate_publish(rec,path,intent,param)
        if report:
            normal['resume_note']=resume_note
            return attach(normal,report,ident,True,scope,report)
        normal.update(evolution_note=resume_note+'候选未通过独立参考核对，已失败，没有启用。',validation_state='failed')
        return normal


def attach(result,report,ident,new,scope=None,acceptance=None):
    result=dict(result);scope=scope or {'intent':report.get('contract','bubble_sort'),'assumptions':[],'explicit_max_length':100}
    intent=scope.get('intent','bubble_sort');contract=CONTRACTS[intent];acceptance=acceptance or report
    result['stable_uncovered']=result.get('uncovered');assumptions=scope['assumptions']
    defaults=('明确假设：'+'；'.join(assumptions)+'。' if assumptions else '')
    limit_note=('你未提供长度上限，100只是验证边界，不是题面事实。' if scope['explicit_max_length'] is None else '你明确给出的长度上限为'+str(scope['explicit_max_length'])+'。')
    note='以下来自进化版专属库。验证范围：'+contract['scope']+'。'+limit_note+'没有执行你的实际输入。'
    if intent=='bubble_sort':note+='算法时间复杂度O(n²)，更大规模未验证。'
    result.update(uncovered=None,status='evolved',code_files=[{'name':'solution.py','source':report['source']}],code_note=note,
                  evolution_note=result.get('resume_note','')+defaults+('已自动生成测试，'+str(acceptance.get('tests',0))+'组独立参考核对通过，已验证并发布（不是数学证明）。' if new else '已复用验证通过的模板，没有重复生成候选或调用成长模型。')+'版本：'+ident,
                  evolution_version=ident,model_calls=result.get('model_calls',2 if new else 1),assumptions=assumptions,
                  verification_scope={'max_verified_length':100,'order':contract['order'],'input':'int_list','output':contract['output']},
                  validation_state='verified',acceptance={k:acceptance.get(k) for k in ['tests','contract','reference','scope','test_kinds','stdout_limits','input_preserved','returns_new_list']})
    result['inferred']={'schema':[['p','evolved_'+intent]],'answer_type':[['p','int_list' if intent=='bubble_sort' else 'none']]}
    name=general.params_of(result['signature'])[0];result['facts']=[['arg',name,'int_list']]
    result['fact_sources']={'arg':'assumption' if '输入默认按整数数组处理' in assumptions else 'explicit','size':'unspecified' if scope['explicit_max_length'] is None else 'explicit'}
    if scope['explicit_max_length'] is not None:result['facts'].append(['size',name,general.size_class(scope['explicit_max_length'])])
    from reasoner_human import describe
    result['answer']=describe(result)
    return result


def mark_cancelled():
    if not CURRENT:return
    path,rec=CURRENT
    with open(STORE/'request.lock','a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return
        if path.exists():rec=json.loads(path.read_text())
        if not any((STORE/folder/(rec['id']+'.json')).exists() for folder in ['versions','limited']) and rec.get('status') not in {'failed','pending'}:
            stage(path,rec,'failed','请求已取消；候选未启用')


def evolve(payload):
    from general_evolution import run
    return run(payload)
