# RemoteCodexDriver 控制器适配切片

此为原生 Opus 传输建议的控制器接口细化，尚待实现。原 Orchestra A1–A8、
N1–N6 和不可变检查保持；单独 driver 源码/协议检查不代表远端执行接通。

## 公开接口与所有权

`RemoteCodexDriver(claims, run_key, node_id, *, input_snapshot, candidate_root,
output_paths, poll_seconds=0.2, clock=time.monotonic)` 保持
`run(Request, emit, controls=lambda:[]) -> Receipt`。这些构造参数全部由控制器
提供，节点不提供路径根、run key、输出权限或验收。`name='codex'`，v1 控制
仅 interrupt。此次切片仅新增独立模块和测试，不修改 LeadCapability 接线。

- 调用前已有真实 canonical IN_FLIGHT worker reservation；任务/model/mode、
  continuation token、固定 prompt 和 node identity 必须相同。
- Request.cwd 是原控制器候选的固定角色路径；创建独立 input snapshot 后由
  bind_input_snapshot 固定只读传输根。offer Request.cwd 不重写；NodeAgent
  在自己机器替换 cwd，原 request/prompt/input/offer hash 保持。
- input_snapshot 和 candidate_root 各是已准备、互相及原 candidate/上传根
  分离的父目录下未存在独占叶目录。不隐式覆盖或修复旧目录。失败工件保留。
- `materialization` 属性只承载 `{candidate,before,delta}` 或完整性诊断；
  使用 remote_artifacts 返回的独占 envelope/candidate 路径，不假定函数会
  覆盖 Request.cwd。后续 LeadCapability 在此候选上计算 patch/scope、保存
  artifact，运行原检查/独立审核/集成。此属性从来不是 verifier PASS。

## 输入、发布及重试

- 使用完整的 prepared candidate，而非忽略 hidden/control/special 文件。
  `create_input_snapshot` 的有限 128 files/8 MB per file/32 MB total 和严格
  路径继续适用；不适配材料明确 ERROR，不静默删减。
- output_paths 为控制器固定的精确文件清单。后续接线从所有输入文件及
  明确文件 write_paths 推导，并再次以原任务 write_paths 核对 delta/scope。
  目录写入或未知新文件不自动扩大 allowlist；保留诊断，完整树揭示所有变化。
- tree wire 不另设 deleted_paths；控制器从原 input files 在最终严格普通文件
  tree.files 中的缺失确定删除集合，再让 exact_delta 验证完整树/目录/allowlist。
  tree.tree 中同路径非普通节点不掩盖文件删除或类型替换；不完整树直接 INVALID。
- 快照完整验证、绑定成功后才 offer。准备失败且证明无 offer 返回已知 ERROR。
  offer 提交后异常或身份不明返回 UNKNOWN；不补发、不重绑、更不本机兜底。
- run 每个实例只允许一次执行。已有 offer（包括 WITHDRAWN/UNKNOWN/receipt）
  只核对固定身份并读回，不再次准备/offer/native。fresh run key 与已占用
  快照目录冲突显式失败；不据目录存在推断准备成功。
- 原 offer 读回也不新物化：匹配的及时终结 Receipt 可带
  `materialization.status='NOT_MATERIALIZED'` 诊断读回，后续 caller 不凭这个
  回执重建候选或验收；原 core cached receipt 仍由原 LeadCapability 优先处理。
  新物化错误是 `materialization.status='INVALID'` 与完整诊断，native 状态不伪造。

## 等待、停止及回执

- 复用 AutonomousRuntime 已有 LeaseHeartbeat；driver 不创建新续租者。
  每轮等待及返回前核对 canonical reservation 与冻结 continuation token。
  任一身份/lease 丢失是 UNKNOWN，终止等待，不授予重新执行。
- 请求总等待有单次 timeout；clock/poll 值严格有限。NodeClaims.expire 保留
  未知 offer 的持久 fence。未领取时的超时/停止与 claim 同事务竞争 withdraw；
  只有 WITHDRAWN/epoch 0/无 claim 才证明未执行并返回已知 ERROR。
- CLAIMED 时控制器将固定 interrupt 持久 post_controls。相同 id 重传保持；
  native ACK 由 NodeAgent → N1 sync 推进。交付不伪造 ACK。其他 action 明确
  rejected control_ack，不将其传给 post_controls 或 native。
- timely RECEIPTED 的 native Receipt 保持请求/实际模型分离；完整树和 STORED
  上传交由 exact_delta/materialize。缺树、diagnostics、不完整、越界、缺失或
  hash 差异成为可追溯完整性错误，保留已知 native terminal，绝不伪装 candidate。
- UNKNOWN/RECONCILIATION_CANDIDATE、epoch/ownership 变化或迟到结果均返回
  UNKNOWN；原始 native 事实仍保留在 NodeClaims。不得清除 core UNKNOWN。
- materialize 前后重新核对 offer 固定 hash、owner/epoch、timely receipt 和
  canonical continuation 身份；变化不结算。不得重复发射已由 sync 持久提交的
  node native events/资料应用/控制 ACK。
- 尚无独立公开 controller lease validator 时，只读
  `claims.journal.store._transaction(immediate=False)` 加原 `Journal._fence`
  是本切片准许的最小复用；固定 native_worker_runs 的 key/task/fingerprint/
  continuation_id/lease_token，角色和 context metadata 存在时核对原值。
  不新增续租、写回、状态解除或假成功的 validator。
- timely RECEIPTED 是提交时已核对双 lease 的持久终结事实。之后自然到期的
  node heartbeat deadline 不把它重新变成活跃执行或迟到结果；materialize/
  return 仍要求同一 RECEIPTED、receipt/hash/owner/epoch 与活跃 canonical
  continuation fence。没有 receipt timestamp 不从现在时间猜提交时状态。
  CLAIMED 等待仍要求双 lease；原 UNKNOWN/reconciliation candidate 不晋升。
- driver 不调用 Journal.reserve/complete、reviewer、verifier 或 integration。
  原 LeadCapability 仍拥有其 reservation 和最终原子 complete 边界。

## 先冻结的验证

脚本化 node 仅计 protocol fixture：固定 snapshot/offer/正常事件与及时结果；
停止/超时 withdraw 与 claim 竞争；已领取失联/身份与 lease 丢失 UNKNOWN；
原 offer 读回零新 offer/native；unsupported controls 明确 ACK；完整树变化、
删除及真实 Trash、缺上传/篡改/越界/hidden/control/错误树均不给成功候选；
IO 前后 receipt/epoch/core fence 变更；原快照与失败工件保留；native telemetry
不由配置推断；原 NodeClaims/N1/产物固定测试及失败历史保持。
