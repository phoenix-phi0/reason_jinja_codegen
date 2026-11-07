# Completing the expert system — design brief for the batch tasks

The project (this directory) is a rule-driven code generator: a problem statement is translated by a model into facts
from `packs/general/vocab.json`; stratified Datalog rules (`packs/general/*.dl`, engine `datalog.py`) choose a schema,
parameters, library functions (`packs/general/templates/lib/`), answer type and feasibility; thin Jinja glue templates
(`templates/schemas/`) call the library functions; every schema has a slow reference implementation
(`templates/reference/`). Growth (`general_grow.py`) lets a model extend the pack, admitted only if all checks pass.
Read `README.md` (sections from "泛化式生成" on) and the module docstrings first. Key commands (always with
`PYTHONDONTWRITEBYTECODE=1 .venv/bin/python`):

    general_grow.py check          # library checks + every stored problem (packs/general/solved/): tests, glue, differential, cost
    -m unittest                    # 63 tests; run sequentially, never in parallel with other heavy jobs (timing checks)
    lib_check.py --no-cache        # library unit tests + declared complexity
    general.py solve PROBLEMS.json --model haiku --log out.json   # end-to-end on a problem set (calls the claude CLI)
    general_grow.py grow PROBLEMS.json --ids ... --notes LOG.json  # growth (calls the claude CLI, sonnet)

Problem sets for evaluation: `/workspace/rjc_runs/glm2/glm2_clean.json` (18 problems; 16 solved end-to-end at the start
of this work) and `/workspace/rjc_runs/earlier_stored.json` (64 problems; 61 solved). A problem set is a JSON list of
{"id", "signature", "statement", "tests": [{"args", "expected"}]}.

## Non-negotiable rules for every task

1. Never weaken a check to make something pass. Never delete or change library functions (append-only; bug fixes must be
   documented in the report with the failing input). Never edit the tests or statements of stored problems.
2. `general_grow.py check` must print `regression ok` and `-m unittest` must pass at the end of your task. If after two
   honest attempts they do not, stop, leave the code in the best consistent state (or restore from git-less backups you
   make yourself at the start of the task) and say so in the report.
3. Add unit tests for every new behaviour (a failing-case test for every new check). Keep the existing test style.
4. Write `reports/<task>.md`: what you built, how to use it, verbatim outputs of the required checks, measured numbers,
   open problems. Be concrete; no claims without a command output backing them.
5. Document new commands/facts/rules in README.md (append a section; Chinese is fine, match the existing tone).
6. Models: when a task needs the claude CLI it is available as `claude -p` (see `general.ask`/`extract`); use haiku for
   translation/answering, sonnet for growth. Do not spawn more than one such call at a time.

## Task 1 — ask-back (consultation interface)

Today the rules refuse a problem when a library function's precondition is not guaranteed by the statement
(`unmet_precondition`) or when an assumed size makes every plan infeasible (`too_slow`). An expert system asks instead.

- In `general.grouped_facts`, mark sizes the driver derived (not stated) with an extra fact `assumed_size(P,A)`.
- Rules (new file `packs/general/questions.dl`, add to pack.json): derive
  `ask_guarantee(P,A,C)` (a candidate function requires C of the parameter bound to its role, not guaranteed, not waived)
  and `ask_size(P,A)` (why_slow for a role whose bound parameter has only an assumed size). Keep `error(...)` as is.
- `general.questions(problem, facts, pack)` turns these into natural-language questions, e.g. "Does the statement
  guarantee that every element of `coins` is a positive integer?" / "Does the statement bound the length of `nums`
  (give the bound)?".
- `general.answer_questions(problem, questions, model)`: one claude call that sees ONLY signature + statement + the
  questions, answers each with {"answer": "yes"|"no"|"not stated"|<class>, "quote": "<exact words from the statement>"}.
  Programmatically verify the quote is a substring of the statement; an answer without a valid quote counts as
  "not stated". Yes → add `guarantees(A,C)`; a size class → add `size(A,class)` (classes: tiny ≤1e2, small ≤1e3,
  medium ≤1e5, large ≤1e6, huge ≤1e7, vast). Never add a fact on "not stated".
