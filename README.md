# 通用 Python 代码生成器

本仓库导入的是 **2026-11-08 03:42:51 JST** 的源码快照（归档 SHA256 `6d44a491169956ce4633d24b7602400d6afe637b2c94bad3e0d97c361d6d3375`，623 个文件）。其中不含该时间之后仍在进行的批任务修改，也不表示最新全量验收已经完成。文档里的历史性能数字和 `/workspace/rjc_runs/` 路径是快照前的记录，对应运行数据没有随快照发布。详见 `EXPORT_NOTES.md`。

输入事实 → Datalog 推理 → 生成计划 → Jinja 模板 → Python 模块与包。

核心不绑定具体业务；通过修改推理规则和 Jinja 模板扩展 Python 代码结构。当前模板支持 import、常量、普通函数、异步函数、装饰器、类、继承、类属性、方法、dataclass，以及多模块包导出。生成目标仅支持 `.py`，额外输出 `inference.json` 作为推理报告。

## 运行

```bash
# 在本仓库根目录执行
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 通用 Python 示例：函数、类、异步函数和包
.venv/bin/python generate.py examples/python.json --out generated/general

# dataclass 示例
.venv/bin/python generate.py examples/entities.json --out generated/python

.venv/bin/python -m unittest -v
```

初次安装可先执行 `python3 -m venv .venv`。

## 修改规则与模板

生成包位于 `packs/python/`：

- `pack.json`：配置规则文件、模板目录以及固定事实。
- `rules.dl`：根据输入事实推导生成计划与模板使用的关系。
- `templates/module.py.j2`：普通函数、常量及类。
- `templates/model.py.j2`：带字段校验的 dataclass。
- `templates/package.py.j2`：包导入与导出。

默认规则使用以下输入事实：

| 事实 | 含义 |
| --- | --- |
| `module(key, path)` | 生成普通 Python 模块 |
| `package(key, path)` | 生成包的 `__init__.py` |
| `entity(key, path)` | 生成 dataclass 模块 |
| `function_mode(key, name, async)` | 将模块函数生成成异步函数 |
| `field(entity, name, type)` | dataclass 字段类型，支持 text/integer/boolean |
| `required(entity, name)` | 为文本字段增加非空校验 |

例如规则 `emit(module.py.j2,P,M) :- target(python), module(M,P).` 将输入模块转换为生成任务。新增代码模式时，可新建模板并添加对应 emit 规则，核心无需改动。可以复制生成包后用 `--pack <目录>` 选择它。

## 输入格式

`facts` 保存字符串元组，参与推理；`data` 保存供模板使用的结构化数据。

```json
{
  "facts": {"module": [["math", "math_utils.py"]]},
  "data": {
    "math": {
      "functions": [{
        "name": "add",
        "parameters": ["a: int", "b: int"],
        "returns": "int",
        "body": "return a + b"
      }]
    }
  }
}
```

完整示例见 `examples/python.json`。函数和方法的 body 是 Python 源代码字符串，多行内容用换行分隔；模板会增加缩进。参数、返回类型、装饰器、基类和 import 同样使用 Python 语法。常量和类属性使用 JSON 值，通过 pyrepr 输出 Python 字面量。类方法的 async 字段可设为布尔值。

这是基于明确输入规格的代码生成器；业务算法需要在输入的 body 中提供，或编写进专用 Jinja 模板。生成器不从自然语言推导算法。

## 通用协议及模板上下文

核心只约定 `emit(template, path, key)` 和 `error(...)` 两个谓词。emit 指定模板、输出相对路径及数据键；key 为空字符串时使用完整 data。error 存在任何记录就终止生成。

| 模板名称 | 含义 |
| --- | --- |
| `data` | 完整输入数据 |
| `item` | 当前 emit 选择的数据 |
| `key` | 当前数据键 |
| `facts` | 原始及推导关系，按谓词分组、排序的记录列表 |
| `relations.rows(predicate, *prefix)` | 查询指定前缀的记录 |
| `relations.has(predicate, *values)` | 判断完整记录是否存在 |
| `relations.one(predicate, *prefix)` | 查询唯一末列值，缺失或多值时报错 |
| `value \| pyrepr` | 输出 Python 字面量 |

