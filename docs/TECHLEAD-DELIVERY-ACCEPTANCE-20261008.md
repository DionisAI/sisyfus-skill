# Sisyfus 本轮交付验收（2026-10-08）

## 当前结论

**真实双机执行与集成已验证，完整产品交付仍有开放门。**
本轮没有把条件算术当作实盘盈利，也没有把源码审查、窄屏浏览器或本机协议替身当作实体手机验收。

固定范围和旧失败继续保留于
`artifacts/techlead/orchestra-20261008/full-delivery-b9e7b9660c534c98bfaaba7f7fede382/DELIVERY-CONTRACT.md`。
原 `TECHLEAD-ORCHESTRA-CONTRACT.md` A1–A8 未缩小。

## 已有实际证据

| 项目 | 实际结果 | 边界 |
|---|---|---|
| 原生规划 | Opus 方案，独立确认 Prepare / Start | 聊天不自动派发 worker |
| 双机协作 | 指定 EC2 的 remote-math → 本机 local-answer，各执行一次 | 第二主机使用自己的 Codex 登录，只有本轮最小源码和任务凭据 |
| 检查与审查 | 两任务固定检查 PASS，三次实际 Opus 5.5 独立审查 PASS，最终集成 PASS | Sol 请求明确 gpt-6.1-sol，回执 actual_model 为 null，不声称运行时型号已证明 |
| 补充信息 | local-answer 的资料 APPLIED，已有原生接受提示与完成回执 | 收到、选入提示、执行完成、验收分别记录 |
| 重启与远端重读 | 重启后完成任务、5 条原生调用及回执逐字一致；远端返回同一 RECEIPTED | 零新增原生调用；首次 UNKNOWN 保留隔离 |
| 产物与远端状态 | 20 个节点源码文件读回一致；原输入、analysis、answer 与集成 bytes 核对；远端 DONE | SQL 是逻辑只读，不声称 WAL 物理零写 |
| 报告状态文件移除 | 原因修复、源码独立审查、真实 macOS Trash 回收字节核对 | 失败和暂存保留，Linux 缺 Trash 时显式报错 |
| 原有报告回归 | 不改旧测试，340 PASS | 不是全部仓库测试全绿 |
| 手机入口源码 | 密码必需、固定方案/对话、未知请求隔离、分开 Prepare / Start，核心及换行微修均已有独立 Opus 源码审查 PASS | 仅本轮固定工程，不暴露 Console/NodeGateway、库存或任意控制 |
| 当前手机宽度浏览器 | 实际完成任务在 360×800 视口，修复后页面宽度 360；密码框清空，重复 Start 禁用 | LOCAL_ONLY 合成密码，不是实体手机或用户公网配置 |

主要证据：

- `dualhost-schema2-4691cd761e306acf/RESTART-ACCEPTANCE-v2.json`
- `dualhost-schema2-4691cd761e306acf/after-restart-canonical-v2.json`
- `dualhost-schema2-4691cd761e306acf/remote-final-readback.stdout`
- `NODE-SCHEMA2-SOURCE-GATE.json`
- `PHONE-PORTAL-SOURCE-GATE.json`（窄屏微修前版本保留）及 `PHONE-PORTAL-SOURCE-GATE-v8.json`
- `report-regression-fixed-once/RESULT.json`
- `real-observatory-trash-a09c76658b724378bc9d71038876cc4d/RESULT.json`

以上文件均位于同一完整交付证据根。

## 保留的失败和限制

- 首次双机调用在原生启动前的心跳确认超时，持续为 UNKNOWN；新独占任务替代验收，不重发旧调用。
- 测试中的异常文本、休眠签名、权限 umask、诊断对象形状等已知旧 oracle 差异原样保留；补充证明不追溯改称原测试全绿。
- 重启测量再次调用旧 `node-no-work.command`，其重定向覆盖了原 pre-Start stdout/stderr。首次 NO_WORK 仍有既有工具观察及持久数据库行，但该位置的原日志字节不再保存。审计缺陷在 RESTART-ACCEPTANCE-v2 明示，不伪造原文件。
- 当前 v6 已完成任务在 360px 浏览器实际出现 658px 水平宽度，原因是长证据哈希及消息列表缺继承换行。保留 RED1FAIL/2PASS，23 字节 CSS 微修后同冻结3项及旧4项共7PASS；浏览器宽度实际360，独立 Opus源码PASS。实体手机结果另记。
- 研究 Reader 的独立 no-tools 原生调用留有实际登录错误；尚未打通动态报告正文发布。之前 WAL 六候选测量没有支持全部目标，未据此选择生产零写契约。

## 尚需完成的交付门

1. 用户本机隐藏设置专用密码，保存仅 verifier 的 0600 文件；测试密码不作用户配置。
2. 本轮 Portal 在真实 Cloudflare HTTPS 上发布；匿名只见登录、正确密码后访问固定工程，错误密码、退出撤销核对。
3. 实体手机登录、查询 /btw、补资料、刷新与重新登录；检查控制器回执及零重复派发。实体手机新建/规划/显式 Start 全流程也仍是开放门；已完成任务的手机浏览不替代此门。
4. 图、进度、工程证据投影使用同一 capture；**固定 HTML 报告仍是独立 SHA 版本，不是随任务快照更新的报告正文**。动态可读正文与统一研究 basis 尚待 Reader 路径。
5. 公开数据的可成交价差、深度、资金费、实际费用/返还资格、成交概率、滑点和单腿风险测量，才支持交易盈利及容量判断。本轮固定 20M 总周转、1bp 净 edge、条件 500 USD 不构成实盘、每日收益或 Arcus 盈利证明。
6. 手机 Portal 暂停/恢复/Stop 本轮保留在本机控制器；不据手机只读页面扩称任意多工程、多节点控制已经交付。
7. 当前远端 CLI 是单次固定请求生命周期；已完成请求重读返回原 RECEIPTED。本轮没有验证同一常驻节点连续领取多个新任务、长期断网重连与多工程轮询。新增轮询/下一任务接口须保持旧请求、UNKNOWN 和去重契约。

## 使用顺序

1. 本机运行证据根中的 `human-password-setup.command`，隐藏输入专用密码两次，不把密码写进聊天。
2. 主控核对当前源码门、固定方案和控制器，再发布只连接 Portal 的临时 HTTPS。`public-start.command` 为固定工程入口，前台关闭即结束发布。
3. 手机访问无 token 的 HTTPS 地址，输入专用密码；先核对真实已完成任务，发送 `/btw` 和资料，刷新/退出/重新登录，不重复点击未知请求。
4. 本地 Console 与 NodeGateway 不直接穿透公网。临时地址不作为生产长期可用性承诺。

停止本轮工作前，更新实际设备/PASS/FAIL/待验表，而不是将源码门改写成整体完成。
