# NodeClaims 执行传输服务切片

后续 RemoteCodexDriver、NodeGateway、NodeAgent 接线所需的 controller-owned
接口，尚待实现。保持原节点基础/N1 与 Orchestra A1–A8，新增固定测试先冻结。

## 固定输入绑定

`bind_input_snapshot(run_key, root, manifest)` 在 offer 前由控制器调用。
要求真实 IN_FLIGHT reservation；root 为控制器已独占建立的持久快照，
manifest 是原 `files/output_paths` 形状。验证所有普通文件的固定 hash/size
和严格路径；同 key 的不同 root/manifest 明确冲突。数据库与 hash chain
固定 root、manifest digest 和 run identity，不传凭据、不接受节点指定根目录。

既有基础 `offer` 调用不强制回填该记录。新 transport offer 若有输入绑定，
其 manifest 必须相同；未准备完整的快照不发布。原完整快照和失败目录保留。

`read_input(node_id, claim_id, epoch, path) -> bytes` 仅用于活跃、属于该节点的
claim，且存在上述固定绑定。只读 manifest 中的文件；descriptor-relative
NOFOLLOW、单链接普通文件、实际 hash/size、文件数/总量边界和读取后的
node/core lease 都核对。返回 bytes 前再次确认所属身份；不延长 lease。
另一节点、撤销、epoch 冲突、租约丢失、未知路径或完整性不符明确报错。

## 状态、撤回与控制

- `status(node_id, claim_id, epoch)` 只读所属 offer/view；不 expire、不续租、
  不创建领取身份、不释放未知执行。已过期 owner 可以核对旧身份，别的节点
  隔离；撤销身份的访问由 gateway 认证拒绝。epoch 必须准确。
- `withdraw(run_key, reason)` 与 claim 同一个任务库事务竞争。仅 OFFERED/
  epoch 0/无 claim 可变 WITHDRAWN，证明未领取；CLAIMED、UNKNOWN、终结或
  reconciliation candidate 均保持，不据此伪造未执行。相同撤回读回；
  原 core reservation 不在这里结算。
- `post_controls(run_key, controls)` 是控制器内部方法，无 node HTTP 写入口。
  v1 只收固定 `{id,action:'interrupt',text:''}`，按 id 持久去重；冲突报错，
  其他动作显式拒绝。有限批次/UTF-8/字段边界；不允许 arbitrary argv/steer。
- `pending_controls(node_id, claim_id, epoch)` 只读活跃所属 claim 的未 ACK
  interrupt。交付不是 native ACK；同 id 可重复读回。NodeAgent 本地先持久
  标记处理身份，再交给 driver；不同 id 的实际控制独立记账。
- N1 的新 `control_ack` 事件同事务推进相同 run 的 transport control 状态；
  unknown id 不获得 operator 权限，原 Journal command ACK 行为保持。
  重传既有 event 不重复操作；callback 失败与命令 ACK 一起回滚。

独立 `heartbeat` 沿用现有 active-claim 续租，不以空/重复 sync 或 status
代替它。节点只延长自己的 claim，controller continuation 仍由现有
AutonomousRuntime LeaseHeartbeat 保持；失去任一所有权均不重新启动 native。

## 完整树终结回执

原 `receipt(..., receipt, manifest)` 基础接口字节语义继续保持。新增可选
keyword `tree`，仅新的 transport 调用要求它；旧投影不回填新字段。

- tree wire 形状来自 `remote_artifacts.full_tree_manifest`：
  `{schema:1, files, tree, errors, complete}`。严格 finite JSON、明确类型、
  bounded 字符串/4096 entries/总 UTF-8；树中的非普通/隐藏/控制路径和缺失
  hash 诊断可保留，但从来不成为可物化普通文件。
- tree 是写一次的独立传输证据，同一个 receipt replay 的不同 tree 明确冲突。
  schema/type malformed 明确报错；`complete:false` 或 errors 不伪造完整成功。
- receipt + uploads manifest + tree + event 同事务提交；已有及时/迟到、
  PREPARING 上传、STORED 子集、UNKNOWN 与 reconciliation candidate 规则保留。
  完整树无效仍可保留已知 native terminal 事实，最终候选由控制器判 INVALID。
- 此模块不调用 Journal.complete、verifier、review 或集成，不清除 UNKNOWN；
  新 Driver 读取匹配的树/上传后在控制器物化，并核对完整 delta/scope。

## 先冻结的验证

固定输入重试/冲突/offer pin、NOFOLLOW/hash/读取后租约丢失、所属状态只读、
撤回与领取竞争、不撤回已执行/未知、interrupt 字段/批次/冲突/重传、native
ACK 原子回滚、完整树正常/诊断/类型/大小/冲突/迟到，以及原 foundation/
N1/inbox 回归。既有7项旧契约差异保留，不追加 alias/skip/xfail 取绿。
所有工件和失败状态保留；移除只走可恢复 Trash，测试不依赖永久删除。
