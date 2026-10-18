# 自动生成可读研究报告 — 2026-10-06

## 产品结果与当前验收边界

本轮实现 ResearchEngine / Observatory 的自动报告产出层。读者先看到自己
的问题和直白答案，再读机制、实际测量、条件测算、研究发现和下一步；
机器状态与合同检查保留在审计层，研究流程完成和问题得到证实分别表达。

链路：**冻结证据 → 原生 Opus 撰写 → 新会话独立 Opus 复核 → 控制器发布**。
现有可读报告界面和图谱复用；另外保存完整 Markdown、证据包、模型回执、
审稿结果、上一版 sidecar 和发布 manifest。

代码与协议夹具的验证已实施；真实无工具 Opus 撰写/审稿，以及原 Entropy × XYZ
报告的自动再生成，仍待订阅登录参数兼容性决定。该原生验收是剩余必需检查，
本文件不将其记为完成。

开发分支：`codex/techlead-report-pipeline`。安装版、既有脏工作和原研究材料保留。
原研究页面：[Entropy × XYZ 报告](http://127.0.0.1:8756/index.html?view=report#seq=26)。
83 个原文件已按冻结 SHA 验证保持原样；没有新市场取样、账户操作、下单或 RSI 晋升。

## 实施范围

- 新增 `research_v2/reporting.py` 协调器，复用 ROOT 的 AutonomyStore、Journal、
  原生 driver 和 reader schema。默认关闭；不可变 TaskSpec 的
  `metadata.reader_reporting` 明确选择启用，历史运行可通过确认的命令配置。
- 在外层 CLI 的 execute、settle、finalize、wake --execute 完成写入后调用。
  policy 在研究写入前校验；保留研究 stdout 与非零退出码，报告结果单行 JSON
  写到 stderr。研究成功而报告失败时退出 5；已在生成的报告返回 IN_FLIGHT，
  不重复启动作者。读取、GET、刷新、纯引擎渲染不调用模型。
- 固定作者/审稿人 `claude-opus-5-5`，不同新会话、工具列表为空，完成回执和
  运行时模型身份均校验。模型只提议叙述；控制器保留原问题、来源、事件类型、
  claim 状态、snapshot/event basis。数字由冻结 fact 引用替换；独立审稿检查
  语义、分母、假设和盈利外推，数字来源绑定本身不是经济结论。
- 单运行单活动 job，原生 reservation/lease、UNKNOWN fence、停止/暂停、
  人工说明的 UNKNOWN 处置、缓存和崩溃恢复。原生调用不盲重试。
- 证据、候选、审稿、Markdown、sidecar 都有漂移检查。锁内 publication claim
  与原子替换，仅更新中文 reader，保留其他 locale/key。纯渲染保留 replay frames，
  不追加研究事件。

引擎、reducer、verifier、workspace、Journal、Observatory Python 和界面模板本轮
保持原样。独立 native TechLead Mission/chat 到此研究管线的桥接另属后续范围。

## 原生开发及独立复核记录

材料传输仅使用用户本轮明确允许的最小相关源码、测试、合同；报告材料是历史
公开研究样本，不含凭据和私人账户。

- 原生 Opus Lead：`97687bdd-c455-41ff-8bb3-2a3f7f5b312c`，身份已 attested；
  设计修订进入冻结合同。
- 原生 Sol 实现及两次局部修复均有 COMPLETED 回执，请求 `gpt-6.1-sol`。
  该 driver 的实际模型遥测为 null，故不将请求名称作为运行时身份证明。
- 首次独立 Opus 实现复核：`83bed731-cecf-4cb5-84c9-41635265fde2`，FAIL；
  发现发布擦除历史帧、SQLite 异常突破研究退出边界、活动报告被误报为失败。
  三项均保留失败与诊断后进行最小局部修复。
- 最终新会话 Opus 复核：`0ddf8305-c62d-4b46-a088-ee697fda392e`，请求与运行时
  身份均为 `claude-opus-5-5`，**PASS / implementation_only**，三个 blocker 已解决，
  没有新 blocker。控制器另行计算核对其阅读的 stage/main 源码 SHA 和冻结期待。
  源码复核输出是普通文字加 JSON verdict，保留原文并提取结构化记录；它不是
  生产报告作者/审稿的 strict JSON 协议验收。实际原生报告生成单列待验。

## Hai TDD 证据

### Target Behavior

终结的显式启用研究自动产生可读报告，但报告失败不改变研究结论、stdout、
退出优先级或既有图谱/历史。重复触发不重复调用；审稿及发布持续 fail-closed。

### RED

- 最初冻结行为检查：`red-frozen-final.log`，46 failed / 3 passed；正确暴露缺失的
  报告 lifecycle/API。`red-automatic-valid.log` 暴露 terminal settle 后缺少 reader。
- 交付检查：`delivery-red-frozen.log`，3 failed / 1 passed，缺少 retained Markdown、
  可读中文 scope、原生预约之前的 owner crash fencing；stop/publish 顺序已有保护。
- 复核追加检查：`tests/test_reader_pipeline_review.py`；`review-blockers-red.log`
  为 4 failed / 1 passed，分别复现三个复核缺陷；中断传播保护已通过。
- 命令均为保留产物的 pytest：`PYTHONPATH=src SISYFUS_AUTO_SERVE=0
  SISYFUS_AUTO_OPEN=0 <release-venv>/bin/python
  -m pytest`，具体测试集与结果日志一起保留。
- 一个初始 test fixture 对只读 engine.task 赋值，修正的是 setup：创建包含坏
  policy 的新 TaskSpec。同样的非零/原事件不变断言保留；v1 原字节未丢失。
  v2/v3 冻结 manifest 和 `acceptance-amendments.md` 记录全部差异，没有放宽检查。
- 集成 helper 曾引用错误的 baseline 文件路径，hash gate 在复制前失败；紧随的
  检查仍跑旧候选，4 failed / 54 passed。日志保留为
  `review-repair-preintegration.log`；修正 helper 路径后重新过 gate 和验收。

### GREEN

- 实现最小外层报告协调器与 no-tools 模式，不将模型引入引擎或 verifier。
  文本/数字/结构证据校验、独立审稿、retained Markdown 和 Journal 生命周期
  对应冻结检查。
- 三个复核修复只涉及 reporting.py / cli.py：渲染传入事件纯 frames；报告边界
  捕获 Exception 并保留 BaseException；自动路径只将 IN_FLIGHT 变成非错误结果。
- 最终专项命令：`python -m pytest tests/test_reader_pipeline.py
  tests/test_reader_pipeline_delivery.py tests/test_reader_pipeline_review.py
  tests/workers/test_report_no_tools.py -q`（上述已验证环境）。
- 控制器实测：**58 passed**，`focused-green-v3.log`。
- 控制器全集实测：**726 passed in 252.23s**，`candidate-regressions-v3.log`。
  测试集包括 tests/workers、activity_monitor、observatory_live、monitor、
  visual_consistency、research models/engine/verifier/waits/observatory/CLI/
  command skill/branch rollback、graph_redesign、reader_report、三个 pipeline 文件。
  完整命令采用上述环境和 `-m pytest <这些路径> -q`，不以模型声称通过替代检查。
- 完成 gate：`integration-acceptance.json`，
  `LOCAL_IMPLEMENTATION_AND_FIXTURE_PASS_NATIVE_ACCEPTANCE_PENDING`。

### REFACTOR

- Refactor done: no。没有跨模块重构；按独立发现进行最小根因修复。
- 冻结 v3 与生产源 SHA gate 完整，原引擎/审计/UI 期待不变。
- 重验包括所有本轮专项、native driver、研究 CLI/状态/verifier、live loopback
  server、历史图谱和 reader UI 回归；实测 **726 passed**，`git diff --check`
  无诊断；结果与命令日志保留。没有借测试修订改变旧验收结果。

### Next Behavior

批准或选择登录参数兼容方案后，真实新运行完成无工具作者与独立审稿，核验
工具清单、Opus 身份、不同会话、自动触发、缓存和发布，再自动生成原公开研究
报告。该生成不新增市场/盈利证据。确认前保留 `--bare` 的冻结期待及原报告。

## 浏览器证据

本轮自动产出的 reader 已使用 **ScriptedOpus 协议夹具** 实测：1280px、460px
无横向页面溢出；问题/答案/过程可读；审计默认收起且可展开；历史/最新切换；
无 console error/warning。HTTP 浏览期间协议调用总数保持 2，真实 provider 调用 0。

截图在 `pipeline-fixture-wide-v2.png` / `pipeline-fixture-narrow.png`，凭据为
`gui-fixture-receipt.json`。这不是原生模型或市场盈利证明。此 GUI server 会纯渲染
历史帧，所以静态 publication 帧保留另有直接 JSON 回归约束。临时 tab/server
已关闭，原 8756 用户页面保留。

## 登录兼容性与必需剩余检查

安装的 Claude `--bare` 跳过 OAuth。只读 `--bare auth status --json` 返回
loggedIn:false / authMethod:none；这个探测没有调用模型，也没有制造 UNKNOWN
reservation。普通只读原生 Lead/reviewer 使用既有订阅登录成功。

已经询问用户是否同意订阅兼容参数修订：保留既有登录，仍关闭 tools、hooks、
skills、项目配置，验证真实 init tools=[]，独立审稿和发布门槛原样保留。该决定
尚待回复。没有读取/导出 token、变更凭据，或偷偷修改 `--bare` 验收断言。

待验项：真实 no-tools init 和身份 → 新 terminal opt-in 运行自动生成 → 历史
Entropy × XYZ 自动生成 → 真实报告 GUI 与事件/原数据完整性。即使源码复核 PASS
和本地回归全绿，也只代表实现 gate，而不是上述 end-to-end gate 已通过。

## 留存位置

所有本轮 freeze、失败、原生回执、隔离源码提议、SHA gate、专项/回归日志、
新 fixture、公开研究 facts 和截图：
`artifacts/techlead/report-pipeline-20261006/`。

合同：`docs/TECHLEAD-REPORT-PIPELINE-CONTRACT.md`。
