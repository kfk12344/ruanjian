# CodePilot —— 一个可运行、可扩展的代码审查 Agent

> 软件工程 2026 · Homework 1（Code Agent）· 学号 2412190233 · 郑俊豪

CodePilot 是一个**能自己动手看代码**的代码审查 Agent：它不是在一次调用里"猜"出结论，而是
按 `思考 → 调用工具 → 读观察 → 再思考` 的循环，真的去读文件、grep 可疑写法、跑一段代码验证，
最后产出带**行号、证据、修复建议**的 Markdown 审查报告。

整个项目**零第三方依赖**（只用 Python 标准库），**无需 API Key 即可完整跑通**（内置确定性离线模型），
接上任意 OpenAI 兼容接口即可切换到真实大模型。

---

## 1. 它解决什么问题

普通的 "把代码贴进 Prompt 让模型点评" 有三个硬伤：

| 问题 | CodePilot 的做法 |
|------|------------------|
| 模型看不到完整文件，容易编造行号 | Agent 用 `read_file` 真正读取，报告里的行号来自工具返回 |
| 一次问答就结束，无法验证猜测 | 多轮工具调用，发现可疑点会继续 `search_code` 取证 |
| 结论不可复现、无法评测 | 内置离线确定性模型 + 55 个单元测试，结果可回归 |

演示（离线模式，无需网络）：

```text
$ python main.py review examples/buggy_calculator.py

# Code review: examples/buggy_calculator.py

**Verdict:** request changes
**Lines reviewed:** 73
**Findings:** 10 (3 high / 4 medium / 3 low)

| # | Severity | Line | Finding | Evidence | Suggested fix |
|---|----------|------|---------|----------|---------------|
| 1 | HIGH | 14 | Mutable default argument | `def average(values=[]):` | Default to `None` and create the list/dict inside the function. |
| 2 | HIGH | 24 | `eval()` executes arbitrary code | `return eval(raw)` | Use `ast.literal_eval` for data or an explicit parser. |
| 3 | HIGH | 25 | Bare `except:` swallows every exception | `except:` | Catch the specific exception you can handle. |
...
```

---

## 2. 快速开始

要求：Python 3.9+（开发与验证环境为 3.12），**不需要 pip install**。

```bash
cd hw1-code-agent

# 1) 离线模式：不需要任何 Key，直接跑
python main.py review examples/buggy_calculator.py

# 2) 看 Agent 的每一步思考与工具调用
python main.py review examples/buggy_calculator.py --verbose

# 3) 交互式对话（带上下文记忆）
python main.py chat --target examples/buggy_utils.py

# 4) 查看当前注册了哪些工具
python main.py tools

# 5) 运行测试
python -m unittest discover -s tests
```

### 接入真实大模型

任何兼容 OpenAI `/chat/completions` 的服务都可以（OpenAI、DeepSeek、通义千问兼容模式、本地 vLLM / Ollama）：

```bash
# Linux / macOS
export CODEAGENT_PROVIDER=openai
export CODEAGENT_API_KEY=sk-xxxx
export CODEAGENT_BASE_URL=https://api.deepseek.com/v1
export CODEAGENT_MODEL=deepseek-chat

# Windows PowerShell
$env:CODEAGENT_PROVIDER="openai"
$env:CODEAGENT_API_KEY="sk-xxxx"
$env:CODEAGENT_BASE_URL="https://api.deepseek.com/v1"
$env:CODEAGENT_MODEL="deepseek-chat"

python main.py review examples/buggy_calculator.py -v
```

`CODEAGENT_API_KEY` 未设置时会自动回落到离线模型，**不会因为缺 Key 而崩溃**。

---

## 3. 命令一览

| 命令 | 作用 |
|------|------|
| `python main.py review <文件>` | 审查一个文件，输出 Markdown 报告 |
| `review --verbose / -v` | 同时打印 Agent 的思考、工具调用与观察结果 |
| `review --json` | 输出机器可读 JSON（便于在 CI 或 HW2 中复用） |
| `review --save reports` | 把报告落盘为 `reports/<文件名>-<时间戳>.md` |
| `review --focus "重点关注并发"` | 追加针对性审查要求 |
| `python main.py chat [--target 文件]` | 交互式问答，支持 `/reset`、`/memory` |
| `python main.py tools` | 列出工具签名与说明 |

---

## 4. 目录结构

```text
hw1-code-agent/
├── main.py                    # 入口：python main.py <子命令>
├── codeagent/
│   ├── __init__.py            # 对外导出的公共 API
│   ├── config.py              # 环境变量 → 不可变 Settings
│   ├── llm.py                 # 三种模型后端 + 离线审查规则引擎
│   ├── prompts.py             # 系统提示词（由工具注册表动态生成）
│   ├── tools.py               # 工具层与路径沙箱
│   ├── memory.py              # 字符预算 + 摘要素的对话记忆
│   ├── agent.py               # Agent 循环 / JSON 解析 / 重试
│   └── cli.py                 # argparse 命令行
├── examples/
│   ├── buggy_calculator.py    # 演示用"坏代码"
│   └── buggy_utils.py
├── tests/                     # 55 个单元测试
│   ├── _support.py
│   ├── test_tools.py
│   ├── test_agent.py
│   ├── test_memory.py
│   └── test_llm.py
├── README.md
└── Design.md
```

