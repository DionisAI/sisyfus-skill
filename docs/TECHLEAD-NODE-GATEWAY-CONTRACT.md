# Node Gateway N4 接入边界

本文件固定后续 N4 的接口细节；此刻 gateway 和 NodeAgent 尚未接通。
不取代 Orchestra A1–A8、N1–N6 或原来的工程验收闸门。

## 服务和身份

- `NodeGateway(hub, *, port=0)` 是独立的 loopback HTTP 服务，地址固定
  `127.0.0.1`。不承载 operator 页面、聊天、Start 或节点注册。
- 路径中的 `controller_mission_id` 是 MissionHub 的选择 ID；现有
  NodeRegistry 的 `mission_id` 是数据库内固定的 namespace。两者分别保留，
  不互相覆盖。响应信封可增加 `controller_mission_id`，底层 claim 中的
  `mission_id` 保持原语义。
- 一个 Host，且为本端口的 `127.0.0.1` 或 `localhost`。带 Origin 的请求拒绝。
  一个 `X-Sisyfus-Node` 和一个 `Authorization: Node <secret>`；operator
  Bearer 在此入口失效。节点身份不授予 operator 路由权限。
- 完成 Host、头部形状和已登记节点认证后才解析操作或建立可写后端。
  认证只读固定任务数据库中的已有节点记录：未登记数据库、未知节点、
  撤销身份或错误秘密都不给予初始化、mkdir 或 native 调用能力。
- 通过 hub 固定 child 和 bound-spec 读回检查选定任务。只读认证时不调用
  lazy `node_claims` 初始化；认证后后端也重新核对 ACTIVE 状态，防止撤销竞争。
- 节点认证凭据不进入 Request、输入包、产物、错误正文或访问日志；禁用
  HTTP access logging。正文错误采用固定字段名和脱敏诊断，不回显未知请求。

## 路由

前缀 `/node/v1/{controller_mission_id}`，无 shell、任意 argv、验收或路径根字段。

| 操作 | 方法和路径 | 固定输入 |
| --- | --- | --- |
| 领取 | POST `/claim` | `request_id` |
| 事件同步 | POST `/sync` | `claim_id, epoch, events` |
| 独立心跳 | POST `/heartbeat` | `claim_id, epoch` |
| 状态读回 | POST `/status` | `claim_id, epoch` |
| 固定输入 | GET `/inputs/{claim_id}/{epoch}` | query `path` |
| 产物上传 | PUT `/uploads/{claim_id}/{epoch}` | query `path, sha256`，octet-stream bytes |
| 终结回执 | POST `/receipt` | `claim_id, epoch, receipt, manifest, tree` |

- JSON 操作必须是严格对象：重复键、未知字段、NaN/Infinity、非整数 epoch、
  嵌套/大小越界均显式失败。一个准确 Content-Length，无 Transfer-Encoding。
  上传上限沿用 8 MB，其他正文上限 1.5 MB，N1 的批次限制仍单独执行。
- URI/query 有固定长度与字段数边界，重复 query、错误百分号编码和未知字段
  拒绝；解码后相对路径继续使用现有严格路径规则。
- `status` 属于只读操作，不延长 lease，不提供重派许可；已失去 lease 的
  owner 可核对自己的已存结果，另一个节点始终隔离。
- 安静的 native 调用用独立 `heartbeat` 续自己的活跃 claim；N1 的空批次和
  重传保持只读，不借此恢复过期执行。待交付 interrupt 可放在 gateway
  响应信封中，不改变已冻结的底层 sync 返回字段；交付与 native ACK 分开。
- `read_input` 属于活跃 claim；descriptor-relative、NOFOLLOW、普通文件、
  单硬链接、固定 hash/size，全量校验后返回 bytes。输入 snapshot 与 claim
  绑定，不从节点上传的路径值推导控制器任意文件。
- `receipt` 的 `tree` 是完整工作树证据，与上传清单分别检查并写一次。
  旧基础 `receipt(..., manifest)` 的语义保留；新的 transport 调用要求树证据。
  迟到回执只保留 reconciliation candidate，不直接完成 core reservation。
- 语法错误 400、认证缺失/错误 401、越权或已撤销 403、固定资源不存在 404、
  冲突或 lease 丢失 409；内部错误 500 保留关联诊断。失败不伪造 ACK/PASS。

## 控制器续租证据

现有 `AutonomousRuntime` 的 `LeaseHeartbeat` 已负责 controller continuation
续租与失败检查。后续 RemoteCodexDriver 复用这一所有权与检查路径，不启动
另一个随意续租者；node sync 只延长自己的 claim，不授予 controller lease。
等待过程中仍核对冻结 token，失去所有权后标明未知执行并保留原身份。

## N4 固定检查

先冻结新增测试，再实现入口：正常 authenticated loopback 往返、Host/Origin/
重复头/身份分离、未认证无写入、任务与 claim 隔离、撤销竞争、正文与 URI
边界、NOFOLLOW 输入、精确上传/hash、无日志凭据、重复请求/失联读回、
与 N1 的原子事件/资料回执及未知执行不重派。HTTP fixtures 只计协议证据；
另一台机器和实际手机仍分别等待 A7/A8 验收。