Jinja 使用 StrictUndefined，支持 include、extends、宏。pack.json 的 rules 可以指定多个相对于生成包的规则文件；facts 可以提供固定事实。

## 规则和验证边界

规则一行一条：`head(...) :- body(...), other(...).`。`%` 后为注释；大写开头表示变量，小写表示常量，大写常量需用双引号。头部变量必须在规则体中绑定。同一谓词的参数数量必须一致。支持正向推理、连接及递归，不支持否定、算术和函数。简单解析器不支持常量中的逗号、括号和 `%`；复杂内容应放入 data 或 JSON 事实。

所有产物先经过 AST 解析和 compile 检查，再开始写入；生成器不执行产物，业务行为由测试验证。重复路径、路径越界、非 `.py` 输出会报错。Python 标识符及导入依赖需由规格和模板保证有效，语法检查无法验证所有运行时行为。

写入不是事务，I/O 中断可能留下部分文件。每次运行覆盖计划内文件，不自动删除旧文件。规则包、输入代码片段和模板均应来自可信来源。

推理机来自工作区 `dsl_workflow_exp/tools/dslagent/datalog.py`，增加了元数及规则头变量检查。项目无需模型 API。旧版 generated/user.py 保留为首次示例产物，当前示例在 generated/general 和 generated/python。

## 能力实测

见 [BENCHMARK.md](BENCHMARK.md) 和原始结果 `benchmark_results.json`。复现执行 `.venv/bin/python benchmark.py`，再执行 `.venv/bin/python summarize_benchmark.py`。测试覆盖生成后实际运行、规则推导、规模和不支持语法的边界；规模测试不是最大容量保证。

另外新增 [14 道编程题实测](EXERCISES.md)：833 项断言通过，覆盖算法、数据处理、有状态类和异步并发。执行 `.venv/bin/python test_exercises.py` 可复现；题型模板位于 `packs/exercises`。

## 成长式生成（grow.py）

遇到题库里没有的题目时，`grow.py` 依次尝试三步：

1. **已知**：规则 `algorithm(K,A) :- task(K,A), supported(A).` 能把题目解析到某个模板，并且测试全部通过。
2. **复用**：题库里有签名兼容的算法能通过全部测试，就追加一条规则 `alias(题目,算法)`，不调用模型。
3. **学习**：由学习器（`claude -p`，默认 sonnet）根据题面和约一半可见测试写出模块，最多 3 轮；只反馈可见测试的失败详情，隐藏测试只报失败数量。通过全部测试才入库：写入模板、追加 `supported(...)`、保存测试，再对整个题库做回归，任何失败都整体回滚。

```bash
.venv/bin/python grow.py solve problems.json            # 学习并入库
.venv/bin/python grow.py solve problems.json --learner none   # 只用题库，不调用模型
.venv/bin/python grow.py check                          # 题库回归
.venv/bin/python -m unittest test_grow -v               # 不调用模型的单元测试
```

成长出的内容都在 `packs/growing/`：`learned.dl`（supported 与 alias 事实）、`templates/algorithms/`（模板，学到的代码用 `{% raw %}` 包住）、`tests/`（每个算法的回归测试）、`library.json`（来源与签名）。种子是 `packs/exercises` 的 14 个算法模板。

边界：学到的代码在独立进程中运行，有内存与时长限制，但没有网络和文件系统隔离，只应对可信来源的题目使用。是否复用只看测试结果，测试覆盖不到的语义差异会被误判为同一题。生成器核心（generate.py、datalog.py）未改动。

## 泛化式生成（general.py，packs/general）

模型只负责把题面翻译成 `packs/general/vocab.json` 里的特征事实，不写代码；用哪个算法骨架、带什么参数、缺省值是什么，由 `packs/general/rules.dl` 推出来（缺省值和一致性检查用到分层否定），再由 `templates/schemas/` 下带参数的骨架生成代码。

