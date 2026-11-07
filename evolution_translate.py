"""One model call translates stable facts AND the actual validated extension catalog."""
import json,subprocess,tempfile
import general
from evolution_contracts import CONTRACTS

def translator(catalog,state):
    def extract(problem,model,voc,hint=''):
        prompt=general.PROMPT.format(vocab=general.describe_vocab(voc),signature=problem['signature'],statement=problem['statement'],params=general.params_of(problem['signature']),hint=hint)
        prompt+='''\nEvolution routing (same call, not a second task): the following catalog is separate from the stable vocabulary. Published extensions are genuinely available, so do NOT reject their operation merely because stable facts cannot express it. Still identify explicit incompatible requirements; never replace descending/floats/objects/additional outputs with ascending integer sort.
Validated catalog: '''+json.dumps(catalog,ensure_ascii=False)+'''
Available independent contracts (not yet published abilities): '''+json.dumps({k:{'label':v['label'],'scope':v['scope'],'order':v['order'],'output':v['output']} for k,v in CONTRACTS.items()},ensure_ascii=False)+'''
The independent verifier knows bubble_sort: one integer-list parameter, ascending return-list, finite verification through length 100. Classify the FINAL active request semantically, even colloquial requests like 帮我做个冒泡算法 or 生成冒泡排序代码. Do not choose bubble sort merely because the user asks for sorting, or if they explicitly request another algorithm.
Return the usual facts/uncovered plus REQUIRED "extension": {"intent":"bubble_sort"|"print_each"|"other"|"ambiguous", "input_type":"int_list"|"float_list"|"objects"|"unspecified"|"other", "order":"ascending"|"descending"|"preserve"|"unspecified"|"other", "output":"return_list"|"stdout_lines"|"unspecified"|"other", "active_scope":"continue"|"replace"|"ambiguous", "max_length":integer_or_null, "extra_requirements":[strings]}. Use unspecified/null for omissions: defaults are NOT user facts. max_length is only the user's explicit upper bound, never the catalog's verification boundary. For a bare bubble algorithm request use intent=bubble_sort, unspecified type/order, null length, no extras; the application will visibly state defaults. List every still-active additional condition (in-place, steps, swap count, custom comparator, filtering, etc.) in extra_requirements; ordinary return sorted array is not extra. Other/ambiguous intent must never be silently mapped to bubble sort. For 遍历数组并打印/逐个输出 use print_each, order=preserve, output=stdout_lines (when layout omitted use unspecified so defaults are visible). Printing stdout is not returning a list/string; do not mis-map it to stable aggregate/list/join. A new standalone request like 帮我写个遍历数组并打印的方法 replaces an earlier separate bubble-sort request: active_scope=replace, interpret stable facts and extension ONLY for the new request. Explicit supplements or combined requirements must remain and appear in extra_requirements if unsupported. Stable-supported questions may use intent=other. No tools, code execution, or new code. Reply JSON only.'''
        p=subprocess.run(['claude','-p','--model',model,'--tools','','--no-session-persistence','--strict-mcp-config'],input=prompt,capture_output=True,text=True,timeout=300,cwd=tempfile.gettempdir())
        if p.returncode:raise ValueError('translator failed')
        obj=general.first_json_object(p.stdout)
        state['extension']=obj.get('extension')
        norm=lambda x:str(x) if isinstance(x,(int,float)) and not isinstance(x,bool) else x
        facts=[[norm(x) for x in row] if isinstance(row,list) else row for row in obj.get('facts',[])]
        return facts,obj.get('uncovered')
    return extract
