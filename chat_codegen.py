"""Read-only generation adapter: existing facts/rules/Jinja pipeline, never exec/eval."""
import ast
import re
import tempfile
from pathlib import Path
import general

SIGNATURE=re.compile(r'solve\(\s*[A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*\s*\)',re.ASCII)

def add_code(result, signature=None, historical=False):
    """Attach generated source in memory. Refuse ambiguous/incomplete/blocked results."""
    if 'code_files' in result or 'code_note' in result:
        return result
    signature=signature or result.get('signature')
    if not isinstance(signature,str) or not SIGNATURE.fullmatch(signature):
        result['code_note']='这一轮未保存完整参数签名，无法可靠还原代码；请重新发送题目或生成请求。'
        return result
    facts=result.get('facts');inferred=result.get('inferred',{})
    if not isinstance(facts,list) or not isinstance(inferred,dict):
        result['code_note']='旧轮数据不足，无法可靠还原代码；请再发送一条生成请求。'
        return result
    if result.get('uncovered') or inferred.get('error') or not inferred.get('schema'):
        result['code_note']='当前题意未完整覆盖、存在规则阻断或尚未匹配模板，因此不生成代码；请先补全上面提示的条件。'
        return result
    params=general.params_of(signature)
    if len(params)>12 or len(set(params))!=len(params) or general.validate(facts,params,general.vocab()):
        result['code_note']='结构化事实与参数签名不一致，不能安全生成；请重新发送题目。'
        return result
    problem={'id':'chat','signature':signature,'statement':'','tests':[]}
    try:
        # Same pipeline used by general.build, but a managed temporary directory
        # also cleans up failed generations. generate performs AST/compile checks,
        # never executes the generated code. No evaluate/run_tests/growth calls.
        with tempfile.TemporaryDirectory(prefix='chat_codegen_') as tmp:
            paths=general.generate({'facts':general.grouped_facts(problem,facts),
                                    'data':{general.KEY:{'params':params}}},Path(tmp),general.PACK)
            files=[]
            for relative in paths:
                source=(Path(tmp)/relative).read_text()
                tree=ast.parse(source)
                solve=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name=='solve']
                if relative=='solution.py' and (len(solve)!=1 or [a.arg for a in solve[0].args.args]!=params):
                    raise ValueError('signature mismatch')
                files.append({'name':relative,'source':source})
            if not files:raise ValueError('no source')
        result['signature']=signature
        result['code_files']=files
        result['code_note']=('以下代码由保存的事实按当前规则与模板重新生成；' if historical else '以下完整代码由引擎实际选择的模板生成；')+'只做静态语法检查，未执行或验证运行结果。'
    except Exception as exc:
        # Missing templates, conflicting emits, rule rejection and static errors
        # are not substituted with model-written or hand-written fallback code.
        reason='现有规则／模板未能生成通过静态检查的完整代码'
        detail=str(exc)
        if type(exc).__name__ in {'TemplateNotFound','TemplatesNotFound'}:reason='引擎选中的模板文件不存在'
        elif isinstance(exc,SyntaxError):reason='模板产物未通过 Python 静态语法检查'
        elif 'too_slow' in detail:reason='当前规模下没有满足效率约束的候选算法'
        elif 'unmet_precondition' in detail:reason='缺少候选算法要求的前提保证'
        elif 'two_choices' in detail or 'Duplicate' in detail:reason='多个候选生成计划发生冲突，不能擅自选择其中一个'
        elif 'no_schema' in detail or 'No emit' in detail:reason='引擎没有推导出可用的代码生成模板'
        result['code_note']=reason+'；没有使用伪代码替代。请补充条件或重新发送题目。'
    return result


def code_text(result):
    text='\n\n'+result.get('code_note','本轮未保存代码，请再发送一条生成请求。')
    for f in result.get('code_files',[]):
        if isinstance(f,dict) and isinstance(f.get('source'),str):
            text+='\n\n'+str(f.get('name','Python 代码'))+'\n```python\n'+f['source'].rstrip()+'\n```'
    return text