```bash
.venv/bin/python general.py solve problems.json --model haiku      # 抽取特征 → 推理 → 生成 → 测试
.venv/bin/python general.py facts problems.json --facts gold.json  # 跳过模型，直接用给定事实
.venv/bin/python -m unittest test_general test_datalog -v
```

现有骨架：seq_fold（筛选 → 映射 → 聚合）、grid_components（连通块计数 / 最大块）、grid_bfs（最短步数）、knapsack（最少件数 / 方案数 / 能否凑成，可重复或各用一次，计序或不计序，可取模）。
题目超出词汇时，抽取器回答 uncovered 并说明缺什么；规则发现描述自相矛盾时用 `error(...)` 拒绝。两种情况都不会生成代码。

datalog.py 现在支持 `not`（分层否定，否定不能出现在递归环里）和 `A != B`；常量加引号后可含逗号、括号、`%`；看不懂的写法一律报错，不再静默丢弃。旧版备份在 datalog.py.bak-20261106-pre-negation。

### 自动成长与整理（general_grow.py、general_consolidate.py）

- `general_grow.py grow problems.json --notes log.json`：题目无法覆盖时，由模型提议扩展词汇、learned.dl 或骨架模板；这道题全部测试通过，且 `packs/general/solved/` 里存的题全部回归通过（用存下的事实，不调模型），才会保留。
- `general_consolidate.py`：让模型合并重复的谓词和骨架，同时迁移已存题目的事实；回归通过，并且谓词数和骨架数都不增加，才会保留。
- `general_grow.py repair`：回归失败时（比如大规模测试超时），让模型修复模板。
- `general_grow.py check`：回归。存档里部分题带有约 10^5 规模的测试，每个测试时限 10 秒，用来防止整理时把高效算法换成暴力算法。

### 算法库（packs/general/templates/lib）

算法是独立的 Python 函数：每个函数一个文件，配同名 `.json` 元数据（说明、声明的复杂度、合法输入的生成器、至少 5 个单元测试）。
`algorithms.dl` 用 `uses(P,F)` 选函数，优先选更快的那个，暴力解只作兜底；`solution.py.j2` 把选中的函数嵌进生成的代码；骨架模板只是很薄的胶水层，负责调用函数。

入库与回归时检查（`general_grow.py check`，不调用模型，约 1 分钟）：
- `lib_check.py`：每个函数通过自己的单元测试；生成器必须真的随 n 增长（最大规模下输入至少 n/2 个元素，并且至少是小规模的 2.5 倍），耗时太短时把规模乘 4 再测，最多两次；实测增长必须符合声明的复杂度。
- 算法库和参考实现只增不改：已有文件不能修改、不能删除；新函数必须 `.py` 和 `.json` 成对；新增骨架必须带参考实现。
- `complexity_regressions`：任何一道已存的题，改动后选中函数的声明复杂度都不能变差。
- `glue_violations`：生成的 `solve()` 只能调用选中的库函数和白名单内置函数；线性开销的操作（库函数调用、sum、sorted、join、对非字面量的 in）只能放在循环外；循环嵌套最多一层；循环里不能用 `x = x + ...` 增长序列，也不能把序列重复非常数次；不能用 while、嵌套函数或递归。
- `differential`：每个骨架都有一份慢但明显正确的参考实现（`templates/reference/`），用随机输入比对生成代码和参考实现的输出。随机输入覆盖长度 0..20（每个长度两遍，其中一遍只用非空区间），随机长度最大到 500，三分之一的用例把坐标平移 10^6 或 10^9、把整数放大 1000 倍。
- `reference_on_tests`：参考实现在存档测试上也必须给出正确答案。
- `problem_cost`：用放大的输入给整份生成代码计时，分两组：数值和测试里的接近，或者平移到很远、放得很大；网格按约 √n×√n 放大。实测增长不能超过所用函数声明的复杂度。确实没法做得更快的题，可以在存档里人工写上 `cost_exempt` 和理由（目前只有大整数连乘这一道）。

适用范围：这些检查防的是模型在成长和整理时**无意中**改坏代码。经过三轮外部验证（Codex 和 Goose 两边都参与），以下两类问题仍然发现不了，要靠人工审查：
1. 只在某个确切的输入规模或取值上出错，而随机输入恰好没生成到；
2. 新增骨架和它新增的参考实现犯了同一个错误。

