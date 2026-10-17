# Remote Node v1 传输契约

此协议是 Orchestra 第二阶段的实现边界，不替代完整目标或 A7/A8 真机验收。执行仍使用原生 gpt-6.1-sol，Lead、独立审核、verifier 和集成由原控制器保持。

## 身份与任务范围

- 节点只通过控制器登记/撤销，能力 v1 限定 codex + gpt-6.1-sol + workspace-write。节点身份不授予 operator 控制、改验收或注册更多节点的权限。
- 身份和领取元数据存于对应任务的现有 autonomy.sqlite3，并进入同一 hash chain；节点只领取明确绑定给自己的调用。跨任务投影带 mission_id。
- 身份凭据只首次返回，数据库/事件存 hash。相同登记请求重试返回已有身份而非新秘密；丢失首次回执需显式轮换/重登，旧登记记录保留。错误日志不出现凭据。
- 网络入口默认仍为本机。远端/手机入口必须显式配置身份、TLS/可信私网和 Origin/Host 边界，节点凭据只用于 node 路由。

## 状态与防重复

- 调用先通过既有 Journal.reserve 与上下文绑定。候选输入准备完成后才能发布唯一 run_key 的 remote offer；发布前崩溃不表示已在节点执行。
- offer 固定 requested model、prompt/hash、mode、timeout、input manifest/hash、任务与节点身份。同 run_key 的不同输入明确冲突，已领取/未知/终结 offer 均不回到待领取。
- 领取有独立 claim_id、lease epoch、request_id 和到期时间。相同 request_id 读回同一结果；接收响应中断后先查询，避免领取第二份工作。
- 节点本地 journal 在启动 native CLI 前持久记录调用 reservation。重启遇到 IN_FLIGHT/UNKNOWN 只核对旧进程/回执，不再次启动同一任务。
- 心跳续租并增量传 native events/控制 ACK；controller 命令 v1 只发 interrupt。断线后旧 lease 到期标 UNKNOWN，绝不据此派发第二份执行。
- 已知且身份/epoch 匹配的终结回执成为传输结果，不是 verifier PASS。迟到回执保留为 RECONCILIATION_CANDIDATE，由既有控制器显式核对；不自动续租、结算或重跑。

## 输入、产物与约束

- 所有路径是非空相对文件路径，拒绝绝对路径、反斜杠、点/父段、NUL、符号链接、大小写折叠冲突和控制目录。
- manifest 每个文件固定 sha256 和 size。节点下载核 hash；上传校验属于该 claim、固定 lease epoch、实际 bytes 的 hash/size，以及文件数/单文件/总 bytes 限额。
- 候选源和依赖由控制器给出；只传工作所需文件，node 自己使用自己的凭据环境。凭据、control DB、原生登录配置不进入输入/产物包。
- 控制器重新物化并计算候选 diff、scope、check integrity。远端上传完整、原生 COMPLETED 或模型声称成功都不跳过既有独立审核/集成。
- 节点只使用允许的原生 driver；协议没有任意 shell command 执行字段。

## 模块接口

- `NodeRegistry(journal)`：`enroll(request_id, name, drivers, models)`，`inventory()`，`authenticate(node_id, secret)`，`revoke(node_id)`。
- `NodeClaims(journal, registry, artifact_root, lease_seconds=30)`：`offer(run_key, node_id, request, input_manifest)`，`claim(node_id, request_id)`，`heartbeat(node_id, claim_id, epoch)`，`upload(node_id, claim_id, epoch, path, sha256, data)`，`receipt(node_id, claim_id, epoch, receipt, manifest)`，`get(run_key)`，`expire()`。
- 上述 registry/claims 是 controller-owned 传输状态；后续 RemoteCodexDriver 与 NodeAgent 接入后才形成执行闭环。

## 必须测试的失败路径

身份撤销/越权、冲突登记或 offer、重复领取、无可领取工作后的重试、lease 过期、撤销节点的迟到结果、heartbeat/receipt 的 epoch 冲突、跨节点上传、路径/hash/size/计数边界、上传冲突、原生 UNKNOWN、重启与 event chain。保留所有测试工件，源码/测试不得永久删除文件。
