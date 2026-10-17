# 会话式机器选择接线

此为待实施的网页切片，不宣称已经在演示服务或手机部署。默认轻色中文对话
遵循 `.impeccable.md`；完整过程、机器、资料和结果留在同一任务页。

## 已观察到的第二个入口缺口

MissionHub 已有显式准备边界，但当前 ChatManager.start 在创建任务后立即
调用 hub.start；仅给已运行任务加机器按钮仍会与 reservation 竞争。网页需要
在确认原方案时选择“先生成子任务，再选择机器”，而不是开始之后抢占派发。

## 控制器和 HTTP

- 新 `ChatManager.prepare_placement(chat_id, allow_planning, request_id,
  approval_hash)` 与旧 start 分开，旧 start/确认契约保持。
- 相同原 readiness、approval_hash、source/验收 hash、固定 objective/constraints/
  deliverables 与操作 request_id 必须核对；聊天 proposal 仍不能替代不可变检查。
  只做 operator-confirmed spec 绑定和 hub.prepare_placement，不调用 hub.start。
- 请求先持久；任务映射在规划准入前持久；相同请求从原身份读回、不同类型/
  approval hash 明确冲突。丢失创建/规划结果保持待核对，不另建第二个任务。
  已绑定草案仍冻结，补充资料转原 mission inbox。
- 新 operator POST `/api/chat/prepare-placement` 固定 body
  `{chat_id,allow_planning:true,request_id,approval_hash}`；复用 Host/Origin/Bearer/
  Node 头隔离。它是明确规划许可而非普通聊天消息，ACK不表示规划或任务通过。
- 本切片不替换 Hub/Lead 的原 `_run_lock`、文件锁、UNKNOWN、任务准入或验收。
  完成准备后 Start 必须另行明确授予已有 worker 权限；未就绪继续等待。

### 机器选择的只读读回

已核对现有 GET nodes 只有节点库存，snapshot 子任务未带 placement。为刷新
和跨端展示新增 GET `/api/missions/{id}/placements`，无 query，复用原 operator
边界，返回 `{mission_id,placements:[{task_id,placement}]}`。包含该任务已有
固定子任务（含历史），placement 是原持久 pin，缺省严格为 `{kind:'local'}`。
同一次原 store 只读事务读取固定任务与 pins；不构造 NodeClaims/Registry、
不回填 metadata、创建请求、规划、派发或推断在线。POST 选择行为保持。
task_id 仅为读回外层关联字段，不加入或重算原 task/placement fingerprint。

网页新增公开交互标识：`chat-planning-permission` / `chat-prepare-placement`
（原方案确认中的单独规划许可与按钮）、`chat-placement-retry`（同原请求
明确重试）、`machine-panel` / `machine-note` / `machine-list` /
`placement-list`（同任务渐进展示）、`node-name` / `node-enroll` /
`node-config-copy` / `node-config-download`（显式登记及交付配置）。选择按钮
用 `data-task-id` 与 `data-node-id` 关联固定身份；撤销按钮用
`data-revoke-node`。权限默认未勾选，普通读回不操作这些按钮。
节点库存内的 namespace mission_id 与 Hub 的 mission_id 是不同身份，分别
保留在库存和后续 claim 读回。NodeAgent 配置严格使用六字段，只有 Hub 身份
作为 controller_mission_id，不另塞 namespace 字段或让网页生成 native 凭据。
详见 TECHLEAD-NODE-WEB-PLACEMENT-PAGE.md 的当前接口静态核对说明。

## 网页交互

1. 方案确认面板保留“确认方案并本机开工”，另列清楚的“先规划，接着选机器”。
   分别说明 Lead 规划调用与实现调用；权限不预先勾选。普通文本与查询零派发。
2. prepare结果与原mission id映射确认后进入同一任务页；人可读状态为
   “子任务已准备，等待选择执行机器”，而非仅显示 WAITING_PLACEMENT。
3. 同页渐进展示每个冻结子任务/写入范围、默认本机及本任务登记机器。选择为
   显式 operator placement 请求，显示收到/固定/失败，保留 request_id 重试。
   已 reservation/UNKNOWN/旧回执/角色隔离不在浏览器绕过。
4. 机器登记、状态读回和撤销沿用 N2 API；登记不证明在线、native登录或就绪。
   secret仅首次注册返回，库存/消息/图/日志不展示；接入配置仅用户明确下载或
   复制时交付，演示截图及最终回复不含secret或带token URL。远端凭据自持。
5. 最后 Start再次确认；显示哪个子任务在哪台机器及每项当前状态。远端不可用
   不是静默本机回退，状态/诊断/资料APPLIED不代表整项验收。
6. 请求不明只读回/同id重试，刷新/重连仍保留同任务与选择；切换任务时响应
   不混入新页。中文IME、键盘焦点、触屏/窄屏与 reduced motion 保持。
7. 报告先展示“做成什么、结论、依据”，再展开机器/过程/专业回执；既有固定
   验收和证据来自 controller，不由 frontend 合成新的通过。

先冻结 Chat/HTTP/网页真实生产函数检查，再实施。随后真实浏览器记录完整
双步确认与零提前worker调用，并保存截图。窄屏和本机协议仍不替代 A7/A8。
