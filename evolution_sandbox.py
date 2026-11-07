"""Trusted harness, run only inside bwrap. Candidate code is never imported on host."""
import ast,json,os,random,sys
sys.path.insert(0,'/input')
from datalog import Datalog,parse_rules
from evolution_contracts import CONTRACTS,reference

RULE='evolved(P,bubble_sort) :- intent(P,bubble_sort), order(P,ascending), input(P,int_list).'
ALLOWED_CALLS={'list','len','range'}
FORBIDDEN=(ast.Import,ast.ImportFrom,ast.Attribute,ast.With,ast.AsyncWith,ast.ClassDef,ast.Lambda,ast.Global,ast.Nonlocal,ast.Try,ast.Raise,ast.Delete,ast.Yield,ast.YieldFrom,ast.Await)

def render(candidate,param,intent=None):
    intent=intent or candidate.get('intent')
    contract=CONTRACTS.get(intent)
    if not contract:raise ValueError('no independent verifier for this candidate')
    if candidate.get('intent')!=intent or candidate.get('rule','').strip()!=contract['rule'] or candidate.get('vocabulary')!=contract['vocabulary']:
        raise ValueError('candidate does not match requested contract')
    allowed_calls=set(contract['calls'])
    d=Datalog(parse_rules(candidate['rule']))
    for pred,value in contract['facts'].items():d.add(pred,'p',value)
    d.run()
    if ('p',intent) not in d.db.get('evolved',set()):raise ValueError('rule did not select candidate')
    src=candidate['source']
    if not isinstance(src,str) or len(src)>20000:raise ValueError('source too large')
    t=ast.parse(src)
    if len(t.body)!=1 or not isinstance(t.body[0],ast.FunctionDef):raise ValueError('one solve function required')
    fn=t.body[0]
    if fn.name!='solve' or len(fn.args.args)!=1 or fn.decorator_list or fn.returns or fn.args.defaults or fn.args.kwonlyargs or fn.args.vararg or fn.args.kwarg:raise ValueError('bad signature')
    if fn.args.args[0].annotation:raise ValueError('annotations disabled')
    old=fn.args.args[0].arg
    for n in ast.walk(t):
        if isinstance(n,FORBIDDEN):raise ValueError('forbidden syntax')
        if isinstance(n,ast.FunctionDef) and n is not fn:raise ValueError('nested function')
        if isinstance(n,ast.Name) and n.id.startswith('_'):raise ValueError('private name')
        if isinstance(n,ast.Call) and (not isinstance(n.func,ast.Name) or n.func.id not in allowed_calls):raise ValueError('call not allowed')
    if sum(isinstance(n,(ast.For,ast.While)) for n in ast.walk(fn))<contract['min_loops']:raise ValueError('required traversal loops missing')
    for n in ast.walk(fn):
        if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='print' and n.keywords:raise ValueError('print options outside contract')
    adjacent_swap=False
    for n in ast.walk(fn):
        if not isinstance(n,ast.Assign) or len(n.targets)!=1 or not isinstance(n.targets[0],ast.Tuple) or not isinstance(n.value,ast.Tuple):continue
        targets=n.targets[0].elts;values=n.value.elts
        if len(targets)!=2 or len(values)!=2 or not all(isinstance(x,ast.Subscript) for x in targets+values):continue
        a,b=targets
        if ast.dump(a.value)!=ast.dump(b.value):continue
        j=a.slice;k=b.slice
        if not (isinstance(j,ast.Name) and isinstance(k,ast.BinOp) and isinstance(k.op,ast.Add) and isinstance(k.left,ast.Name) and k.left.id==j.id and isinstance(k.right,ast.Constant) and k.right.value==1):continue
        # Compare without Store/Load contexts.
        if ast.unparse(a)==ast.unparse(values[1]) and ast.unparse(b)==ast.unparse(values[0]):adjacent_swap=True
    if contract['adjacent_swap'] and not adjacent_swap:raise ValueError('adjacent tuple swap required')
    # Canonical parameter is mapped structurally, not via Jinja or string evaluation.
    if not param.isidentifier() or param.startswith('_') or param in allowed_calls:raise ValueError('bad output parameter')
    # Avoid capturing an existing local variable when renaming the public parameter.
    names={n.id for n in ast.walk(t) if isinstance(n,ast.Name)}
    if param!=old and any(isinstance(n,ast.Name) and isinstance(n.ctx,ast.Store) and n.id==param for n in ast.walk(t)):
        local='evo_local_1'
        while local in names:local+='x'
        for n in ast.walk(t):
            if isinstance(n,ast.Name) and n.id==param:n.id=local
    for n in ast.walk(t):
        if isinstance(n,ast.Name) and n.id==old:n.id=param
    fn.args.args[0].arg=param
    ast.fix_missing_locations(t)
    return t,ast.unparse(t)+'\n'