- In `general.main` (solve): when evaluate returns rejected with unmet/too_slow (or questions exist), ask, apply, re-evaluate
  (at most 2 rounds), log `questions`, `answers`, `solved_after_questions`. Then the existing near-miss retry as before.
- Acceptance: unit tests with a fake answerer (yes with valid quote → solved; yes with a fabricated quote → still refused;
  not stated → refused); end-to-end on the two problem sets reports how many problems got solved via questions.

## Task 2 — dependency tracking (truth maintenance, minimal form)

- Store in each `packs/general/solved/<id>.json`: `schema`, `uses` (functions), and sha256 of the rendered solution and
  reference sources (`general.build(..., reference=False/True)`), under a `deps` key. Command
  `general_grow.py deps --update` fills them for all stored problems; `general_grow.py deps --who <rule-or-function-or-schema>`
  lists stored problems that depend on it.
- `general_grow.affected(pack)`: re-render (rules + Jinja only, no execution) every stored problem; return those whose
  rendered solution or reference hash differs from the stored one, plus those that fail to render. This is exact: identical
  generated code cannot behave differently.
- Use it: in `try_proposal` and `general_consolidate.attempt`, run the expensive checks (`regression`) only on
  `affected ∪ {new problem}`; keep `general_grow.py check` as the full run; after an admitted proposal update deps.
  Prove soundness in a unit test: modify a rule that touches some problems, assert affected == the set whose code changed,
  and that full regression finds nothing outside it.
- Acceptance: measured check time in a growth-style edit before/after.

## Task 3 — static rule checks

`general_grow.py lint` (and called at admission in try_proposal/attempt): over all pack rule files
- dead rule: a body predicate that is neither a vocabulary predicate, a driver fact (problem, algorithm, complexity, role,
  drives, requires, size, assumed_size, guarantees, want_reference) nor the head of any rule → REJECT (typos);
- redundant rule: two rules with the same head whose bodies are the same up to variable renaming, or one body ⊆ other → WARN;
- contradiction: functional predicates (schema, answer_type, map_fn, use_mode, order_mode, neighbours, no_answer) with two
  rules whose bodies are identical up to renaming but heads differ in a constant → REJECT;
- unused vocabulary predicate: appears in no rule body and no template (`relations.rows/one/has('<pred>'`) → WARN.
Run it on the current pack; put the findings in the report and fix the real ones (dead rules, true contradictions; for
warnings say which you consider real). Then run `general_consolidate.py` once (it calls a model) with lint wired into its
admission, and report the before/after pack size (predicates, schemas, learned rules) and that end-to-end results on the
two problem sets did not get worse.

## Task 4 — composition: implicit sources, stage chains, condition trees, backward chaining hints

Goal: problems that are combinations of existing schemas get solved without growing a dedicated schema.
- Implicit sources (vocab + rules + templates): `source(S, param, A)`, `source(S, range, Lo, Hi)` (Lo/Hi int literal or int
  param, inclusive), `source(S, digits, X)`, `source(S, chars, X)`, `source(S, stage, I)` (output of an earlier stage).
  `iterate(A)` stays as the short form of a param source.
- Stages: `stage(I, Schema)` with the stage's own facts namespaced (design the fact shape; e.g. stage facts carry the
  stage index as first argument, single-stage problems keep today's flat form). Rules check that consecutive stages'
  output/input types match (`produces(Schema, Agg, Type)`, `consumes(...)`); the solution template renders stages in
  order into `_s1`, `_s2`, ... outside loops (glue whitelist must still pass). Reference templates compose the same way.
- Condition trees for seq_fold filters: `cond(C, <existing keep/drop/remainder/bound vocabulary...>)`, `expr(E, and|or, X, Y)`,
  `expr(E, not, X)`, `filter(E)`; rules: every node defined once, leaves are conds, acyclic (use stratified reachability);
  the templates render the Python boolean expression. Existing `keep/drop/...` facts stay valid (implicitly and-ed).
