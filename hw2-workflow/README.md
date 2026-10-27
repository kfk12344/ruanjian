# Mini SE Workflow —— 3 个 Agent 协作的软件工程流水线

> 软件工程 2026 · Homework 2（Simple Workflow MVP）· 学号 2412190233 · 郑俊豪

本作业实现一个**可运行的 Mini SE 流程**：需求 Agent 写需求 → 设计 Agent 出设计 → 编码 Agent 写代码
→ **直接复用 Homework 1 的 CodeAgent 做审查** → 审查不通过就带着反馈回到编码重试 → 通过后汇总。

流程里有**顺序执行、条件分支、回退循环、并行执行**四种控制结构，全程有结构化日志与状态快照，
零第三方依赖，**不需要 API Key 即可完整跑通**。

---

## 1. 一次真实运行

```text
$ python main.py demo

  0.003s  == mini-se run 7070f876
           task: Build a small English word/number counter module with input validation.
  0.003s  >> requirement  (visit 1)
  0.004s     msg requirement -> workflow [result] # Requirements: Build a small English word/number...
  0.004s  OK requirement  0ms  739 chars
  0.004s  >> design  (visit 1)
  0.005s  OK design  0ms  701 chars
  0.005s  >> design_gate  (visit 1)
  0.006s     msg design_gate -> workflow [result] gate passed
  0.006s  OK design_gate  0ms  0 chars
  0.007s  >> coding  (visit 1)
  0.009s  OK coding  1ms  354 chars
  0.009s  >> verify  (visit 1)                 <- 审查 + 文档并行
  0.019s     msg review -> review_gate [result] request changes
  0.020s     msg documentation -> workflow [result] # Usage: ...
  0.021s  OK verify  10ms  1242 chars
  0.021s  >> review_gate  (visit 1)
  0.021s     msg review_gate -> coding [feedback] reviewer requested changes; sending the code back for a fix
  0.021s  !! review_gate  reviewer requested changes; sending the code back for a fix
  0.021s  << review_gate -> coding  (reviewer requested changes; ...)
  0.021s  >> coding  (visit 2)                 <- 带着反馈重写
  0.023s  OK coding  1ms  1039 chars
  0.023s  >> verify  (visit 2)
  0.029s     msg review -> review_gate [result] approve with nits
  0.030s  OK verify  5ms  870 chars
  0.030s  >> review_gate  (visit 2)
  0.031s     msg review_gate -> workflow [result] gate passed
  0.031s  OK review_gate  0ms  0 chars
  0.031s  >> summary  (visit 1)
  0.032s  OK summary  0ms  373 chars
  0.032s  == finished: completed in 0.03s

run 7070f876: completed in 0.03s
steps: requirement -> design -> design_gate -> coding -> verify -> coding -> verify -> review_gate -> summary
artifacts: code, code_file, code_path, design, docs, requirement, review, review_verdict, summary
issues: review_gate: reviewer requested changes; sending the code back for a fix
run directory: runs\7070f876
```

一次完整运行的全部产物都在 `runs/<run_id>/`：

```text
runs/7070f876/
├── artifacts/
│   ├── requirement.md   # 需求 Agent 产出
│   ├── design.md        # 设计 Agent 产出
│   ├── code.py          # 编码 Agent 产出（可直接执行）
│   ├── review.md        # HW1 CodeAgent 的审查报告
│   ├── docs.md          # 文档 Agent 产出
│   └── summary.md       # 汇总
├── state.json           # 完整状态快照（含所有 Agent 间消息）
└── trace.jsonl          # 逐事件审计日志
```

上面这段真实输出也保存在 `examples/sample-run/`（`console.txt` + 全部产物 + `state.json`）。

---

## 2. 快速开始

要求：Python 3.9+（验证环境 3.12），**不需要 pip install**。

```bash
cd hw2-workflow

python main.py demo                      # 跑内置演示任务（离线，无需 Key）
python main.py run "做一个 CSV 去重工具"   # 跑你自己的任务
python main.py graph                     # 打印流程定义与 Mermaid 图
python -m unittest discover -s tests     # 29 个测试
```

### 接入真实大模型