### 推理机的四项能力（2026-11-07）

- **近失解释**（`datalog.py` 的 `near_misses`，`general.explain`）：推不出骨架时，列出最接近的规则、还缺哪些事实、哪些否定文字挡路。翻译失败时带着这个提示让翻译模型重试一次；成长的提示词里也用它代替散文描述。
- **答案类型**（`packs/general/types.dl`）：从骨架和输出事实推出答案类型（int / bool / string / int_list / string_list / list_of_lists，可空），生成代码前和测试期望值的 JSON 类型比对，不符即 `type_mismatch`。
- **规模与可行性**（`packs/general/costs.dl`）：题面给出的 `size(param, class)`（tiny ≤ 1e2 … vast）或由测试推出的规模，对照函数声明的复杂度（表由数量级生成，预算约 1e8 步），只保留可行的函数，再按复杂度选最快的；没有可行函数时报 `too_slow`。`algorithms.dl` 现在只给出 `candidate(P,F)`。
- **前提与保证**：库函数元数据里的 `requires`（如背包物品必须为正、无限次使用时须互异）对照题面明确说出的 `guarantees(param, cond)`；不满足时报 `unmet_precondition` 并说明缺哪条保证。存档题的事实已迁移（规模来自测试证据，保证来自题面）。

库函数元数据新增 `role`（函数的职责）、`drives`（决定开销的角色，须由 `binds(P,Role,A)` 规则绑定到参数；新角色在 learned.dl 里加一条 binds 规则）、`requires`（前提）；复杂度类新增 `1`（常数时间，不需要生成器）。

其他：模型回复只解析第一个完整 JSON；成长时检查按代价从小到大、失败即停；回归并行（约 25 秒）；`lib_check` 的生成器新增 `string`，规模按生成器声明计算。

## 独立网页对话（chat.py）

```bash
# 在本仓库根目录执行；仅监听回环地址，不要直接暴露到公网
.venv/bin/python chat.py --port 8797
# 可选 --model；默认 haiku，与 general.py 默认一致，不改全局模型配置。
# 无模型费用的针对性测试：
.venv/bin/python -m unittest test_chat -v
```

在 **box 本机**打开 http://127.0.0.1:8797/ 。仅监听回环地址，不提供公网路由；不修改现有 Chat、relay 或鉴权。终端 Ctrl+C 停止。没有新增依赖。

填写题目参数签名（如 `solve(nums)` 或 `solve(coins, target)`），自然语言描述题目，再在同一会话补充或修正条件。更换参数需先清空。每轮仅调用一次项目现有 `general.extract` 翻译，验证词汇后用 `general.engine_for` 执行真实 Datalog 推理，显示提取事实、规则结果与近失说明。模型翻译仍可能有误，应核对事实；缺失保证/规模应由用户补充，不能当作已证明。`uncovered` 表示词汇不覆盖，不自动成长。

这不是通用知识聊天或数值求解执行器：不运行 `build/evaluate`，不执行生成代码，不写规则、模板或算法库。现有 general.py 命令不变。会话只在内存，刷新新建独立会话，重启丢失；清空移除当前会话上下文。上限 20 轮/18000 字符，每条最多 6000 字符，最多 100 个会话，空闲一小时可回收。模型调用全局串行，忙碌返回可重试错误，单次最长约 300 秒；失败不更新上下文，不向网页泄露 CLI 输出。仅适合可信本机用户，尚未增加公网账号鉴权、持久化或后台自启动。

网页对话现已接通原有 Datalog → Jinja 代码生成步骤：推理通过时默认显示全部生成的 Python 源码；只做静态检查，不执行。条件不足、超出覆盖或引擎阻断时不生成。公网 Chat 的旧历史可根据保存事实与签名按当前模板重建代码；缺数据时需重新请求。相关静态生成测试：`.venv/bin/python -m unittest test_chat_codegen -v`。

## 反问（ask-back，general.py）

