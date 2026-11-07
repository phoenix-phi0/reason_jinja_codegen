"""Conversation-only scoping; no rule or library changes."""
import re

START=re.compile(r'^\s*(?:换题|新题|重新开始|替换旧题)(?:[：:\n\s]+|$)')
SIG=re.compile(r'^\s*(solve\([^\n]*\))\s*(?:\n|$)')
FOLLOW=re.compile(r'^\s*(?:补充|另外|继续|只|还|保持|在此|改为|改成|修正|更正|撤销|取消|不再|不要)')

def scoped(history,message,signature):
    text=message.strip()
    marker=START.match(text)
    explicit=marker is not None
    if marker:text=text[marker.end():].strip()
    sig=SIG.match(text)
    body=text[sig.end():].strip() if sig else text
    complete=bool(not FOLLOW.match(body) and re.search(r'整数数组|字符串|矩阵|网格|给定|输入',body)
                  and re.search(r'求|返回|计算|判断|统计|生成|排序',body))
    replace=bool(history and (explicit or complete))
    if explicit and not body:raise ValueError('请在“换题”后输入完整新题目，旧上下文尚未更改')
    new_signature=sig.group(1) if sig else signature
    if history and new_signature!=signature and not replace:
        raise ValueError('参数签名变了；请点“换题”，或在消息首行写“换题”后重发完整题目')
    active=[] if replace else list(history)
    active.append(text)
    mode='replace' if replace else 'continue'
    note=('已识别明确换题，旧题不再参与本轮；历史仍保留。' if explicit else '检测到完整的新题描述，已替换旧题范围；历史仍保留。') if replace else '沿用当前题目；最新补充、修正和撤销要求优先生效。'
    return active,new_signature,mode,note

HINT='''
Conversation scope rules: this is a sequence of revisions of ONE ACTIVE requirement, not a list of independent tasks to satisfy together. Later explicit corrections, cancellations and withdrawals replace the corresponding earlier requirements. Extract facts for the final active requirement only. The uncovered field must mention ONLY still-active unsupported aspects, never a cancelled or superseded historical request. Do not drop still-active constraints, transforms (such as square), or genuine unsupported requirements. If the intended revision is ambiguous, keep an uncovered note asking the user to use the visible 换题 control with a complete new statement. Do not guess or claim support.'''
