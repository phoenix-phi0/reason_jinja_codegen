"""Consolidate packs/general: a model refactors vocab.json, learned.dl and the schema templates
into a smaller, more uniform pack and migrates every stored problem's facts. The result is kept
only if every stored problem still passes with its migrated facts and the pack did not grow.

  python general_consolidate.py [--model sonnet] [--max-rounds 3] [--log out.json]
"""
import argparse, json, shutil, tempfile, time
from pathlib import Path

import general
from general_grow import new_lint_errors, LAYERS_NOTE, affected, ask, changes, complexity_regressions, edit_violations, pack_text, reference_compat, regression, solved_dir, update_deps

PACK = general.PACK

PROMPT = """You maintain a code generator. Problems are described by facts from vocab.json; Datalog rules
(rules.dl, learned.dl) derive a schema and its parameters; Jinja schema templates render the Python solution.
{layers}Datalog syntax: one rule per line ending in '.', literals pred(args), not pred(args) (stratified), A != B;
variables start uppercase; constants with uppercase/odd characters go in double quotes; `head(...) :- .` is a fact.
In templates, relations.rows/one/has(pred, key, ...) query derived facts; `params` is the list of argument names.
In vocab.json a value list may contain the placeholders <int>, <char> and <param> (a parameter name).

The pack grew one problem at a time and has become uneven. Current pack:
{pack}

Every problem solved so far, with the facts that describe it:
{problems}

Refactor the pack so it is smaller and more uniform while every problem above keeps working:
- merge predicates where one is a special case of another (keep the more general one);
- merge schemas that are special cases of another schema, adding a parameter if needed;
- remove rules that are dead or duplicated, and use one naming and checking style;
- keep vocab.json documentation clear enough that another model can translate a new statement correctly.
rules.dl and templates/solution.py.j2 cannot be changed, so the base schemas' selection rules stay; you may
change their glue templates, algorithms.dl, learned.dl and vocab.json. Library functions in templates/lib may not be
changed or deleted: merging two schemas must keep calling the same functions. Do not add new capabilities.
Keep the usual optimal complexity of every case: stored problems include large tests with a 10 second limit.
{feedback}
You have no tools: do not try to write files or run commands; put every file's complete content in your reply.
Reply with only JSON:
{{"files": {{"<path>": "<complete new content>", ...}},      // vocab.json, learned.dl, algorithms.dl, templates/schemas/*.py.j2
  "delete": ["templates/schemas/<name>.py.j2", ...],          // schema glue templates merged away (never library functions)
  "facts": {{"<problem id>": [[...], ...], ...}},              // migrated facts for EVERY problem listed above
  "summary": "<what was merged>"}}"""


def size(pack):
    voc = json.loads((pack / 'vocab.json').read_text())['predicates']
    rules = [l for l in (pack / 'learned.dl').read_text().splitlines() if l.strip() and not l.lstrip().startswith('%')]
    schemas = sorted((pack / 'templates/schemas').glob('*.py.j2'))
    return {'predicates': len(voc), 'schemas': len(schemas), 'learned_rules': len(rules),
            'template_lines': sum(len(p.read_text().splitlines()) for p in schemas)}


def problems_text(pack):
    lines = []
    for f in sorted(solved_dir(pack).glob('*.json')):
        r = json.loads(f.read_text())
        lines.append(f"- {r['id']} {r['signature']}: {r['statement'][:160]}\n  facts: {json.dumps(r['facts'], ensure_ascii=False)}")
    return '\n'.join(lines)


def attempt(pack, proposal):
    files, delete, facts = proposal.get('files') or {}, proposal.get('delete') or [], proposal.get('facts') or {}
    bad = edit_violations(pack, files, delete)
    if bad:
        return False, '; '.join(bad), None
    stored = {f.stem: json.loads(f.read_text()) for f in solved_dir(pack).glob('*.json')}
    missing = sorted(set(stored) - set(facts))
    if missing:
        return False, f'facts missing for {missing[:10]}', None
    work = Path(tempfile.mkdtemp(prefix='gcons_')) / 'pack'
    shutil.copytree(pack, work)
    for rel, text in files.items():
        (work / rel).write_text(text if text.endswith('\n') else text + '\n')
    for rel in delete:
        (work / rel).unlink(missing_ok=True)
    for pid, rec in stored.items():
        rec['facts'] = facts[pid]
        (work / 'solved' / f'{pid}.json').write_text(json.dumps(rec, ensure_ascii=False))
    try:
        json.loads((work / 'vocab.json').read_text())
        found = new_lint_errors(pack, work)
        if found:
            return False, {'lint': found[:8]}, work
        broken = regression(work, only=set(affected(work))) + complexity_regressions(pack, work) + reference_compat(pack, work)
    except Exception as exc:  # noqa: BLE001
        return False, f'{type(exc).__name__}: {str(exc)[:300]}', work
    if broken:
        return False, {'broken': broken[:8], 'count': len(broken)}, work
    before, after = size(pack), size(work)
    if after['predicates'] > before['predicates'] or after['schemas'] > before['schemas'] or after == before:
        return False, {'not_smaller': {'before': before, 'after': after}}, work
    return True, {'before': before, 'after': after}, work


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--model', default='sonnet')
    ap.add_argument('--max-rounds', type=int, default=3)
    ap.add_argument('--log', type=Path)
    args = ap.parse_args()
    pack = PACK.resolve()
    assert not regression(pack), 'regression must pass before consolidating'
    log, feedback = [], ''
    for r in range(1, args.max_rounds + 1):
        t0 = time.time()
        try:
            proposal = ask(PROMPT.format(layers=LAYERS_NOTE, pack=pack_text(pack), problems=problems_text(pack), feedback=feedback), args.model)
        except Exception as exc:  # noqa: BLE001
            log.append({'round': r, 'error': str(exc)[:300]}); feedback = '\nYour previous reply was not valid JSON.\n'; continue
        ok, info, work = attempt(pack, proposal)
        entry = {'round': r, 'ok': ok, 'seconds': round(time.time() - t0, 1), 'summary': proposal.get('summary'),
                 'changes': changes(pack, proposal.get('files') or {}), 'delete': proposal.get('delete'), 'info': info}
        log.append(entry)
        print(json.dumps(entry, ensure_ascii=False)[:1500], flush=True)
        if ok:
            for rel in proposal.get('files') or {}:
                shutil.copy(work / rel, pack / rel)
            for rel in proposal.get('delete') or []:
                (pack / rel).unlink(missing_ok=True)
            shutil.rmtree(pack / 'solved'); shutil.copytree(work / 'solved', pack / 'solved')
            assert not regression(pack)
            update_deps(pack)
            shutil.rmtree(work.parent, ignore_errors=True)
            break
        if work:
            shutil.rmtree(work.parent, ignore_errors=True)
        feedback = f'\nYour previous proposal was rejected: {json.dumps(info, ensure_ascii=False)[:2000]}\nFix it.\n'
    if args.log:
        args.log.write_text(json.dumps(log, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