---

## 5. 核心实现要点

### 5.1 Agent 循环

```text
系统提示词(含工具清单) + 用户任务
        │
        ▼
   ┌─────────────┐   返回 JSON：{thought, action, action_input}
   │  LLM 调用    │ ─────────────────────────────┐
   └─────────────┘                              │
        ▲                                       ▼
        │                             ┌──────────────────┐
        │                             │ 校验 JSON / 纠错  │
        │                             └──────────────────┘
        │                                       │
        │                                       ▼
        │                             ┌──────────────────┐
        └──── OBSERVATION[tool] ───── │ 执行单个工具      │
                                      └──────────────────┘
                                                │
                          返回 {thought, final_answer} → 结束
```

- 每轮**只允许一个工具调用**，避免模型一次返回多个动作导致的执行顺序歧义。
- 模型输出必须是**单个 JSON 对象**；解析器会剥掉 ```json 围栏、跳过前置寒暄，并用括号配对扫描
  找出第一个完整对象（字符串里的 `{}` 不会误判）。
- 连续 3 次无法解析才终止，并保留原始输出便于排查。

### 5.2 工具沙箱

| 工具 | 说明 | 安全措施 |
|------|------|----------|
| `list_files` | 列目录，glob 过滤 | 结果上限 200 条 |
| `read_file` | 带行号读取，支持窗口 | 行数上限 2000 |
| `search_code` | 正则搜索，返回 `文件:行:内容` | 非法正则报错而非崩溃，命中上限 80 |
| `run_python` | 执行代码片段并捕获输出 | 写入工作区临时文件、独立子进程、超时、可用 `CODEAGENT_ALLOW_EXEC=0` 关闭 |
| `run_python_file` | 执行工作区内已有 `.py` | 同上 |

所有路径先 `resolve()` 再校验是否仍在工作区根目录内，`..` 逃逸、绝对路径外指都会被拒绝并
作为 `ERROR:` 观察返回给模型，**不会让异常穿透到循环外**。

### 5.3 上下文记忆

`ConversationMemory` 以**字符**为预算（默认 24000）而非 token，避免引入分词器依赖：

- 超出预算时按**完整的一问一答**为单位淘汰，绝不留下孤立的 assistant 消息（严格服务商会因此报错）；
- 被淘汰的内容压成摘要保留在 `[EARLIER CONTEXT DIGEST]` 中，长会话仍能记住早期结论；
- `chat` 模式复用同一份记忆，`/memory` 可查看、`/reset` 可清空。

### 5.4 错误处理与重试

| 故障 | 处理 |
|------|------|
| 网络 / 5xx | 指数退避重试（默认 3 次，`CODEAGENT_MAX_RETRIES`） |
| 模型返回非 JSON | 注入纠错提示重试，3 次后降级为用户可见的失败说明 |
| 工具名不存在 | 返回可用工具列表作为观察，模型自行纠正 |
| 工具抛异常 | 统一转成 `ERROR:` 字符串，循环继续 |
| 步数耗尽 | 停止并汇总已收集的证据，而不是抛异常 |

### 5.5 离线模式（可复现的演示与测试）

没有 API Key 时使用 `MockLLM`：它按照与真实模型**相同的 ReAct 协议**输出 JSON，
依次调用 `read_file` → `search_code` → 产出最终报告，报告内容由一组真实审查规则
（裸 `except`、`eval`、可变默认参数、`shell=True`、被 `pass` 吞掉的异常……）从**读到的源码**中提取，
因此行号、证据都是真实的，可以直接用于回归测试。

---

## 6. 测试

```text
$ python -m unittest discover -s tests
Ran 55 tests in 0.19s
OK
```

覆盖范围：

- **工具层**：路径逃逸拒绝、非法正则、行号窗口、超时/非零退出、关闭执行开关；
- **循环层**：正常两轮结束、脏 JSON 纠正、3 次失败终止、未知工具、缺参、步数上限、provider 抖动重试；
- **解析层**：围栏、前后夹带文本、字符串内花括号、转义引号、括号不配对；
- **记忆层**：预算淘汰整轮、摘要保留关键词、重置；
- **模型层**：provider 自动探测、离线规则命中/未命中、退避重试。

---

## 7. 与 Homework 2 的衔接

HW2 的 Workflow 直接**复用本项目作为"审查节点"**：`hw2-workflow/workflow/adapters/hw1_reviewer.py`
把 `CodeAgent` 包装成一个节点，流程为 `需求 → 设计 → 编码 → 审查 → 汇总`，审查不通过时回退到编码重试。
这满足 HW2 "从项目 1 复用" 的要求，也证明本项目的接口是为 **被编排** 而设计的：
`CodeAgent.review()` 返回结构化 `AgentResult`，而不是只往终端打印。

---

## 8. 已知限制

- `run_python` 只做**路径隔离 + 超时**，不是操作系统级沙箱；生产环境应放进容器或 `seccomp` 环境。
- 离线规则引擎覆盖常见 Python 反模式，不做跨函数数据流分析（真正的语义审查需要真实模型）。
- 审查以单文件为主；跨文件调用链目前依靠 `search_code` 取证，尚未构建符号索引。
