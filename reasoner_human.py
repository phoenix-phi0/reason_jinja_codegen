"""Deterministic Chinese presentation of engine evidence; never invent numerical answers."""
KINDS={'int_list':'整数数组','int':'整数','string':'字符串','grid':'网格','string_list':'字符串列表','interval_list':'区间列表','int_matrix':'整数矩阵','op_list':'操作序列'}
AGG={'sum':'求和','count':'计数','product':'求积','max':'取最大值','min':'取最小值','list':'收集结果','join':'拼接字符串','distinct_count':'统计不同值个数'}
KEEP={'positive':'严格大于 0 的元素','negative':'严格小于 0 的元素','nonnegative':'大于等于 0 的元素','even':'偶数','odd':'奇数','nonzero':'非零元素'}
ASK={'min_count':'最少需要多少个物品','count_ways':'共有多少种组合方式','feasible':'能否凑成目标','count_components':'连通块数量','largest_component':'最大连通块大小','shortest_path':'最短路径长度','merge_intervals':'合并区间','max_overlap':'最大重叠数','covered_length':'覆盖总长度','overlap_pairs':'重叠区间对数'}
SCHEMAS={'evolved_print_each':'保持原顺序逐元素逐行打印（进化版独立库）','evolved_bubble_sort':'整数数组升序冒泡排序（进化版独立库）','seq_fold':'逐项筛选、变换后汇总','grid_components':'网格连通性分析','grid_bfs':'网格最短路径搜索','knapsack':'背包／凑数动态规划','interval_scan':'区间扫描'}
CONDS={'positive':'元素均为正数','distinct':'元素互不相同','nonnegative':'元素均非负','sorted':'输入已排序'}
SIZES={'tiny':'不超过 100','small':'不超过 1000','medium':'不超过 10 万','large':'不超过 100 万','huge':'不超过 1000 万','vast':'超过 1000 万'}

def describe(result):
    if result.get('workflow')=='general_code':
        return result.get('human_answer','本轮通用候选尚未形成可读结论，请查看验证状态。')
    facts=result.get('facts',[])
    inferred=result.get('inferred',{})
    if not isinstance(facts,list) or not isinstance(inferred,dict):raise ValueError('invalid engine result')
    lines=[]
    for f in facts:
        if not isinstance(f,list) or not f:continue
        p,*a=f
        if p=='arg' and len(a)==2:lines.append(f'输入 {a[0]} 是{KINDS.get(a[1],"题目指定类型的数据")}。')
        elif p=='iterate' and len(a)==1:lines.append(f'处理 {a[0]} 中的元素。')
        elif p=='keep' and len(a)==1 and a[0] in KEEP:lines.append(f'只保留{KEEP[a[0]]}。')
        elif p=='map' and len(a)==1 and a[0] in {'square','abs','negate','to_int','lower','upper'}:lines.append('对保留元素执行：'+{'square':'平方','abs':'取绝对值','negate':'取相反数','to_int':'转为整数','lower':'转小写','upper':'转大写'}[a[0]]+'。')
        elif p=='aggregate' and len(a)==1 and a[0] in AGG:lines.append(f'目标是{AGG[a[0]]}。')
        elif p=='ask' and len(a)==1 and a[0] in ASK:lines.append(f'需要判断／计算：{ASK[a[0]]}。')
        elif p=='items' and len(a)==1:lines.append(f'{a[0]} 提供可选择的物品数值。')
        elif p=='target' and len(a)==1:lines.append(f'目标总数由 {a[0]} 给出。')
        elif p=='size' and len(a)==2 and a[1] in SIZES:lines.append(f'{a[0]} 的规模{SIZES[a[1]]}。')
        elif p=='guarantees' and len(a)==2 and a[1] in CONDS:lines.append(f'题目保证 {a[0]}：{CONDS[a[1]]}。')
    understood='\n'.join('• '+s for s in dict.fromkeys(lines)) or '目前尚未提取到能明确理解的题目条件。'
    errors=inferred.get('error',[])
    schemas=inferred.get('schema',[])
    blocked=bool(errors)
    if blocked:
        answer='目前还不能给出可靠的解题方案，需要先解决以下条件问题。'
    elif result.get('uncovered'):
        answer='这道题有一部分超出了当前推理机能表达的范围，我还不能完整处理。'
    elif schemas:
        methods=list(dict.fromkeys(SCHEMAS.get(r[-1],'已匹配的算法方案（名称见详情）') for r in schemas if r))
        answer='根据这些条件，引擎支持的处理方式是：'+'；'.join(methods)+'。'
    else:
        answer='目前还没有推导出可用的解题方案，请继续补充条件。'
    extra=[]
    if schemas and not blocked:
        types={'none':'无返回值（None）','int':'整数','bool':'是／否','string':'字符串','int_list':'整数列表','string_list':'字符串列表','list_of_lists':'嵌套列表'}
        ts=list(dict.fromkeys(types[r[-1]] for r in inferred.get('answer_type',[]) if r and r[-1] in types))
        if ts:extra.append('引擎推导出的答案类型是：'+'、'.join(ts)+'。')
    for row in inferred.get('unmet',[]):
        cond=CONDS.get(row[-1], '其他必要的输入保证（见详情）') if row else '必要的输入保证'
        extra.append('请补充确认：是否保证'+cond+'？未确认前不能采用该方案。')
    for row in errors:
        kind=row[0] if row else ''
        if kind=='too_slow':extra.append('当前方案在给定规模下可能太慢；请确认规模，或调整问题要求。')
        elif kind=='two_sizes':extra.append('规模条件互相冲突，请确认以哪个上限为准。')
        elif kind=='unmet_precondition':
            if not inferred.get('unmet'):extra.append('缺少算法所需的输入保证，请补充前提。')
        else:extra.append('引擎发现条件冲突或不支持的组合，请核对题目条件；具体证据在详情中。')
    if not schemas:
        preds={f[0] for f in facts if isinstance(f,list) and f}
        if 'arg' not in preds:extra.append('请说明每个输入参数的类型与含义。')
        if not preds.intersection({'aggregate','ask','fold','select_rank'}):extra.append('请说明最终要计算什么，以及期望的输出形式。')
        extra.append('请补充完整题意、输入规模和必要保证；最接近规则的缺失条件可在详情中查看。')
    if not any(isinstance(f,list) and f and f[0]=='size' for f in facts):extra.append('尚未给出明确规模上限，不能据此保证效率可行。')
    if result.get('uncovered'):
        extra.append('尚未覆盖的部分：'+str(result['uncovered']))
        extra.append('如果你是在更换题目，请点“换题”，或以“换题”开头发送完整题目；不会删除旧消息。')
    extra.append('本轮没有对你的实际输入执行解题代码，因此没有计算具体数值答案。模型转译可能有误，请核对以上理解。')
    if result.get('evolution_note'):answer=result['evolution_note']+'\n\n'+answer
    if result.get('context_note'):answer=result['context_note']+'\n\n'+answer
    return answer+'\n\n我对题目和条件的理解：\n'+understood+'\n\n'+'\n'.join(dict.fromkeys(extra))