```bash
# 复用 Homework 1 的模型后端，环境变量也一致
export CODEAGENT_PROVIDER=openai
export CODEAGENT_API_KEY=sk-xxxx
export CODEAGENT_BASE_URL=https://api.deepseek.com/v1
export CODEAGENT_MODEL=deepseek-chat

python main.py run "做一个 CSV 去重工具"
```

未配置 Key 时默认使用**确定性离线模型**：它按真实 Agent 的协议产出需求/设计/代码，
并且第一版代码里**故意留了一个裸 `except`**，用来触发"审查不通过 → 回退修改"的循环，
所以演示是真实走完整个控制流的，不是假数据。

---

## 3. 流程定义

```text
                  ┌──────────────┐
                  │ requirement  │  需求 Agent
                  └──────┬───────┘
                         ▼
                  ┌──────────────┐   ┌─────────────┐
                  │   design     │◀──│ design_gate │ 不通过则回退
                  └──────┬───────┘   └─────────────┘
                         ▼
                  ┌──────────────┐
                  │   coding     │◀──────────────┐
                  └──────┬───────┘               │
                         ▼                       │
        ┌────────────────────────────────┐       │
        │  verify (并行)                  │       │
        │  ├── review  ← HW1 CodeAgent   │       │
        │  └── documentation             │       │
        └────────────────┬───────────────┘       │
                         ▼                       │
                  ┌──────────────┐               │
                  │ review_gate  │───────────────┘ 不通过则带反馈回退
                  └──────┬───────┘
                         ▼
                  ┌──────────────┐
                  │   summary    │
                  └──────────────┘
```

| # | 步骤 | 类型 | 作用 | 失败时 |
|---|------|------|------|--------|
| 1 | `requirement` | Agent | 把任务转成带 FR/NFR/AC 的需求文档 | 中止 |
| 2 | `design` | Agent | 产出架构、模块、数据流、测试计划 | 中止 |
| 3 | `design_gate` | 质量门 | 校验设计是否结构化（≥3 个章节、≥150 字符） | 回退 `design`（最多 3 次） |
| 4 | `coding` | Agent | 产出代码并落盘到 `artifacts/code.py` | 中止 |
| 5 | `verify` | **并行** | `review`（HW1 Agent）‖ `documentation` | 中止 |
| 6 | `review_gate` | 质量门 | 审查结论是否为 `request changes` | 回退 `coding`（最多 3 次） |
| 7 | `summary` | Agent | 汇总本轮产出、审查意见与风险 | 中止 |

`max_visits` 是**循环护栏**：任何一个步骤被重复执行到上限，整轮以 `failed` 结束并写明原因，
不会出现"三个 Agent 互相甩锅直到天亮"。

---

## 4. 目录结构

```text
hw2-workflow/
├── main.py                        # 入口
├── workflow/
│   ├── __init__.py
│   ├── state.py                   # 共享状态：artifacts / messages / visits
│   ├── messages.py                # Agent 间消息（handoff / result / feedback / error）
│   ├── nodes.py                   # Node / LLMNode / GateNode / FunctionNode
│   ├── engine.py                  # 流程解释器：顺序、条件、回退、并行、护栏
│   ├── flows.py                   # Mini SE 流程装配 + 两个质量门
│   ├── agents.py                  # 4 个 Agent + 复用 HW1 的 ReviewNode
│   ├── llm_bridge.py              # 定位并复用 hw1-code-agent（找不到时降级）
│   ├── tracing.py                 # 控制台轨迹 + trace.jsonl
│   └── cli.py                     # run / demo / graph
├── examples/sample-run/           # 一次真实运行的完整产物
├── tests/                         # 29 个测试
├── README.md
└── Design.md
```

---

## 5. 设计要点

### 5.1 状态共享：单一写入者

`WorkflowState` 保存 `artifacts`（产物）、`messages`（Agent 间消息）、`visits`（步数）与 `errors`。
**节点只读状态，返回 `NodeResult`；引擎是唯一写入者。** 这条规则带来两个好处：

1. 并行步骤不需要锁——节点不写共享状态；
2. 事件顺序确定——引擎按声明顺序合并并行结果，`trace.jsonl` 可复现。

### 5.2 Agent 间通信

Agent 之间不直接互相调用，而是发消息：

