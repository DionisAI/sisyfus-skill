# NodeAgent 持久执行切片

此为下一切片接口合同，尚待实现；真实第二台机器和实际手机仍待 A7/A8。
节点本地数据库只记录传输/原生执行身份，不产生任务验收或新的 hub 真相。

## 固定配置与接入

- `NodeAgent(credential_file, state_directory, *, driver=None)`；
  `run_once()` 领取至多一个固定任务或核对旧任务。生产默认 driver 为原
  CodexDriver；注入 driver 只用于明确标记的协议测试。
- 凭据文件为 operator 已独占准备的普通、单链接、NOFOLLOW、当前用户所有、
  0600 文件，位于执行工作区以外。v1 严格字段：
  `{schema:1, controller_mission_id, node_id, secret, gateway_url, gateway_host}`。
  有限 JSON、重复键/未知字段/大小/类型均核对。
- v1 gateway_url 仅 `http://127.0.0.1:<port>` 或 localhost，path/query/fragment
  为空，gateway_host 是实际 node gateway 的固定 loopback Host/port。
  远端访问由用户选定的 SSH 转发提供；NodeAgent 不创建转发、不选择主机、
  不放宽公共入口。HTTP 重定向禁止，固定前缀/路由和有限请求/响应时间。
- 本地 native 使用节点自己的 Codex 登录及原 environment 过滤规则。
  node secret 不进入 driver Request/env、workspace、事件、产物或日志。
  所有错误对 secret 原值和 `Node <secret>` 脱敏，错误保留关联身份。

## 至多一次执行与重连

1. 以独占 0700 state_directory 和进程/文件锁保护单个 Agent 实例；凭据、
   sqlite、outbox 与 workspaces 分开。所有旧目录、失败和未知工件保留。
2. 领取 request_id 在网络 POST 前持久提交。丢失响应仅重复同 id；NO_WORK
   先持久保存，然后下一次明确 run_once 才建立新 id。不得因超时取新 claim。
3. 验证 response namespace/node/run/task/epoch、offer fingerprint、原 Request
   严格字段、codex/gpt-6.1-sol/workspace-write、prompt/input hashes 和边界。
   下载有限固定输入，普通单链接 NOFOLLOW、hash/size 和最终完整输入树核对。
   唯一 workspace 不复用，只有本地 cwd 变更，原 request 另行固定保存。
4. native 启动前事务持久 `IN_FLIGHT` reservation 与 claim/input/offer 身份。
   重启见 IN_FLIGHT/UNKNOWN 只核对/传输原事实，不再次调用 native driver。
   即使崩溃发生在 reserve 与 spawn 之间，也不推断未执行并重新启动。
5. 每条原 native event 在网络前持久提交连续 seq outbox，有限批次 sync。
   ACK 高水位必须与当前 claim/epoch、连续本地记录一致；重复只重传原记录。
   记录超过 N1 既定字段/64 KB 或未知 event kind 时明确诊断，不静默删除或
   合成接受证据。资料 APPLIED 仍仅由原 controller N1 接受证据产生。
6. 独立 heartbeat 保持安静 native 调用的 claim；空 sync/status 不续租。
   请求丢失可重试同身份，但失去 core/node lease、revocation 或 epoch 变化
   时只做本地合作停止与原结果核对；不据新连接/心跳重新启动 native。
7. 每个 interrupt id 在交给 driver 前持久记录“已交付本地 driver”。重试/
   重启不重新交付；是否 native accepted 仅原 control_ack。没有 ACK 的
   中断保持待核对，不从持久交付记录伪造接受。其他动作显式拒绝。
8. 终结 native Receipt 先持久，再保存完整工作树。全树错误保留，不能只
   上传允许文件来掩盖变化。只上传 changed/added 的精确 allowlist 普通文件；
   树仍包含所有 hidden/control/special 诊断。回执、STORED 清单和 tree 的
   原内容固定后重传；不同结果不覆盖，不自动尝试第二次实现。
9. 上传/回执丢失 ACK 重传同身份/hash。失去 lease 后只报告已确知的 STORED
   子集和完整诊断，不宣称未确认上传已存。迟到结果由原控制器保存为
   reconciliation candidate；本地 outbox 和全部工作区保留。

## 固定检查先冻结

- 真实固定 HTTP gateway 的 claim/input/sync/heartbeat/upload/receipt 往返，
  与 controller N1/inbox 同事务；协议 driver 明确计 fixture。
- 丢 claim/sync/upload/receipt 响应后的原身份重传，NO_WORK 后明确新请求；
  reserve-before-spawn 的故障注入，IN_FLIGHT/UNKNOWN/终结重启零新 native。
- 输入/offer hash、权限/路径/type/epoch 篡改与断线/撤销均不授予执行。
- 安静调用 heartbeat；interrupt 至多一次交付、无 ACK 不伪造；N1 超界事件
  显式失败、bounded outbox 保留；不存在未知 kind 的兼容成功别名。
- native receipt 实际模型遥测与 requested_model 分开；全树检测变化/删除/
  越界、固定上传字节及迟到子集；凭据不进入进程/日志/数据工件。
- 并发进程排他、独占工作区、重启读回、无永久删除；原失败工件保留。

节点不执行 verifier/reviewer/integration，不提供 operator Start/chat/注册
权限。原控制器检查、独立审核、scope 与集成是单独必需闸门。
