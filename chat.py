"""Loopback-only, read-only Datalog conversation UI; no generated code execution."""
import argparse
import json
import re
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import general
from reasoner_human import describe
from chat_codegen import add_code
from chat_scope import scoped, HINT

MAX_TEXT = 6000

class Chat:
    def __init__(self, model='haiku', translator=None):
        self.model = model
        self.translator = translator
        self.sessions = {}
        self.lock = threading.Lock()
        self.worker = threading.Lock()

    def session(self, sid):
        with self.lock:
            if sid not in self.sessions:
                raise ValueError('会话已失效，请刷新页面')
            return self.sessions[sid]

    def create(self):
        with self.lock:
            # Bound memory; only expire idle sessions, never an in-flight request.
            now = time.monotonic()
            for k, s in list(self.sessions.items()):
                if now-s['touched'] > 3600 and not s['lock'].locked():
                    del self.sessions[k]
            if len(self.sessions) >= 100:
                raise ValueError('会话数量已达上限，请稍后再试')
            sid = secrets.token_urlsafe(32)
            self.sessions[sid] = dict(history=[], lock=threading.Lock(), touched=now)
            return sid

    def reset(self, sid):
        s = self.session(sid)
        if not s['lock'].acquire(False):
            raise BlockingIOError('当前会话忙碌，请等待完成后清空')
        try:
            s['history'] = []
            s['touched'] = time.monotonic()
        finally:
            s['lock'].release()
        return {'history': []}

    def ask(self, sid, message, signature):
        if not isinstance(message, str) or not message.strip() or len(message)>MAX_TEXT:
            raise ValueError('请输入 1–6000 字符的问题')
        if not isinstance(signature, str) or not re.fullmatch(r'solve\(\s*[A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*\s*\)', signature, re.ASCII):
            raise ValueError('输入签名格式为 solve(nums) 或 solve(coins, target)')
        params = general.params_of(signature)
        if len(params)>12 or len(set(params)) != len(params):
            raise ValueError('参数需唯一且不超过 12 个')
        s = self.session(sid)
        if not s['lock'].acquire(False):
            raise BlockingIOError('当前会话忙碌')
        acquired = False
        try:
            history, signature, mode, scope_note = scoped(s['history'], message, signature)
            if s['history'] and s['signature'] != signature and mode!='replace':
                raise ValueError('更换参数前请明确换题')
            if not re.fullmatch(r'solve\(\s*[A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*\s*\)',signature,re.ASCII):
                raise ValueError('签名格式无效')
            params = general.params_of(signature)
            if len(set(params))!=len(params) or len(params)>12:raise ValueError('参数无效')
            if len(history)>20 or sum(map(len,history))>18000:
                raise ValueError('上下文已达上限，请清空后开始新问题')
            acquired = self.worker.acquire(False)
            if not acquired:
                raise BlockingIOError('推理服务忙碌，请稍后重试')
            problem = {'id':'chat', 'signature':signature, 'statement':
                       '以下是同一题目的多轮说明，后续说明可修正之前条件。只提取明确给出的事实；不要猜测缺失前提。\n'+
                       '\n'.join(f'第{i+1}轮：{m}' for i,m in enumerate(history)), 'tests':[]}
            # Exactly one existing translator call per turn. No learning/build/evaluate.
            try:
                facts, uncovered = (self.translator or general.extract)(problem, self.model, general.vocab(), hint=HINT)
                if not isinstance(facts,list) or len(facts)>200:
                    raise ValueError('invalid facts')
                bad = general.validate(facts, params, general.vocab())
                if bad:
                    raise ValueError('invalid facts')
            except Exception:
                # Never return CLI stderr/stdout: may contain sensitive diagnostics.
                raise RuntimeError('模型翻译失败或返回了无效事实；上下文未更新，请重试') from None
            try:
                d = general.engine_for(problem, facts)
                explanation, _ = general.explain(problem, facts)
                selected = {p: [list(r) for r in sorted(rows)] for p,rows in d.db.items()
                            if p in {'schema','uses','answer_type','error','why_slow','unmet','candidate','size','guarantees'}}
            except Exception:
                raise RuntimeError('引擎无法处理本轮事实；上下文未更新') from None
            result = dict(status=('blocked' if d.db.get('error') else 'uncovered' if uncovered else 'inferred' if d.db.get('schema') else 'needs_conditions'),
                          facts=facts, inferred=selected, explanation=explanation,
                          uncovered=uncovered if isinstance(uncovered,str) else None,
                          note='模型只翻译事实；下列结论来自 Datalog。未执行生成代码、未自动成长。规模未给出时不保证可行性。')
            result['context_mode'] = mode
            result['context_note'] = scope_note
            result['signature'] = signature
            add_code(result, signature)
            result['answer'] = describe(result)
            s.update(history=history, signature=signature, touched=time.monotonic())
            return dict(history=history, result=result)
        finally:
            if acquired: self.worker.release()
            s['lock'].release()

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # No conversation text or session IDs in logs.

    def reply(self, status, body, content='application/json; charset=utf-8'):
        data = body.encode() if isinstance(body,str) else json.dumps(body,ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type',content)
        self.send_header('Content-Length',str(len(data)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.end_headers(); self.wfile.write(data)

    def allowed(self):
        host = self.headers.get('Host','')
        port = self.server.server_port
        return host in {f'127.0.0.1:{port}', f'localhost:{port}'} and self.headers.get('Origin',f'http://{host}') == f'http://{host}'

    def do_GET(self):
        if not self.allowed(): return self.reply(403, {'error':'仅允许同源本地访问'})
        assets = {'/':('chat.html','text/html; charset=utf-8'), '/chat.js':('chat.js','text/javascript; charset=utf-8')}
        if self.path not in assets: return self.reply(404, {'error':'not found'})
        name, content = assets[self.path]
        self.reply(200, Path(__file__).with_name(name).read_text(),content)

    def do_POST(self):
        if not self.allowed(): return self.reply(403, {'error':'仅允许同源本地访问'})
        try:
            if self.headers.get('Content-Type') != 'application/json': raise ValueError('需要 JSON 请求')
            n = int(self.headers.get('Content-Length','0'))
            if not 0<n<=32000: raise ValueError('请求过大或为空')
            data = json.loads(self.rfile.read(n))
            if not isinstance(data,dict): raise ValueError('请求必须是对象')
            chat = self.server.chat
            if self.path == '/api/session': result={'session':chat.create()}
            elif self.path == '/api/reset': result=chat.reset(data.get('session'))
            elif self.path == '/api/ask': result=chat.ask(data.get('session'),data.get('message'),data.get('signature'))
            else: return self.reply(404,{'error':'not found'})
            self.reply(200,result)
        except BlockingIOError as e: self.reply(409,{'error':str(e)})
        except (ValueError,TypeError): self.reply(400,{'error':'输入无效：检查问题长度、参数签名及会话；更换签名需先清空'})
        except RuntimeError as e: self.reply(502,{'error':str(e)})
        except Exception: self.reply(500,{'error':'服务错误；请刷新重试'})

if __name__ == '__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--port',type=int,default=8797)
    ap.add_argument('--model',default='haiku')
    args=ap.parse_args()
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    server.chat=Chat(args.model)
    print(f'http://127.0.0.1:{server.server_port}/',flush=True)
    server.serve_forever()