规则拒绝一个题目有两种常见原因：库函数的前置条件题面没保证（`unmet_precondition`），或者某个尺寸只是驱动器推测的、导致所有方案都太慢（`too_slow`）。现在系统会先问题面，而不是直接放弃。

- `general.grouped_facts` 给驱动器推出（题面没写）的尺寸额外加事实 `assumed_size(P,A)`。
- `packs/general/questions.dl`（已加入 pack.json）：`ask_guarantee(P,A,C)`（候选函数要求参数 A 满足 C，题面没保证也没被豁免）和 `ask_size(P,A)`（某角色无可行函数，且驱动它的参数只有推测尺寸）。`error(...)` 不变。
- `general.questions(problem, facts, pack)` 把它们变成自然语言问题；`general.answer_questions(problem, questions, model)` 只给模型签名+题面+问题，要求每个回答带题面原文 `quote`，程序校验 quote 是题面的子串（空白折叠后），否则按 "not stated" 处理。yes → `guarantees(A,C)`；尺寸等级 → `size(A,class)`；"not stated"/"no" 不加任何事实。
- `solve` 中被拒（unmet/too_slow）时自动提问、应用、重新评估（最多 2 轮），日志有 `questions`、`answers`、`facts_added`、`solved_after_questions`；之后原有的 near-miss 重试照旧。`--no-ask` 可关闭。
- 测试：`test_general.AskBackTest`（假回答器：有效引用→解出；伪造引用→仍拒绝；not stated/no→拒绝；尺寸回答；提示里不含测试数据）。

## 依赖追踪（deps，general_grow.py）

每个 `packs/general/solved/<id>.json` 带 `deps`：`schema`、`uses`（选中的库函数）、渲染出的解答/参照实现源码的 sha256
（`solution_sha256`、`reference_sha256`，由 `general.build(..., reference=False/True)` 得到，只跑规则 + Jinja，不执行代码）。

    general_grow.py deps --update          # 为所有已存题目写入/刷新 deps
    general_grow.py deps                   # 打印 affected：渲染结果与存档哈希不同、渲染失败或没有 deps 的题目
    general_grow.py deps --who NAME        # NAME 是 schema / 库函数 → 查 deps；否则当作规则文本片段，
                                           # 在副本里删掉含该片段的规则行，列出代码因此改变的题目（精确）

`general_grow.affected(pack)` 是精确的：生成的代码相同则行为必然相同。`try_proposal`、`grow_one` 采纳后的复查和
`general_consolidate.attempt` 只对 `affected ∪ {新题}` 跑昂贵的 `regression`（库函数检查照常全跑，
`complexity_regressions`/`reference_compat` 也照常）；采纳后用 `update_deps` 刷新。`general_grow.py check` 仍是全量。
没有 deps 的题目一律视为受影响。测试：`test_deps.py`。

## 静态规则检查（lint）

`general_lint.py`，命令 `general_grow.py lint`（无需模型、不跑题目，约 1 秒）。对 `pack.json` 里的所有规则文件检查：

- **死规则（ERROR）**：正文谓词既不是 vocab.json 的谓词、也不是驱动事实（problem, algorithm, complexity, role, drives, requires, size, assumed_size, guarantees, want_reference），又不是任何规则的头 —— 多半是拼写错误。
- **矛盾（ERROR）**：函数型谓词（schema, answer_type, map_fn, use_mode, order_mode, neighbours, no_answer）有两条规则，正文在变量改名意义下相同、头部只在某个常量上不同。
- **冗余规则（WARN）**：同一个头，正文相同（改名后）或一条正文是另一条的子集（后者多余）。
- **未使用的词汇谓词（WARN）**：既不在任何规则正文，也不在任何模板的 `relations.rows/one/has('<pred>'` 里。

准入：`try_proposal`（grow）和 `general_consolidate.attempt` 在跑任何检查之前先对提案后的 pack 做 lint；只要出现 *旧 pack 没有的* ERROR 就拒绝，并把原因作为反馈给模型。警告不拒绝。有 ERROR 时 `lint` 命令退出码为 1。测试：`test_lint.py`。

## 组合：隐式来源、阶段链、条件树、反向提示（composition）

