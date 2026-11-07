"""Run one generated module against a test file in a separate, resource-limited process.

Usage: python -I grow_runner.py <module.py> <tests.json> <per_test_seconds>
Prints one JSON line: {"results": [{"ok": bool, "error": str|null, "got": str}...]}
"""
import importlib.util, json, resource, signal, sys


class Timeout(Exception):
    pass


def alarm(*_):
    raise Timeout('timeout')


def main():
    path, tests_path, seconds = sys.argv[1], sys.argv[2], int(sys.argv[3])
    resource.setrlimit(resource.RLIMIT_AS, (2 << 30, 2 << 30))
    sys.setrecursionlimit(100000)
    tests = json.load(open(tests_path))
    out = []
    try:
        spec = importlib.util.spec_from_file_location('candidate', path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        solve = mod.solve
    except BaseException as exc:  # noqa: BLE001
        print(json.dumps({'load_error': f'{type(exc).__name__}: {exc}'[:300]}))
        return
    signal.signal(signal.SIGALRM, alarm)
    for t in tests:
        signal.alarm(seconds)
        try:
            got = json.loads(json.dumps(solve(*json.loads(json.dumps(t['args'])))))
            signal.alarm(0)
            ok = got == t['expected']
            out.append({'ok': ok, 'error': None, 'got': None if ok else repr(got)[:200]})
        except BaseException as exc:  # noqa: BLE001
            signal.alarm(0)
            out.append({'ok': False, 'error': f'{type(exc).__name__}: {exc}'[:200], 'got': None})
    print(json.dumps({'results': out}))


if __name__ == '__main__':
    main()
