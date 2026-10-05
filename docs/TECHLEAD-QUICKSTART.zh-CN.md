# Opus Tech Lead + Sol 执行：怎么用

这是基于 Sisyfus 0.9.0 的独立开发扩展，入口是 `sisyfus techlead`。
已安装的正式版保持原样。

## 1. 打开操作页面

在本工程里双击 `launch-techlead.command`，或运行：

```sh
cd /Users/xinhuang/github/sisyfus-techlead-rsi
./launch-techlead.command
```

启动器会打开浏览器；终端里保留私有访问链接。终端关闭后服务也会结束。
新的任务状态保存在 `~/Documents/Sisyfus-TechLead/missions`。
启动页面本身不会启动模型。

## 2. 像聊天一样创建任务

首页是浅色中文聊天页面。两套 CLI 需已有登录状态。

1. 点击 **新对话**，直接说你想做什么。发送消息会调用真实只读 Opus；
   它负责澄清、架构和可验收的任务纲要，此时不调用 Sol、也不改工程。
2. 在 **工程与验收** 侧栏选择现有任务，复用它的工程与固定验收方案；
   或填写现有工程路径和经你批准的任务方案文件路径。
   不用在聊天页面编辑 Checks JSON。尚未附上验收时仍可讨论需求。
3. 阅读 Opus 的方案、模块拆分和验收标准；有问题直接继续聊。
4. 工程和验收齐备后，明确确认本地 Agent 执行，再点 **确认方案并开工**。
   执行仍走原来的 Lead → Sol → 固定测试 + 独立 Opus → 集成双重验收链。

聊天方案只是规划草稿，正式可执行 DAG 仍由核心 Lead 生成；原批准目标、
约束和检查保持不变。绑定后的聊天不修改任务合同，需要变更时另建对话。
页面右侧查看并行任务、失败诊断和验收详情；开发者原始状态仍在 `/console`。
总调用、迭代、Token、金额和时间预算默认 Unlimited，其他控制保持原合同。

聊天请求具有固定请求 ID；重复提交同一 ID 不再次调用模型。
在途聊天遇到进程重启保留 UNKNOWN 状态，不自动重发。
草稿和聊天回执保存在任务根目录的 `.chats`，与任务数据库的真源分开。

## 3. 它会怎样干活

```text
Opus：架构、接口、可验收 spec、带依赖和写入范围的任务图
  → Sol：在独立候选副本中执行，无写入冲突的任务可并行
  → 固定测试 + 新的只读 Opus 会话：双重验收
  → 失败：Opus 定位失败层，生成新版修复任务，保留成功结果
  → 集成：合并已验收任务，再做全工程测试和独立 Opus 验收
```

这对应 Architecture / Specification / Delegation / Verification /
Diagnosis / Orchestration 六种能力。测试通过与模型执行完成是不同状态。
源工程保留原样；验收结果位于任务目录的 integration 候选中，不自动覆盖主线。

**Pause** 暂停新调度，在途调用可结束；**Resume** 继续同一任务；
**Stop** 保存停止请求并协作中断。UNKNOWN 表示执行结果尚未确立，保留原请求，
重启时也不会盲目重复调用。

## 4. 先试一个小工程

```sh
cd /Users/xinhuang/github/sisyfus-techlead-rsi
DEMO="$HOME/Documents/Sisyfus-TechLead/polling-$(date +%Y%m%d-%H%M%S)"
PYTHONPATH="$PWD/src" python3 scripts/prepare_lead_fixture.py "$DEMO"
PYTHONPATH="$PWD/src" python3 -m sisyfus techlead up "$DEMO/mission.json" \
  --directory "$DEMO/control" --port 8782 --open --allow-local-workers
```

这个命令会真正调用模型，实现一个带六项独立测试的 `poll_job` 模块。
它演示编排，不代表 Tripo3D CLI 的完整业务已经交付。

## 5. RSI 指的是什么

这里改进的是 Tech Lead 的拆任务、规格和调度流程，不是修改模型权重。
模型提出版本化策略后，必须用冻结的 baseline/candidate 对照和独立 holdout
检查真实结果；没有实测收益就保持旧版本。

完整配置见 [英文运行手册](TECHLEAD-RUNBOOK.md#enable-the-paired-procedure-lab)。
浏览器可操作预先配置的任务并查看策略证据；带独立评估集的任务通过 JSON/CLI
创建。总预算默认 Unlimited；当前启用有限父预算时，RSI 子试验保守停止调度，
主工程仍按自己的预算执行。

Claude 的实际回执模型与请求模型分别显示。当前原生 Codex 接口缺少 Sol
实际模型的执行证明时，actual_model 保持 null，不把配置名称当成证明。

验证状态与交付边界见 [验收清单](TECHLEAD-ACCEPTANCE.md)。
