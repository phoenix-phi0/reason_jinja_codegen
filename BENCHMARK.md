# Python 代码生成能力实测

本报告由本地能力测试生成。单次运行耗时仅代表当前环境，不是容量上限。

## 功能结果

| 类别 | 通过 | 总数 |
| --- | ---: | ---: |
| python_body | 14 | 14 |
| python_structure | 7 | 7 |
| inference | 6 | 6 |
| boundary_probe | 0 | 3 |
| scale | 3 | 3 |
| rule_driven_scale | 2 | 2 |
| inference_scale | 1 | 1 |

## 规模与耗时

| 测试 | 秒 | 详情 |
| --- | ---: | --- |
| 10_modules | 0.0108 | {"modules": 10, "functions": 100, "lines": 550, "bytes": 3150, "runtime_calls": 100} |
| 100_modules | 0.0508 | {"modules": 100, "functions": 1000, "lines": 5500, "bytes": 31500, "runtime_calls": 1000} |
| 1000_modules | 1.1899 | {"modules": 1000, "functions": 10000, "lines": 55000, "bytes": 315000, "runtime_calls": 10000} |
| 100_inferred_models | 0.7729 | {"models": 100, "fields": 1000, "inferred_types": 1000, "inferred_checks": 2000, "lines": 13100} |
| 1000_inferred_models | 97.3082 | {"models": 1000, "fields": 10000, "inferred_types": 10000, "inferred_checks": 20000, "lines": 131000} |
| 100_node_closure | 0.0105 | {"nodes": 100, "derived_pairs": 4950} |

## 失败边界

- `negation`：AssertionError: expected {('a',)}, got {('b',)}
- `comparison`：AssertionError: expected {('5',)}, got {('2',), ('5',)}
- `quoted_comma`：AssertionError: expected {('a,b',)}, got {('a', 'b')}

## 如何理解结果

Python body 项测试的是输入代码片段经过模板拼装后能否正确运行，不代表推理机能编写这些算法。
rule_driven_scale 项未提供函数体，由规则推导字段类型和校验要求，由模板生成校验实现，并实际验证合法及非法输入。
规模测试包括生成、写盘、导入和调用；生成的临时文件在测试结束后清理。代码行数包含模板空行。
当前可用于有明确规格及模板的批量 Python 生成；尚不能依据自然语言自动设计任意业务算法。
否定、比较等不支持语法存在被静默误读的问题，应先增强解析器，再扩展规则语言。

复现：`.venv/bin/python benchmark.py`，再运行 `.venv/bin/python summarize_benchmark.py`。
