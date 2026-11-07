"""Trusted behavior contracts, not editable by candidates. Add an independent oracle to extend."""
CONTRACTS={
 'bubble_sort':{
  'label':'整数数组升序冒泡排序',
  'vocabulary':{'intent':['bubble_sort'],'order':['ascending'],'input':['int_list']},
  'rule':'evolved(P,bubble_sort) :- intent(P,bubble_sort), order(P,ascending), input(P,int_list).',
  'facts':{'intent':'bubble_sort','order':'ascending','input':'int_list'},
  'calls':['list','len','range'], 'min_loops':2,'adjacent_swap':True,
  'order':'ascending','output':'return_list','max_length':100,'test_count':80,
  'reference':'python_sorted_and_no_stdout',
  'scope':'整数数组，升序返回列表，长度≤100，有限测试不是证明'},
 'print_each':{
  'label':'保持原顺序逐元素逐行打印',
  'vocabulary':{'intent':['print_each'],'order':['preserve'],'input':['int_list'],'output':['stdout_lines']},
  'rule':'evolved(P,print_each) :- intent(P,print_each), order(P,preserve), input(P,int_list), output(P,stdout_lines).',
  'facts':{'intent':'print_each','order':'preserve','input':'int_list','output':'stdout_lines'},
  'calls':['list','len','range','print'],'min_loops':1,'adjacent_swap':False,
  'order':'preserve','output':'stdout_lines','max_length':100,'test_count':80,
  'reference':'exact_stdout_lines_and_none_return',
  'scope':'整数数组，顺序与重复保留，每个元素一行，空数组无输出，返回None；长度≤100，测试元素-100到100，有限测试不是证明'}
}

def reference(intent,values):
    """Independent trusted oracle. Candidate never provides expected outputs."""
    if intent=='bubble_sort':return sorted(values),''
    if intent=='print_each':return None,''.join(str(x)+'\n' for x in values)
    raise ValueError('No independent oracle')
