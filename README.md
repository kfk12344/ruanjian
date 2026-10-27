# 软件工程 2026 · Homework 1 & 2

> 学号：**2412190233**　姓名：**郑俊豪**　班级：计科2402

本仓库包含两次作业的完整提交物：代码、文档、可运行示例与测试。

| 作业 | 主题 | 目录 | 说明 |
|------|------|------|------|
| HW1 | Code Agent（代码审查） | [`hw1-code-agent/`](hw1-code-agent/) | 工具调用循环、5 个工具、记忆、重试、CLI |
| HW2 | Simple Workflow MVP（3 Agent 协作） | [`hw2-workflow/`](hw2-workflow/) | 需求→设计→编码→审查→文档，含分支/回环/并行 |

两次作业共享同一套模型接入层：HW2 直接**复用** HW1 的 `CodeAgent` 作为审查节点，
而不是复制一份代码。

---

## 快速验证（都不需要联网、不需要 API Key）

```bash
# HW1：审查一段故意写坏的代码
cd hw1-code-agent
python main.py review examples/buggy_calculator.py

# HW2：跑完整工作流
cd ../hw2-workflow
python main.py demo
python main.py graph
```

要求 Python 3.9+，**零第三方依赖**（仅标准库），无需 `pip install`。

测试：

```bash
cd hw1-code-agent && python -m unittest discover -s tests   # 55 tests
cd ../hw2-workflow && python -m unittest discover -s tests  # 29 tests
```

---

## 仓库结构

```text
.
├── hw1-code-agent/          # Homework 1
│   ├── main.py              # 入口
│   ├── codeagent/           # 包：config / llm / prompts / tools / memory / agent / cli
│   ├── examples/            # 演示用代码 + 一次真实审查记录
│   ├── tests/               # 55 个测试
│   ├── README.md            # 使用说明
│   └── Design.md            # 设计文档
├── hw2-workflow/            # Homework 2
│   ├── main.py
│   ├── workflow/            # 包：state / messages / nodes / engine / flows / agents / cli
│   ├── examples/sample-run/ # 一次真实运行的完整产物与日志
│   ├── tests/               # 29 个测试
│   ├── README.md
│   └── Design.md
├── capture_examples.py      # 重新生成上面的示例记录（开发辅助）
└── docs/VIDEO_SCRIPT.md     # 1 分钟演示视频脚本（可选提交物）
```

---

## 两次作业的评价维度 → 证据位置

### Homework 1（Code Agent）

| 评分维度 | 实现 | 可直接核对的证据 |
|----------|------|------------------|
| 功能完整性 40% | 完整 Agent 循环、5 个工具、CLI + 交互模式、上下文记忆、重试与降级 | `hw1-code-agent/README.md` §5、`examples/sample-review.md` |
| Agent 架构 30% | 分层（cli→agent→llm/tools/memory）、工具注册表、可替换后端、结构化 `AgentResult` | `hw1-code-agent/Design.md` §2–§5 |
| 代码质量 20% | 全量类型注解、docstring、55 个测试、零依赖 | `tests/`、`python -m unittest discover -s tests` |
| 文档 10% | README（用法）+ Design（决策） | 两个 md 文件 |

### Homework 2（Simple Workflow MVP）

| 评分维度 | 实现 | 可直接核对的证据 |
|----------|------|------------------|
| 流程完整性 40% | 7 步端到端；顺序/条件/回环/并行齐全；真实产物落盘 | `hw2-workflow/examples/sample-run/`（console + 全部产物 + state.json） |
| Agent 协作 30% | 4+1 个 Agent；feedback 消息真正驱动退改；单一写入者的共享状态 | `workflow/agents.py`、`workflow/messages.py`、sample-run 的 `state.json` |
| 可扩展性 20% | 声明式装配；新增 Agent 约 10 行；控制流是属性不是硬编码 | `hw2-workflow/Design.md` §9 |
| 文档 10% | README + Design + Mermaid 架构图/时序图 | 两个 md 文件 |

---

## 设计取舍（一句话版）

- **零依赖**：评审方 clone 下来就能跑，不会卡在 `pip install` 上。
- **离线可复现**：内置确定性模型，演示与测试不依赖网络与 Key；接真实模型只改环境变量。
- **结构化而非打印**：Agent 返回 `AgentResult`，所以 HW2 能把它当节点复用。
- **护栏优先**：所有循环都有 `max_visits` / `max_steps`，宁可失败退出也不静默打转。

---

## 演示视频（可选）

未随仓库提交视频文件。若需要录制，`docs/VIDEO_SCRIPT.md` 提供了 1 分钟的分镜与命令，
照着执行即可（两个 demo 全程约 3 秒，剩余时间用于讲解设计）。

---

## 环境

- Python 3.12（验证），3.9+ 可用；
- Windows / Linux / macOS 均可；
- 真实模型：任何 OpenAI 兼容端点，通过 `CODEAGENT_PROVIDER=openai` + `CODEAGENT_API_KEY` 配置（详见各子项目 README）。