- Backward-chaining hint: when no schema is derived, `general.explain` also proposes schema chains that could produce the
  required answer type from the available sources (search over produces/consumes, depth ≤ 3) and includes them in the
  near-miss text given to the translator.
- Update the translator prompt/vocab docs so the model can emit staged descriptions.
- Acceptance: with hand-written facts (a `facts` command run, no model) these are solved without new schemas: factorial
  digit sum (range → product → digits → sum), leap-year count (range → and/or/not of remainders → count), relaxed
  palindrome (chars → keep alnum, lower → compare with reverse: add the small aggregate `is_palindrome` if needed),
  frog jumps 1..k (range source feeding knapsack items). Then end-to-end with the haiku translator on the two sets:
  report solved counts and that no stored problem regressed. Every new rule/template gets reference templates and tests.

## Task 5 — explanation chain

- `datalog.Datalog` records one derivation per derived fact (rule text + the body facts used) when run with
  `explain=True`; add `d.why(pred, args)` returning the derivation tree (depth-limited).
- `general.explain_plan(problem, facts, pack)` → text: which schema and why (rule + facts), which functions and why
  (candidate → ok (sizes, fits) → not beaten), answer type, preconditions checked, stages if any.
- Put the plan as a header comment in the generated solution and in the solve log (`plan` field). Unit tests: the
  derivation of `uses` for a stored pair-count problem names count_pairs_residue, its complexity, the size class and
  the fits fact.

## Task 6 — final verification

Run and record verbatim: `general_grow.py check`, `-m unittest`, `lib_check.py --no-cache`, `general_grow.py lint`,
end-to-end on both problem sets (twice each, to show translation variance), and a growth run on whatever is still unsolved
(max 3 rounds per problem). Write `reports/final.md` with a table of all numbers before (from the task reports) and after,
the list of problems still unsolved with the reason, and the open problems you see. Be honest about failures.

# Batch 2 — tasks 7 to 12 (after the batch-1 reports in reports/task1..5.md and reports/final.md)

Read those reports first; they describe what exists now (ask-back, deps/affected, lint, composition, explanation chain).
The same non-negotiable rules apply. Current state: 82 stored problems, 163 unit tests, `check`/`lint`/`unittest` all pass.

## Task 7 — rejection corpus; restore the checks consolidation removed

The task-3 consolidation removed, among equivalent rewrites, seven real checks that nothing protected:
`missing_shift_by`, `missing_circle_step`, `missing_case_to`, `missing_range_to`, `missing_date_origin`,
`range_count_needs_order`, `range_steps_use_once` (see reports/task3.md and the diff against learned.dl in
`/workspace/rjc_runs/batch/before/reason_jinja_codegen/packs/general/learned.dl`). Admission can only prove that stored
(valid) problems still pass; it cannot see that an `error` rule became unreachable.
- Create `packs/general/rejected/<name>.json`: {"signature", "facts", "error": "<error constant>"} — a description that must be
  rejected with exactly that error. Write at least one case per distinct `error(...)` constant in every rule file (list them
  with a script; there are dozens). For the seven removed checks: first decide whether each is still needed by looking at the
  template: if a missing fact makes the template fail loudly (`relations.one` raises) or a sensible default exists, say so;
  otherwise restore the rule. Add corpus cases for the restored ones.
- `general_grow.regression` (and therefore `check`, `try_proposal`, consolidation) runs the corpus: every case must still be
  rejected with its error; a proposal that makes a corpus case pass or change its error is refused with that feedback.
- `general_grow.py check` output gains a line `rejections ok (N cases)`. Unit tests: corpus passes; a rule removal that frees
  a corpus case is refused by try_proposal and by consolidate.attempt.

## Task 8 — growth proposal pre-check; output-sensitive complexity; retry run-length decode

