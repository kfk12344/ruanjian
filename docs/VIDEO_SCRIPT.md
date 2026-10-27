# 1 分钟演示视频脚本（可选提交物）

视频要求 1 分钟以内。下面的分镜按 **60 秒** 排，命令都已在本仓库验证可跑（离线，无需 Key）。
录制工具随意（OBS / Windows 内置录屏 / 剪映）。建议 1080p、终端字号 16–18。

---

## 分镜

| 时间 | 画面 | 操作 / 台词 |
|------|------|-------------|
| 0:00–0:06 | 仓库根目录 | "这是我的两次作业：HW1 是一个能自己读代码的审查 Agent，HW2 是把多个 Agent 编排成软件工程流水线。" |
| 0:06–0:14 | `cd hw1-code-agent` | 说明：零第三方依赖，`python main.py review` 即可运行。 |
| 0:14–0:30 | 执行 `python main.py review examples/buggy_calculator.py -v` | 重点讲三行：`[step 0] read_file`、`[step 1] search_code`、最后 `Verdict: request changes` 与表格里的**行号 + 证据**。"结论不是模型猜的，是它读了文件、grep 了可疑写法之后给的。" |
| 0:30–0:34 | 切到 `cd ../hw2-workflow` | "HW2 要求复用项目 1，所以这里的审查节点就是刚才那个 Agent。" |
| 0:34–0:52 | 执行 `python main.py demo` | 跟着日志讲：`>> requirement` → `design` → `design_gate` → `coding` → `verify`（并行：review + documentation）→ `!! review_gate`（审查不通过）→ `<< review_gate -> coding`（带反馈回退）→ 第二版 → `gate passed` → `summary`。"四种控制结构：顺序、条件、回环、并行，全部有护栏。" |
| 0:52–0:58 | `ls runs/<id>/artifacts` 或打开 `examples/sample-run/` | "每次运行的产物、完整消息、事件日志都落盘，可以事后核对。" |
| 0:58–1:00 | 仓库 README | "代码、README、设计文档都在 GIT 上。" |

---

## 录制前准备

```bash
# 1) 确认环境（无需安装任何依赖）
python --version

# 2) 预热一次，避免首次运行时磁盘缓存造成卡顿
cd hw1-code-agent && python main.py review examples/buggy_calculator.py > /dev/null
cd ../hw2-workflow && python main.py demo --quiet > /dev/null

# 3) 清理上一轮的 runs/，让演示从头开始
rm -rf runs        # Windows: Remove-Item -Recurse -Force runs
```

## 相机位与节奏提示

- 终端宽度 ≥ 110 列，避免日志折行；
- `demo` 全程约 0.05 秒，**必须先讲再看**，否则画面一闪而过；
- 关键暂停点：`review_gate` 失败那两行（`!!` 与 `<<`），这是最能体现"Agent 协作与回环"的地方；
- 若超时，先砍 0:52–0:58 的产物展示，保留两个 demo 与回环讲解。

## 录完自检

- [ ] 视频 ≤ 60 秒
- [ ] 能看清 `Verdict: request changes` 与审查表格
- [ ] 能看清 `review_gate -> coding [feedback]` 与后续第二版通过
- [ ] 提到"复用 HW1 的 Agent"
- [ ] 文件命名符合要求（如 `2412190233郑俊豪-演示.mp4`）
