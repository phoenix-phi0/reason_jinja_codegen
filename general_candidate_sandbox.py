"""Trusted general-function runner, imported only inside the isolated bwrap process."""
import ast,copy,json,math
CALLS={'abs','all','any','bool','dict','divmod','enumerate','float','int','isinstance','len','list','max','min','pow','range','reversed','round','set','sorted','str','sum','tuple','zip','print'}
METHODS={'append','extend','pop','get','items','keys','values','lower','upper','strip','lstrip','rstrip','split','join','replace','count','index','startswith','endswith','copy','sort','reverse','add','discard'}
BANNED=(ast.Import,ast.ImportFrom,ast.ClassDef,ast.With,ast.AsyncWith,ast.AsyncFunctionDef,ast.Global,ast.Nonlocal,ast.Lambda,ast.Await,ast.Yield,ast.YieldFrom)

def process(p):
    source=p.get('source','');params=p.get('params',[])
    if not isinstance(source,str) or len(source)>20000:return {'safe':False,'failure_kind':'syntax','reason':'代码为空或超过20000字符'}
    try:t=ast.parse(source)
    except SyntaxError as e:return {'safe':False,'failure_kind':'syntax','reason':f'Python语法错误，第{e.lineno}行'}
    functions=[n for n in t.body if isinstance(n,ast.FunctionDef)]
    if len(functions)!=len(t.body) or not functions:return {'safe':False,'failure_kind':'unsafe','reason':'只允许顶层纯函数定义'}
    names={n.name for n in functions}
    solves=[n for n in functions if n.name=='solve']
    if len(solves)!=1 or [a.arg for a in solves[0].args.args]!=params:return {'safe':False,'failure_kind':'signature','reason':'候选签名与需求契约不一致'}
    for n in ast.walk(t):
        if isinstance(n,BANNED):return {'safe':False,'failure_kind':'unsafe','reason':'导入、类、动态作用域或外部I/O不在自动执行范围'}
        if isinstance(n,ast.Name) and n.id.startswith('_'):return {'safe':False,'failure_kind':'unsafe','reason':'禁止私有/反射名称'}
        if isinstance(n,ast.Attribute) and n.attr not in METHODS:return {'safe':False,'failure_kind':'unsafe','reason':'方法不在受限纯数据操作白名单'}
        if isinstance(n,ast.FunctionDef):
            if n.name.startswith('_') or n.decorator_list or n.returns or n.args.defaults or n.args.kw_defaults or n.args.vararg or n.args.kwarg or n.args.kwonlyargs or any(a.annotation for a in n.args.args):
                return {'safe':False,'failure_kind':'unsafe','reason':'函数需无装饰器、注解、默认表达式或可变参数'}
        if isinstance(n,ast.Call):
            if isinstance(n.func,ast.Name):
                if n.func.id not in CALLS|names:return {'safe':False,'failure_kind':'unsafe','reason':'禁止未知函数或系统调用'}
                if n.func.id=='print' and any(k.arg not in {'sep','end'} for k in n.keywords):return {'safe':False,'failure_kind':'unsafe','reason':'print只能写受控捕获器'}
            elif not isinstance(n.func,ast.Attribute):return {'safe':False,'failure_kind':'unsafe','reason':'禁止动态函数目标'}
    canonical=ast.unparse(t)+'\n'
    if p.get('mode')=='general_inspect':return {'safe':True,'executed':False,'source':canonical,'params':params}
    tests=p.get('tests',[])
    if not tests or len(tests)>32:return {'safe':True,'passed':False,'failure_kind':'no_tests','reason':'没有有效测试或超过32组上限','source':canonical}
    class Capture:
        def __init__(self):self.text='';self.bytes=0;self.lines=0
        def emit(self,*args,sep=' ',end='\n'):
            if not isinstance(sep,str) or not isinstance(end,str):raise ValueError('print格式无效')
            text=sep.join(str(x) for x in args)+end
            self.bytes+=len(text.encode());self.lines+=text.count('\n')
            if self.bytes>8192 or self.lines>128:raise ValueError('stdout超限')
            self.text+=text
    cap=Capture()
    import builtins
    safe={name:getattr(builtins,name) for name in CALLS if name!='print'};safe['print']=cap.emit
    ns={'__builtins__':safe}
    try:exec(compile(t,'candidate.py','exec'),ns)
    except Exception:return {'safe':False,'failure_kind':'runtime','reason':'函数定义失败'}
    failures=[];passed=0;properties=p.get('properties',[])
    for i,test in enumerate(tests):
        cap.text='';cap.bytes=0;cap.lines=0
        args=copy.deepcopy(test['args']);before=copy.deepcopy(args)
        try:
            actual=ns['solve'](*args)
            # Bound the receipt and exclude non-JSON objects/nonfinite values.
            encoded=json.dumps(actual,ensure_ascii=False,allow_nan=False)
            if len(encoded)>8192:raise ValueError('返回值超限')
            checks=[]
            if 'expected' in test:checks.append(type(actual) is type(test['expected']) and actual==test['expected'])
            checks.append(cap.text==test.get('stdout',''))
            if 'preserves_input' in properties:checks.append(args==before)
            if 'deterministic' in properties:
                stdout=cap.text;cap.text='';cap.bytes=0;cap.lines=0
                again=ns['solve'](*copy.deepcopy(before))
                checks.append(type(again) is type(actual) and again==actual and cap.text==stdout)
            if not all(checks):
                failures.append({'case':i,'args':before,'expected':test.get('expected'),'actual':actual,'actual_type':type(actual).__name__,'expected_type':type(test.get('expected')).__name__,'expected_stdout':test.get('stdout','')[:256],'actual_stdout':cap.text[:256]})
            else:passed+=1
        except Exception as e:
            failures.append({'case':i,'args':before,'error':type(e).__name__,'reason':str(e)[:120]})
    return {'safe':True,'executed':True,'passed':not failures,'passed_count':passed,'total':len(tests),'failures':failures[:3],
            'source':canonical,'params':params,'properties_checked':[x for x in properties if x in {'deterministic','preserves_input'}],
            'stdout_limits':{'bytes':8192,'lines':128},'semantic_proof':False}