- `general_grow.precheck(pack, proposal)` before any expensive check: every predicate/value used in the proposal's `facts`
  exists in the (new) vocab; every predicate used in new rules is a vocab/driver/head predicate (reuse general_lint);
  a new schema template has a reference template and an answer_type rule; a new library function has metadata with
  role/drives/requires/generator/tests; files outside the editable set are named explicitly in the feedback. Feedback lists
  every missing piece at once, so the model can fix them in one round. Unit tests for each kind of omission.
- Output-sensitive complexity: allow `"complexity": "n+out"` in library metadata with `"output_size"` describing how the
  generator bounds the output (e.g. digit counts ≤ 9 so output ≤ 9n). `lib_check` measures growth on the generator's inputs
  as usual; `problem_cost` for problems whose functions declare `n+out` scales inputs so that the declared bound holds
  (document how). Add corpus/unit tests. Then run growth on `glm2_run_length_decode` (max 3 rounds) and report.

## Task 9 — translation robustness, measured

- Measure first: run `general.py solve` 5 times on `/workspace/rjc_runs/glm2/glm2_clean.json` and 3 times on
  `/workspace/rjc_runs/earlier_stored.json` with haiku; report per-problem solved counts (a problem is "unstable" if it is
  solved in some runs and not others), total wrong code (must be 0), and time per run.
- Implement `--translate-twice`: translate independently twice; if both describe and both evaluate solved with the same
  answer type, use the first; if exactly one is uncovered/rejected, use the other; if both fail, fall back to the existing
  near-miss/ask-back retry. Also `--fallback-model sonnet`: when haiku ends uncovered after all retries, translate once with
  sonnet. Both off by default; log which path solved each problem.
- Measure again (same runs) with `--translate-twice` and with `--translate-twice --fallback-model sonnet`. Acceptance: fewer
  unstable problems, zero wrong code; report costs (number of model calls per problem).

## Task 10 — composition, extended

- Stages may use any schema whose output type is a sequence or scalar (seq_rank, seq_reduce, run_encode, pair_count, knapsack,
  interval_scan...), with produces/consumes declared per schema; a stage may read several sources (e.g. a param and an earlier
  stage) where the schema has several inputs (knapsack items + target).
- Virtual sources get sizes from their bounds: `range lo hi` → size class of hi's size/magnitude; `digits x` → tiny; `chars s` →
  size of s. Cost rules must see them (a `range 1 n` with n large and an O(n*t) stage must be refused as too_slow).
- Chain hints across schemas (depth ≤ 3), ranked by how many of the problem's facts the chain's first stage already satisfies.
- Write 6 new composition problems of your own (brute-force references, ≥ 8 tests each, saved under examples/), e.g.
  "sum of the k largest distinct even values", "number of distinct run lengths", "max overlap among intervals whose length is
  prime", "count pairs among the digits of n! with sum divisible by 3"; solve them with hand-written facts (no new schema),
  store them, then run haiku end-to-end on them and report.

## Task 11 — test suite speed and a one-command check

- Mark timing-sensitive tests (`problem_cost`, `lib_check` growth, differential timeouts) with a decorator/attribute; run all
  other tests in parallel (e.g. `-m unittest` through a small runner script `run_tests.py` using multiprocessing), then the
  timing tests sequentially. Target: full suite under 3 minutes on this 8-core machine without flakiness (run it 3 times).
- `run_checks.sh`: lint → deps → check (incl. rejections) → run_tests.py, printing a one-line verdict per step; used by task 12.

## Task 12 — final verification 2 and a brief for external reviewers

- Run `run_checks.sh`; run both problem sets with the best translation setting from task 9 (3 runs each); run the 6 composition
  problems; growth on anything unsolved (max 3 rounds). Write `reports/final2.md` with a table: start of batch 1 (from
  reports/final.md "start of work"), end of batch 1, end of batch 2; per-problem stability; everything still unsolved and why.
- Write `reports/REVIEW_BRIEF.md` for an external reviewer (another model, no context): what the system claims, exact commands
  to verify each claim, where the corpus/tests live, and the known residual risks (special cases at sizes the random inputs
  never reach; a new schema and its new reference sharing a mistake; translator variance). It must be self-contained.
