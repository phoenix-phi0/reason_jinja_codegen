"""Summarise reports/task9_raw/<config>_<set>_<i>.json: per-problem solved counts, unstable problems, wrong code, calls, seconds."""
import json, sys, collections
from pathlib import Path
raw = Path(__file__).parent / 'reports' / 'task9_raw'
for cfg in sys.argv[1:]:
    for s in ('glm2', 'earlier'):
        files = sorted(raw.glob(f'{cfg}_{s}_*.json'))
        if not files:
            continue
        per, wrong, calls, paths, nsolved = collections.defaultdict(int), 0, 0, collections.Counter(), []
        for f in files:
            log = json.loads(f.read_text())
            nsolved.append(sum(r['status'] == 'solved' for r in log))
            for r in log:
                per[r['id']] += r['status'] == 'solved'
                wrong += r['status'] == 'wrong'
                calls += r.get('model_calls', 0)
                paths[r.get('path', '-')] += 1
        n = len(files)
        unstable = {k: v for k, v in per.items() if 0 < v < n}
        never = [k for k, v in per.items() if v == 0]
        total = len(per)
        print(f'{cfg} {s}: runs={n} problems={total} solved/run={nsolved} unstable={len(unstable)} {unstable} never={never} wrong={wrong} '
              f'calls/problem={calls/(n*total) if calls else "n/a"} paths={dict(paths)}')