目标：由现有骨架组合出来的题目不必为它们单独成长一个骨架。规则在 `packs/general/composition.dl`（已加入 pack.json），词汇在 vocab.json，模板共用宏在 `templates/composition.j2`。

**隐式来源** `source(kind, x[, y])`（`iterate(A)` 仍是 `source param A` 的简写）：`range lo hi`（闭区间整数，端点是整数字面量或 int 参数）、`digits X`（整数 X 的十进制各位，整数）、`chars X`（字符串 X 的字符）、`stage I`（第 I 阶段输出的元素）。X 是参数，或（分阶段时）`stage1`、`stage2`… 表示更早阶段的输出。规则为每种来源推出一个虚拟的 `iterate(P,"$range")` 等及其 `arg` 类型，所以现有的类型/错误规则（如 `char_condition_on_numbers`）自动适用。非 param 来源只用于 seq_fold（`source_needs_seq_fold`）；在背包形状的题目里（`target` + count_ways/min_count/feasible），`source range lo hi` 就是物品列表（推出 `items_range`，用现有 range_steps，跳蛙题即此）。新增聚合 `is_palindrome`（bool，调用库函数 sequence_palindrome）。

**阶段链**：`["stage","1","seq_fold"]`、`["stage","2","seq_fold"]`… 逐个声明（从 1 连续编号），每个阶段自己的事实在谓词名前加阶段号：`["1.source","range","1","n"]`、`["1.aggregate","product"]`、`["2.source","digits","stage1"]`、`["2.aggregate","sum"]`。`arg/size/guarantees/unique` 仍是不带前缀的顶层事实；单阶段题目保持原来的平面形式。实现方式：`general.grouped_facts` 把阶段 I 当作子问题 `p.I`（事实带上这个键，并补上 `substage/parent/last_stage/before/stage_ref/stage_var`），所以 rules.dl/learned.dl 里的所有规则对阶段原样适用；顶层得到 `schema(P,staged)`，答案类型取最后一个阶段的，`uses` 为各阶段之并。规则检查：声明的骨架与推出的一致（`stage_schema_mismatch`）、每个阶段有骨架、来源只能读更早的阶段（`stage_not_earlier`，且 `validate` 先挡）、阶段输出与消费类型匹配（`stage_type_mismatch`，表 `consumes/produces`）、非末阶段的输出必须被用到（`stage_output_unused`）。目前只有 seq_fold 可作阶段（`stage` 的 schema 取值只有 seq_fold）。解答模板把各阶段按顺序平铺进 `solve()`，非末阶段写入 `_s1`、`_s2`…（循环之外，glue 白名单照常通过）；参考实现把每阶段渲染成 `_stageI(params, _s1…)`，`solve` 依次调用。

**条件树**（只用于 seq_fold）：`cond(id, keep|drop|remainder|bound, a[, b])` 是叶子（参数同 keep/drop/remainder/bound）、`expr(id, and|or, x, y)`、`expr(id, not, x)`、`filter(root)`。规则：每个节点只定义一次（`node_defined_twice`）、操作数必须已定义、无环（`condition_cycle`，用分层可达性）、有且仅有一个 filter、所有节点都从根可达（`unused_node`/`nodes_without_filter`）、not 一个操作数/and,or 两个。原有 keep/drop/remainder/bound 仍然有效，与树隐含 and。例（闰年）：`cond d4 remainder 4 0; cond d100 remainder 100 0; cond d400 remainder 400 0; expr n100 not d100; expr a and d4 n100; expr e or a d400; filter e`。

**反向提示**：推不出骨架时，`general.explain` 在近失说明之后追加 `general.chains` 的结果：在 `produces/consumes/source_elem/needs_elem` 表上搜索（深度 ≤ 3）从参数出发、以测试期望值的类型结束的阶段链，每个长度最多 3 条，丢弃数据的中间阶段（count/极值/bool）排在后面。这些文字会随重试提示交给翻译模型；它只是线索，翻译模型仍可回答 uncovered。

