"""Create a readable report from benchmark_results.json."""
import json
from collections import Counter
from pathlib import Path

root=Path(__file__).resolve().parent
report=json.loads((root/'benchmark_results.json').read_text())
rows=report['results']
lines=['# Python 代码生成能力实测', '',
       '本报告由本地能力测试生成。单次运行耗时仅代表当前环境，不是容量上限。', '',
       '## 功能结果', '', '| 类别 | 通过 | 总数 |', '| --- | ---: | ---: |']
for category in dict.fromkeys(row['category'] for row in rows):
    group=[r for r in rows if r['category']==category]
    lines.append(f"| {category} | {sum(r['passed'] for r in group)} | {len(group)} |")
lines+=['', '## 规模与耗时', '', '| 测试 | 秒 | 详情 |', '| --- | ---: | --- |']
for row in rows:
    if 'scale' in row['category']:
        lines.append(f"| {row['name']} | {row['seconds']} | {json.dumps(row['detail'],ensure_ascii=False)} |")
lines+=['', '## 失败边界', '']
for row in rows:
    if not row['passed']:
        lines.append(f"- `{row['name']}`：{row['detail']}")
lines+=['', '## 如何理解结果', '',
        'Python body 项测试的是输入代码片段经过模板拼装后能否正确运行，不代表推理机能编写这些算法。',
        'rule_driven_scale 项未提供函数体，由规则推导字段类型和校验要求，由模板生成校验实现，并实际验证合法及非法输入。',
        '规模测试包括生成、写盘、导入和调用；生成的临时文件在测试结束后清理。代码行数包含模板空行。',
        '当前可用于有明确规格及模板的批量 Python 生成；尚不能依据自然语言自动设计任意业务算法。',
        '否定、比较等不支持语法存在被静默误读的问题，应先增强解析器，再扩展规则语言。', '',
        '复现：`.venv/bin/python benchmark.py`，再运行 `.venv/bin/python summarize_benchmark.py`。', '']
(root/'BENCHMARK.md').write_text('\n'.join(lines),encoding='utf-8')
print('\n'.join(lines))