def main():
    payload=json.load(open('/input/request.json'))
    if payload.get('mode','').startswith('general_'):
        from general_candidate_sandbox import process
        print(json.dumps(process(payload),ensure_ascii=False));return
    if payload.get('mode')=='probe':
        import socket
        assert not os.path.exists('/home/box') and not os.environ.get('GH_TOKEN')
        try:socket.create_connection(('1.1.1.1',443),timeout=.2);raise AssertionError('network reachable')
        except OSError:pass
        try:open('/usr/EVOLUTION_WRITE_TEST','w');raise AssertionError('root writable')
        except OSError:pass
        print(json.dumps({'isolated':True}));return
    if payload.get('mode')=='inspect':
        candidate=payload['candidate']
        source=candidate.get('source','')
        if not isinstance(source,str) or len(source)>20000:raise ValueError('too large')
        ast.parse(source)
        parse_rules(candidate.get('rule',''))
        print(json.dumps({'static_ok':True,'executed':False}));return
    intent=payload.get('contract') or payload['candidate'].get('intent')
    contract=CONTRACTS[intent]
    t,source=render(payload['candidate'],payload.get('param','nums'),intent)
    count=0
    if payload.get('mode')=='validate':
        class Capture:
            def __init__(self):self.parts=[];self.bytes=0;self.lines=0
            def emit(self,*args):
                text=' '.join(str(x) for x in args)+'\n'
                self.bytes+=len(text.encode('utf-8'));self.lines+=text.count('\n')
                if self.bytes>16384 or self.lines>128:raise ValueError('stdout limit')
                self.parts.append(text)
        capture=Capture()
        safe={'list':list,'len':len,'range':range}
        if 'print' in contract['calls']:safe['print']=capture.emit
        ns={'__builtins__':safe}
        exec(compile(t,'candidate.py','exec'),ns)
        rng=random.Random(78123)
        cases=[[],[0],[1,-1,1],[3,2,1],list(range(100,0,-1))]
        cases += [[rng.randrange(-100,101) for _ in range(rng.randrange(101))] for _ in range(75)]
        for a in cases:
            capture.parts=[];capture.bytes=0;capture.lines=0
            args=list(a);actual=ns['solve'](args)
            expected,stdout=reference(intent,a)
            output=''.join(capture.parts)
            if type(actual) is not type(expected) or actual!=expected or output!=stdout:
                raise ValueError('independent reference mismatch')
            if args!=a:raise ValueError('candidate mutated input')
            if intent=='bubble_sort' and actual is args:raise ValueError('sorting must return a new list')
            count+=1
    print(json.dumps({'source':source,'tests':count,'rule_selected':True,'checks':'finite independent contract tests, not proof','contract':intent,'reference':contract['reference'],'scope':contract['scope'],'test_kinds':['empty','singleton','duplicates','negative','preserved_order','boundary_100','seeded_random'],'stdout_limits':{'bytes':16384,'lines':128},'input_preserved':True,'returns_new_list':intent=='bubble_sort','sandbox':'bwrap user/pid/net namespaces; read-only runtime; empty environment; resource limits'}))

if __name__=='__main__':
    try:main()
    except Exception:print(json.dumps({'error':'候选未通过隔离语法、规则或独立测试验证'}));sys.exit(1)
