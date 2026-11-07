"""Fixed JSON stdin/stdout adapter for authenticated webchat; no network listener."""
import json
import sys
from chat import Chat

def answer(payload):
    if payload.get('evolution'):
        from evolution import evolve,mark_cancelled
        import signal
        def cancelled(*args):raise SystemExit(143)
        signal.signal(signal.SIGTERM,cancelled)
        try:return evolve(payload)
        except (SystemExit,KeyboardInterrupt):
            mark_cancelled()
            raise
    c=Chat()  # Same haiku default as the standalone UI and general.py.
    sid=c.create()
    history=payload.get('history',[])
    if not isinstance(history,list) or not all(isinstance(x,str) for x in history):
        raise ValueError('invalid history')
    if len(history)>19 or sum(map(len,history))>18000:
        raise ValueError('上下文已达上限，请新建推理机对话')
    c.session(sid).update(history=history, signature=payload['signature'])
    return c.ask(sid,payload['message'],payload['signature'])['result']

if __name__=='__main__':
    try:
        data=sys.stdin.buffer.read(100001)
        if len(data)>100000:raise ValueError('请求过大')
        result=answer(json.loads(data))
        print(json.dumps({'result':result},ensure_ascii=False))
    except Exception as e:
        # Only our sanitized public messages; never echo CLI diagnostics.
        print(json.dumps({'error':str(e) if isinstance(e,(ValueError,RuntimeError)) else '推理失败'},ensure_ascii=False))
        sys.exit(1)
