# Remote Node 执行接入契约

本文件约束下一实施切片，不取代 Orchestra A1–A8 或现有不可变工程验收。
当前身份/领取模块仍是 disconnected foundations；列出的新接口尚待实现和验证。
原生 Opus 的传输设计是建议，源码独立审核和真实跨设备验收仍为独立闸门。

## 架构与权限

- 默认执行仍在本机。仅 controller-owned implementation 任务可显式绑定本任务登记的 ACTIVE node；Lead、reviewer、RSI trial 和 integration 留在本机。
- operator 绑定 placement，记录 request_id 和 task hash；已有调用先读其冻结 placement。运行中的 reservation、UNKNOWN 和缓存回执保持原身份，不重新绑定或重发。普通聊天、补充资料及模型计划不选择执行机器。
- 节点主动拉取，不接受任意 shell、argv、验收或 operator 控制字段。native Codex 使用节点自己的登录环境；输入包和节点凭据均不包含 operator token 或其他机器的登录配置。
- node gateway 与 operator UI 分端口、分身份，默认均 loopback。节点转发只接入 node gateway，不顺带暴露任务控制页面。实际外网/手机接入需用户明确选择访问路径。
- 任务真相仍在原有 per-mission autonomy.sqlite3、hash chain、continuation、verifier 和独立审核中，无新增 hub truth DB。

## 事务与传输接口

1. `Journal.event_in(db, key, kind, data)`：在调用者事务中复用原 `event` 的 IN_FLIGHT、continuation fence、hash chain、after_event 和 control_ack 行为；不另开写事务。原 `event` 用其包装，行为保持。
2. `NodeClaims.sync(node_id, claim_id, epoch, events)`：领取身份、连续事件序号、事件 digest、续租、native event 和资料应用回执同事务提交。完全相同的重传只读回；冲突、序号空洞、失去任一租约均显式报错，整批回滚。
3. `post_controls(run_key, controls)`：v1 只传 interrupt，按 command_id 持久去重；未 ACK 的交付可用同一身份读回。NodeAgent 持久记录每个 command_id 至多处理一次。其他动作明确 REJECTED，不伪造 ACK。
4. `withdraw(run_key, reason)`：与 claim 同事务竞争，仅 OFFERED/epoch 0 可成为 WITHDRAWN，作为确定未执行的证据。已领取/未知/终结调用保持原状态。
5. `status` 只查询、不续租、不授予重新执行；`read_input` 只返回属于活跃 claim 的固定 manifest 文件，descriptor-relative、NOFOLLOW、hash/size 验证后读回。
6. 回执区分 native terminal 与 verifier PASS。已迟到或失去身份/租约的结果只保留 reconciliation candidate；包含未完成上传时仍保留失败/未知回执和缺口，不自动结算。

## RemoteCodexDriver / NodeAgent

- 保持 `run(Request, emit, controls) -> Receipt`；LeadCapability 的 reservation、candidate、patch/scope、固定 check、独立 review、integration 流程保持原闸门。
- 发布 offer 前保存唯一的固定 input snapshot。准备失败且无 offer 是确定 ERROR；发布后失联/未知执行是 UNKNOWN，禁止据超时补派第二次。
- 长等待期间复用原 continuation lease renewal，严格匹配 token；保活失败显式 UNKNOWN。暂停仅阻止新派发，停止传 interrupt，交付和 native ACK 分开。
- NodeAgent 先持久保存 claim request_id 再领取；原响应丢失只核对同一身份。先固定输入与本地 native reservation，再启动一次原生进程。
- 重启遇到 IN_FLIGHT/UNKNOWN 不重新启动 native；只保留和核对原 outbox、上传、回执及已有进程事实。连接恢复不等于新执行许可。
- 本地 workspace 可以替换 Request.cwd，但 prompt/input/offer 的原始 hash 与节点身份保持固定；节点工作区必须唯一、持久，不跨任务复用。
- requested_model 和 actual_model 分开。Codex 配置回显不据此填入 runtime attestation。

## 产物与保留

- 输入包 v1 使用现有 128 文件、8 MB/文件、32 MB/包边界和严格路径规则；材料不适配时显式报告，不静默丢文件或扩大传输范围。
- 上传只在固定 namespace/allowlist 内。还需完整工作树 manifest，避免仅上传允许修改的文件而隐藏其他改动；controller 重新核算 diff/scope，而非信任节点的 patch 说法。
- 缺失输入、非普通文件、控制目录、缺失上传、hash/size 冲突及新目录文件缺少 allowlist 均留下 integrity/scope 诊断，未完整物化的候选不进入成功闸门。
- 原 input snapshot、失败工作区、上传碎片、UNKNOWN/迟到回执及测试工件全部保留。所需移除只用 `/usr/bin/trash` 绝对路径；不支持该流程的环境先明确报告该边界。

## 固定检查切片

- N1：event_in/sync 同事务、无嵌套写死锁；序号重传/冲突/空洞/边界；callback 失败和租约失败整体回滚。
- N2：operator placement 身份、固定 task hash、原 local fingerprint/replay 保持、角色/任务隔离、绑定后变更拒绝。
- N3：input snapshot、offer/withdraw/claim 竞争、native event/ACK、UNKNOWN 不重派、续租、全树物化和原 check/review/integration。
- N4：接口细节见 TECHLEAD-NODE-GATEWAY-CONTRACT.md；分身份 gateway 的 Host/Origin/auth、严格字段/大小、跨节点/claim 路径及秘密不进入诊断/日志。
- N5：NodeAgent 的 reservation-before-spawn、断线/进程重启至多一次 native、固定输入、事件 outbox、controls、回执重传及独立凭据。
- N6：本机两个进程的 loopback 闭环，仅计 protocol/staging；完整 A1–A5 回归。A7 仍需真实第二台机器，A8 仍需实际手机创建、查询、资料补充及重连。

先冻结对应新增测试，再实施；每个切片都需 deterministic evidence 与独立 native review，失败历史不覆盖。