翻译提示和词汇文档已更新（`general.PROMPT`、vocab.json）。示例：`examples/composition_problems.json` 与 `examples/composition_facts.json`（阶乘数位和、闰年计数、宽松回文、跳蛙），不调模型：

    .venv/bin/python general.py facts examples/composition_problems.json --facts examples/composition_facts.json

四道题也存进了 `packs/general/solved/`，所以 `general_grow.py check` 对它们同样做胶水白名单、与参考实现的差分、代价检查。测试：`test_composition.py`。已知限制：只有 seq_fold 能当阶段；阶段只能读参数和更早阶段（不能同时读参数与上一阶段）；条件树不支持 digit_sum 条件，也不用于 seq_rank/seq_reduce/palindrome_check（`filter_needs_seq_fold`）。

## 解释链（explanation chain）
- `datalog.Datalog(rules, explain=True)` 为每个推导出的事实记录第一条推导（规则文本 + 用到的正文事实 + 否定文字中确认不成立的事实）；
  `d.why(pred, args, depth=4)` 返回推导树：`{'fact','rule','because':[...],'absent':[...]}`，输入事实为 `{'given':True}`，超深度为 `{'cut':True}`，事实不成立返回 `None`。默认关闭，不影响求值结果。
- `general.explain_plan(problem, facts, pack)` → 文本：选了哪个 schema 及原因（规则 + 事实）、每个函数（candidate → ok（复杂度、规模、fits）→ 未被更快者取代）、已检查的前置条件（guaranteed / waived）、答案类型、阶段。
- `general.build(..., plan=True)` 把 plan 作为 `# PLAN` 头注释写进生成的解答；`evaluate()`/`solve` 日志里有 `plan` 字段。用于哈希的渲染（deps、affected）不带头注释，所以依赖追踪不受影响。
- 测试：`test_explain.py`。

## 最终验证（Task 6）

最终核对步骤与结果见 `reports/final.md`：`general_grow.py check`、`-m unittest`、`lib_check.py --no-cache`、`general_grow.py lint`，
以及两个题集各跑两次 `general.py solve --model haiku`，再对仍未解出的题跑 `general_grow.py grow --max-rounds 3`。

## 拒绝语料（rejection corpus）

准入检查（`regression`）只能证明“已存的有效题目仍然通过”，看不到某条 `error(...)` 规则变得不可达（整合时就丢过 7 条）。
`packs/general/rejected/<error>.json` 是反向的回归集：每个文件是一个**必须被拒绝**的描述
`{"signature": ..., "facts": [[...], ...], "error": "<常量>"}`，规则引擎对它必须恰好推出这一个 error 常量。

- 可选字段 `also`：同一描述必然连带推出的其他 error（例如两个 `bracket_output` 同时给出时还会有 `two_answer_types`）；
  可选字段 `extra_rules`：只为这个用例追加的规则文本，用来触发事实够不到的防线（`two_choices`、`unknown_algorithm`、`two_answer_types`）。
- 检查器只跑规则引擎（不生成代码、不跑测试，一个用例几毫秒，全部约 2 秒）；它不做 `general.validate`，所以少数用例的事实
  虽然被词汇校验挡住（`range_needs_upper_bound`、`unknown_source_ref`、`stage_not_earlier`），其规则仍受保护。
- 每个规则文件里的每个 `error(<常量>,P)` 都至少有一个用例（`general_grow.error_constants/uncovered_errors`；单元测试要求无遗漏）。
  新增 error 规则时请同时加一个用例文件；`check` 会在末尾提示尚无用例的常量。
- 接入：`general_grow.regression` 先跑语料（再跑库检查和题目检查），所以 `check`、`try_proposal`、`general_consolidate.attempt` 都会用到。
  使语料用例变成“通过”或“换了 error”的提案会被拒绝，反馈里列出具体用例（`feedback_text`）。整合提案不能改语料：语料用例引用的
  谓词/取值必须保留，要改词汇就先人工迁移语料。
- `python general_grow.py check` 输出多一行 `rejections ok (N cases)`。

## 增长提案预检（precheck）与输出敏感复杂度（n+out）

