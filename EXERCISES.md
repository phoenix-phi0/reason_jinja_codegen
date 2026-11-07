# 14 道 Python 编程题实测

结果：14/14 题通过，833 项断言通过。与原有测试一起运行，21/21 个测试方法通过。

| 题目 | 要求与重点检查 | 断言数 |
| --- | --- | ---: |
| 二分查找 | 返回首次匹配位置；空列表、重复值、100 组固定种子随机输入 | 101 |
| 合并区间 | 重叠、相接、包含、逆序区间；随机验证覆盖范围 | 104 |
| 拓扑排序 | DAG 顺序、仅作为邻居出现的节点、自环及一般环 | 104 |
| 最短路径 | BFS 路径、不可达、起终点相同、带环图 | 5 |
| CSV 分类汇总 | Decimal 精度、带逗号类别、负数、空表及错误数据 | 5 |
| 滑动平均 | 迭代器、窗口边界、非法窗口、随机对照 | 56 |
| 嵌套列表展开 | 保留字符串和 None，展开列表及元组，1,500 层嵌套 | 3 |
| 迭代器分块 | 尾部不足一块、空输入、非法块大小、重组一致性 | 44 |
| 失败重试 | 成功退出、最大尝试次数、异常传播、非法次数 | 6 |
| LRU 缓存 | 更新访问顺序、淘汰、缺失键，与独立参考状态逐步对照 | 278 |
| 银行账户 | Decimal 存取、余额不足、负数、NaN 和 Infinity | 12 |
| 异步并发映射 | 结果顺序、并发上限、空输入、非法上限、异常传播 | 5 |
| JSON 配置校验 | host、端口范围、拒绝 bool 端口、格式错误 | 8 |
| 保序去重 | 空输入、重复值、迭代器、100 组随机对照 | 102 |

## 生成方式

这轮新增 `packs/exercises`，其中 Datalog 根据 task、supported、destination 推导 algorithm 和 emit，再由 Jinja include 选中对应算法模板。`examples/exercises.json` 只声明题型和输出路径，data 为空，不携带算法函数体。

算法实现由本轮预先写入模板库，测试输入指定题型标识；没有进行自然语言理解或未知算法合成。这些结果说明当前框架能够正确选择模板、生成及运行这 14 类 Python 程序，不代表已覆盖每类题目的所有输入。异步异常测试仅检查异常传播，未验证任务取消策略；CSV 题按 category、amount 固定列名处理，金额题没有实现账户间转账。

## 复现与产物

```bash
# 在本仓库根目录执行
.venv/bin/python generate.py examples/exercises.json --pack packs/exercises --out generated/exercises
.venv/bin/python test_exercises.py
.venv/bin/python -m unittest -v
```

- 输入：`examples/exercises.json`
- 规则与模板：`packs/exercises/`
- 生成代码：`generated/exercises/`
- 自动测试：`test_exercises.py`（测试时重新生成到临时目录，验证当前模板）
- 原始测试结果：`exercise_results.json`

没有修改推理机或原来的 Python 生成模板。之前发现的否定、数值比较、复杂常量解析问题依然存在；本轮只使用正向规则和简单常量。
