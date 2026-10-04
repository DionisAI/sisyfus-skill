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

## 2. 创建工程任务

页面左侧填写：

1. **Source / project directory**：现有工程的绝对路径。
2. **Objective**：具体交付物、接口、约束和验收目标。
3. 三个角色模型：
   - Lead：`claude-opus-5-5`
   - Worker：`gpt-6.1-sol`
   - Independent reviewer：`claude-opus-5-5`
4. **Checks JSON**：经你批准的测试命令、测试代码哈希和 PASS/FAIL 判据。
5. Parallelism 默认 2；总调用、迭代、Token、金额和时间预算留空就是 Unlimited。

点击 **Create mission** 只建任务。选中任务后，勾选本地 worker 执行确认，
点击 **Start** 才开始原生 Claude/Codex 调用。两套 CLI 需已有登录状态。

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