**`general_grow.precheck(pack, proposal, problem=None)`**：在任何引擎运行/测试之前，对提案做廉价的结构检查，返回**所有**缺失项（一次列全，模型一轮就能补齐）。`try_proposal` 第一步调用它，失败时反馈形如 `precheck found N problem(s): (1) … | (2) …`，且不跑任何后续检查。检查内容：
- 可编辑集合之外的文件被点名（并列出可编辑/固定文件）；库函数追加式（已存在的不得改）；新库函数需 `.py`+`.json`；JSON 必须可解析；
- `facts` 中的谓词/取值/参数个数必须在（新）`vocab.json` 里（复用 `general.validate`）；新词汇谓词必须有 `doc`；不得丢掉已有谓词；
- 规则文件可解析；新规则体里的谓词必须是词汇/驱动/规则头谓词（复用 `general_lint`，信息以 `static rule check (lint)` 开头）；
- 新 schema 模板：必须有参考模板、一条推出 `schema(P,<名>)` 的规则、一条 `answer_type` 规则；
- 新库函数：元数据含 `doc/complexity/role/drives/requires/generator/sizes/tests`（≥5 条），`sizes` 满足 N2≥3·N1，`drives` 的每个角色有 `binds(P,角色,A)` 规则，`.py` 里有同名函数且无 Jinja 标记，`algorithms.dl` 里有 `candidate(P,<名>)` 规则，`n+out` 带合法 `output_size`。
测试：`test_precheck.py`（每种遗漏一条）。

**`"complexity": "n+out"`**（时间 = 输入 + 输出）：库元数据必须附带
`"output_size": {"max_factor": F, "constant": C(可省，默认16), "doc": "输出为何有界"}`，含义 `len(输出) ≤ F·输入元素数 + C`（对满足前置条件的输入）。
- `lib_check`：照常在生成器输入上测增长，但①在 N1、N2 两个生成输入上核对输出界（超界即失败）；②增长指数按「输入+输出」规模计算；缺少/非法 `output_size`、或非 `n+out` 却带 `output_size` 都失败。
- 规则：`costs.dl` 里 `n+out` 与 `n` 同样 `fits` 任意规模、可作单驱动；`RANK`（复杂度不退化检查）中与 `n` 同级。
- `problem_cost`（整题计时）：若所用函数含 `n+out`，每个计时输入先核对声明的输出界——超界的输入视为违反前置条件、不计时（与其他“前置条件不满足”同样处理）；增长指数按「输入+输出」规模（`work`）计算，而不是仅按输入长度。只对返回 list/str/tuple/dict 的 `solve` 度量输出（其他返回类型输出记 0，即退化为按输入）。

## 翻译稳健性：`--translate-twice` 与 `--fallback-model`（任务 9）

`general.py solve` 的单题流程现在在 `general.solve_problem(...)` 里（可用假翻译器做单元测试，见 `test_translation.py`）。两个开关默认关闭：

- `--translate-twice`：同一题独立翻译两次（两次调用互不可见）。都能求解 → 用第一次（`rec['twice']['agree_answer_type']` 记录两次的 answer_type 是否一致）；
  恰好一次求解 → 用那一次；两次都失败 → 回到原有流程（对第一次的结果做 ask-back，再带近失提示重试一次）。判据是“求解且全部测试通过”，所以不会因此多出错误代码（`wrong` 仍须为 0）。
- `--fallback-model sonnet`：主模型走完全部重试后状态仍是 `uncovered` 时，用该模型再翻译一次。注意只对 `uncovered` 生效，不处理 `rejected`。
- 日志字段：`path`（`single` / `twice_first` / `twice_second` / `ask_back` / `near_miss_retry` / `fallback_model` / `unsolved`）、`model_calls`（该题花掉的 claude 调用数，含 ask-back）、`twice`、`fallback`。
- 统计脚本：`python summarize_task9.py base twice both` 读 `reports/task9_raw/<配置>_<集合>_<i>.json`，给出每题求解次数、不稳定题、wrong 数、每题调用数。
- 顺手修了一个旧问题：`invalid` 状态下 `reason` 是列表，拼提示时 `'\n'.join` 会抛 TypeError（原先被外层 try 吞成 “extractor error”，等于丢掉重试）。
