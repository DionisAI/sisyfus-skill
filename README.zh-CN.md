# sisyfus-research — 验证者门控的自主研究 Agent Skill

[English](README.md) | **简体中文**

> Planner 可以提出实验,但只有预注册的验证者和确定性的 reducer 才能改变研究真相。

**这个仓库本身就是 skill。** 根目录的 [`SKILL.md`](SKILL.md) 是 agent 的入口;
[`references/`](references/) 是 skill 运行所依据的契约文档;
[`templates/`](templates/) 是 TaskSpec 与实验的脚手架。`src/` 下的 Python 引擎是
skill 的确定性后端——agent 通过 `sisyfus` CLI 驱动它,永远不能直接篡改研究状态。

## 这个 skill 做什么

给定一个开放的研究问题,使用本 skill 的 agent 会:

1. 把问题编译成 **TaskSpec**——可证伪的命题、AND/OR 目标图、预注册的验证合约、
   可选的硬预算;
2. 进入循环:提出实验(必须引用已有证据/经验)→ 准入控制 → 执行 →
   **纯代码验证者**把每次观测判为 `PASS / FAIL / INCONCLUSIVE / INVALID / ERROR`
   → 事件溯源的 reducer 提交状态;
3. 沉淀**经验(lessons)**:证据门控、晋升进项目级知识库、按相关性注入之后每个
   run 的规划上下文;
4. 机械地停止:目标证实(`SOLVED`)、目标证伪(`REFUTED`)、或声明的预算耗尽——
   永远不靠感觉收工;
5. 渲染自包含的双语 **HTML 观测台("Arena")**:电竞转播式的探索视图——击杀
   播报、解说席、确定性可视回放、可打印的终局报告。

一切投影都可以从只增的哈希链事件日志重建。`sisyfus research replay` 重推整场
run;`sisyfus research reproduce` 重跑任意 command 证据的哈希锁定测量代码,并在
同一份锁定合约下重新裁决——全程没有模型参与。

## 安装

**一条命令**——skill 和引擎一起装,幂等、无需 sudo、不碰系统 Python:

```bash
curl -fsSL https://raw.githubusercontent.com/DionisAI/sisyfus-skill/main/install.sh | bash
```

安装器会:

1. 把 `SKILL.md` + `references/` + `templates/` 复制进所有检测到的技能目录
   (`~/.claude/skills/`、`~/.agents/skills/`),命名为 `sisyfus-research`;
2. 把引擎装进 `~/.local/share/sisyfus` 并把 CLI 链接到 `~/.local/bin/sisyfus`——
   优先使用专用 venv;在缺少 `python3-venv`/`ensurepip`/pip 的机器上自动降级为
   纯标准库源码安装(sisyfus 零运行时依赖,因此永远不需要 sudo);
3. 校验 `sisyfus --version`,并在 `~/.local/bin` 不在 `PATH` 时给出提示。

`install.sh --uninstall` 可完整卸载(各项目的 `.sisyfus/` 研究状态永不触碰)。

<details>
<summary>手动安装</summary>

Skill:把 `SKILL.md`、`references/`、`templates/` 复制进
`~/.claude/skills/sisyfus-research/`(或你的 agent 扫描的任意技能目录),
或使用 skills CLI:`npx skills add github:DionisAI/sisyfus-skill`。

引擎(纯标准库,Python >= 3.11):

```bash
python3 -m pip install "sisyfus @ git+https://github.com/DionisAI/sisyfus-skill@v0.7.4"
```

`SKILL.md` 自带这项检查,agent 落到干净机器上首次使用时会自行装好引擎。

</details>

## 在 agent 里使用(主要方式)

装好之后,任何支持 skills 的 harness(Claude Code、Codex 等)会自动发现
`sisyfus-research`:

- **显式调用**——直接点名:

  ```text
  /sisyfus-research 验证「0-5c 档被动做市在 Polymarket 是否可行」
  ```

- **自动触发**——用自己的话描述任务即可:「帮我验证这个假设是否成立,要可复现」、
  「用预注册标准回测这个策略」、「对 X 做一次证据驱动的研究」。harness 会根据
  skill 的 frontmatter 描述自动匹配并加载,无需点名。

无论哪种方式,skill 都会端到端接管:缺 CLI 时自举引擎、把你的问题编译成带预注册
验证合约的 TaskSpec、跑完提出 → 验证 → 提交的循环、最后交给你 Arena 报告。
**你永远不需要直接碰 Python。**

没有技能注册表的 harness,可在 `AGENTS.md` 里指向已安装的
`~/.claude/skills/sisyfus-research/SKILL.md`(或把 skill 复制进项目自己的
`.agents/skills/`)。

## 快速上手(CLI,给人和脚本用)

同一个引擎,手动驾驶:

```bash
mkdir /tmp/sisyfus-demo && cd /tmp/sisyfus-demo
sisyfus init                       # 安装 .sisyfus/ 布局 + 项目本地技能副本
sisyfus research demo --root .     # 脚本化演示:失败、分支、恢复、攻克
sisyfus research serve latest --open --root .   # 浏览器里的实时 Arena
sisyfus research replay latest --root .         # 哈希验证整场 run
```

然后阅读 [`SKILL.md`](SKILL.md)——它就是 agent 遵循的操作手册:启动/续跑、研究
循环、判定语义、等待与唤醒、经验沉淀、停止规则、审计命令。

## 仓库布局

```text
SKILL.md          # skill 本体:面向 agent 的操作手册(canonical)
references/       # task-spec / verifier-contract / event-model 契约文档
templates/        # TaskSpec 与实验的 JSON 脚手架
src/sisyfus/      # 确定性引擎:CLI、reducer、验证者、Arena 渲染器
  skill_assets/   # wheel 载荷——根目录 skill 的同步副本(勿直接编辑)
scripts/          # sync_skill_assets.py 保证根目录 skill == wheel 载荷
tests/            # 引擎 + skill 回归测试(pytest -q)
examples/         # v0.6 legacy 目标演示
SPEC.md           # 引擎设计文档
CHANGELOG.md      # 版本历史
```

根目录的 skill 文件是唯一事实源;`scripts/sync_skill_assets.py` 把它们同步进
wheel 载荷,两者一旦漂移测试即失败。

## 设计承诺

- **判决是代码,不是意见**:验证者只评估预注册的规则合约;合约在执行前哈希锁定;
  测量代码内容哈希进每条证据记录。信任模型见
  [`references/verifier-contract.md`](references/verifier-contract.md)。
- **失败即信息**:被证伪的命题、无效测量、预算耗尽都是一等公民结局,各有专属
  视觉呈现——Arena 永远不会把 MISS 画成伤害。
- **记忆必须挣得**:经验晋升需要来自独立实验的证据支持,并携带跨 run 的引用/
  效果统计。
- **本地优先、零依赖**:每个项目一棵基于文件的状态树,无运行时依赖,一切可离线
  审计。

## 测试

```bash
python3 -m pytest -q
```

## 许可

MIT——见 [LICENSE](LICENSE)。