| 消息类型 | 语义 | 例子 |
|----------|------|------|
| `handoff` | 把工作交给下游 | design → coding |
| `result` | 汇报产物摘要 | review → review_gate |
| `feedback` | 退回并要求修改 | review_gate → coding |
| `error` | 失败说明 | 任何节点 |

反馈消息会**改变下游行为**：`CodingNode` 会把发给自己的 `feedback` 追加到提示词里
（`## code_feedback`），离线模型据此输出修复版本。这不是装饰性的消息传递。

### 5.3 控制流

| 能力 | 实现 |
|------|------|
| 顺序 | 步骤列表自然顺序 |
| 条件 | `Step.when = lambda state: ...`，为假则跳过 |
| 回退循环 | `Step.on_fail = "<上游步骤名>"`，失败即跳转 |
| 并行 | `ParallelStep([...])`，`ThreadPoolExecutor` 并发，结果按声明顺序合并 |
| 循环护栏 | `max_visits` + 全局 `max_steps` |
| 重试 | 节点抛异常时按 `retries` 重试，仍失败则转成 `step_failed` |

### 5.4 可观测性

- 控制台：每一步的开始/结束/耗时/字符数、每条 Agent 消息、每次跳转与重试；
- `trace.jsonl`：结构化事件，便于事后分析（例如统计每个 Agent 的耗时）；
- `state.json`：完整快照，包含全部消息与产物；
- ASCII 标记（`>>`、`OK`、`!!`、`<<`）而不是 emoji —— Windows 控制台默认不是 UTF-8，
  用 emoji 会直接抛 `UnicodeEncodeError`。这是被真实环境逼出来的选择。

### 5.5 复用 Homework 1

`workflow/llm_bridge.py` 会在仓库里定位 `hw1-code-agent/`：

- 找到 → 导入真实的 `CodeAgent`、`create_llm`、`load_settings`，审查步骤就是**项目 1 的同一个 Agent**；
- 找不到 → 打印警告并退化为内置规则扫描器，工作流仍能跑通。

这样既满足"从项目 1 复用"，又不会因为目录缺失就直接崩掉。

### 5.6 错误恢复

| 故障 | 行为 |
|------|------|
| 模型调用抛异常 | 节点重试（默认 2 次），仍失败则步骤失败 |
| 节点返回失败 | 有 `on_fail` 就跳转，否则整轮 `failed` |
| 并行节点部分失败 | 合并结果但整步判失败，触发 `on_fail` |
| 护栏触发 | 立即停止并记录 `loop guard` 原因 |
| CLI 层异常 | 打印一行原因，返回非零退出码，不抛 traceback |

---

## 6. 测试

```text
$ python -m unittest discover -s tests
Ran 29 tests in 0.21s
OK
```

- **引擎**：顺序、条件跳过、回退跳转、循环护栏、异常重试、并行合并、并行失败、全局步数上限、
  重复标签校验、非法跳转目标校验、trace 落盘、describe/mermaid 输出；
- **流程**：端到端跑通、审查失败一次后修复、代码文件可编译、反馈消息真的发给编码 Agent、
  trace 中出现 jump、状态可序列化；
- **质量门**：空/过短/无结构/合格设计，四种输入；审查通过/不通过/缺失。

---

## 7. 与评分标准的对应

| 维度 | 权重 | 对应实现 |
|------|------|----------|
| 流程完整性 | 40% | 端到端跑通并留下真实产物；顺序/分支/循环/并行齐备；`examples/sample-run` 可核对 |
| Agent 协作 | 30% | 4 个 Agent + 1 个复用 Agent；消息驱动的退改；单一写入者的共享状态 |
| 可扩展性 | 20% | 新增 Agent = 一个 `LLMNode`；新增控制流 = 一个 `Step` 属性；`Workflow` 声明式装配 |
| 文档 | 10% | README（用法）+ Design（决策与时序）+ 图表 |

---

## 8. 已知限制

- 并行基于线程，适合 I/O 密集的模型调用；CPU 密集任务应换成进程池；
- 没有持久化与断点续跑：进程中断后只能重跑整轮（状态快照可用于人工恢复）；
- 质量门是**结构化校验**而非语义评审（语义判断交给审查 Agent）；
- 离线模型的产物是模板，接真实模型才有真实的代码质量。
