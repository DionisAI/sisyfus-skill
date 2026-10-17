# 同任务机器选择网页：固定检查边界

本页为新增网页检查的实施说明，既有默认轻色中文会话和固定验收保持。
只读库存与 placement 读回、规划许可、机器登记和最终 Start 是分开的步骤。
普通聊天、刷新、切换任务、注册节点与选择机器均零 worker dispatch。

- `chat-planning-permission` 默认为未勾选，独立于原 `chat-permission`。
  审阅当前 approval_hash 后，`chat-prepare-placement` 只 POST 固定四字段。
  ACK 只表示受理；进入原 mission 看实际准备状态，Start 仍单独确认。
- 超时保留原 request_id/approval_hash 与操作输入，查询只核对同请求；
  `chat-placement-retry` 是显式原请求重试，不自行生成第二个任务。
  切换任务期间晚到结果留在原任务，禁止写入当前任务的视图或选择。
- `machine-panel` 在原任务页渐进展示，包含 `machine-note`、`machine-list`
  和 `placement-list`。只从 controller 的 GET nodes、GET placements、snapshot
  投影状态；ACTIVE 只说明已登记，`execution_ready:false` 不变成在线/登录。
  选择按钮用 `data-task-id` / `data-node-id`，撤销按钮 `data-revoke-node`。
  失败或未知保留原 pin，不靠浏览器猜测新的固定选择或验收通过。
- 登记通过 `node-name` / `node-enroll`。首次返回的 secret 仅留当前页面
  私有内存，不进入 DOM、sessionStorage/localStorage、history、事件、诊断。
  显式 `node-config-copy` / `node-config-download` 才把配置交付给用户；
  首次响应丢失或刷新后 secret 缺失，说明需撤销后重新显式登记，不伪造密钥。
- 独立网关尚未接入时禁止猜测 console 端口。配置采用当前 NodeAgent 严格
  六字段：`{schema:1,controller_mission_id,node_id,secret,gateway_url,gateway_host}`。
  `controller_mission_id` 为当前 Hub mission id；Registry 的 namespace
  mission_id 只留库存/后续 claim 读回，不作为第七字段塞入 credential。
  `node-gateway-url` 与 `node-gateway-host` 由用户明确填写 loopback 连接地址和
  固定 Host，SSH 本地转发端口可不同。没有这些信息时交付按钮保持待配置。
  用户保存 credential 文件时需 0600，state 目录需 0700；页面不建立 SSH。
- 固定子任务写入范围、原默认本机与已有远端 pin 始终可读；旧任务/未知/
  已有 reservation 在核心受限，前端不得绕过。Start 确认说明按已固定机器
  执行、权限与费用，并且保持原 HTTP worker 许可字段及验收闸门。
- 窄屏、键盘、中文 IME 与 reduced motion 保留同等功能；真实浏览器和真实
  手机仍是独立验证，不用本机 JS fixture 宣称设备验收。

新增检查只针对以上可观察交互和真实生产脚本，不冻结无关内部函数名。
先记录现有公共 shape 和明确新增 IDs，再 freeze / RED，原检查及失败保留。
