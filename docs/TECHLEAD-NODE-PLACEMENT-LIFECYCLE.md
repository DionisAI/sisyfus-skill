# 远端任务机器选择的运行边界

这是 N3 执行接线前的必需流程说明，目前尚待实现；不增加已完成声明。

## 已观察到的流程缺口

N2 正确地只允许为已经固定、已准入的 implementation 子任务选择节点。
现有 `LeadMission.run` 在 `_initial_plan()` 后立即启动 supervisor cycle；
网页用户在启动后再选择机器，容易遇到子任务已 reservation 的拒绝。
当前 N2 是 staging，并明确返回 `execution_ready:false`，因此这个缺口
尚未被伪装成可用的远端执行。

## N3 必需的 operator 边界

保留默认本机 Start 的现有行为。远端流程增加一个显式、持久的准备边界：

1. 用户已经确认 objective 和固定验收，再明确选择“生成子任务，先选择机器”。
   仅允许原 Lead 规划/固定任务，不授予 Sol 派发；普通聊天、页面读回和
   `/btw` 不触发这一能力。
2. 复用 `_initial_plan` 的版本化计划与现有 `prepare` 准入；记录
   `WAITING_PLACEMENT`，保留任务 hash、revision、native 规划回执。
   不运行 supervisor，不创建 worker reservation，不重发 UNKNOWN Lead。
3. 同一任务页显示子任务、写入范围与机器选择。N2 operator placement 的
   ACTIVE node、固定 task hash、request_id、同事务竞争规则继续保持。
   未选择远端的子任务默认本机，不重写历史 placement。
4. 当 transport / NodeAgent 接通并核对就绪后，用户再次明确 Start。
   Start 读取已固定的计划和 placement；新的远端 worker reservation
   原子固定机器与上下文，之后由 RemoteCodexDriver 发布 offer。
5. 等待期间刷新、服务重启、查询和资料补充均保留准备状态；不默认恢复
   worker 派发。已有停止、暂停、UNKNOWN、试验隔离与验收仍保持。

这个边界是执行许可，不是新的验收方式。不得用“选择机器失败后自动本机”
绕过用户选择，也不以已登记节点或正常心跳推断 native 登录/执行已经就绪。

## 本切片固定接口

- `LeadMission.prepare_for_placement(request_id)` 仅由显式 operator 调用。
  使用与 `run` 相同的进程内/文件控制器排他锁；先持久记录请求，再进行
  原有 Lead 规划。`request_id` 冲突明确失败；相同请求读回既有状态。
  只有已知未执行的准备步骤可继续，未知 native Lead 不重新发送。
- 已有固定 initial plan 无需调用模型。需要 native Lead 时只做该角色所需
  preflight，不要求或运行 Sol。规划/准入完毕固定 revision、task hashes、
  acceptance_hash 和 plan hash，再记录 `WAITING_PLACEMENT`。
- 准备流程不进入 supervisor cycle、verifier、review、trial 或 integration。
  此切片不启用远端传输；N2 的 `execution_ready:false` 行为保持。
- `MissionHub.prepare_placement(id, request_id, *, allow_planning=False)` 使用
  现有 session/control 审计及线程管理。只有 `allow_planning is True` 接受；
  准备和 Start 使用同一排他边界。ACK 仅表示请求受理，不表示规划完成。
  同 request 重试不创建第二个线程；重启后 pending/UNKNOWN 保留核对状态。
- operator HTTP `POST /api/missions/{id}/prepare-placement` 只接受
  `{request_id, allow_planning:true}`，复用原 Host/Origin/Bearer 和节点身份隔离。
  不接受 spec、argv、目录、node、验收或 dispatch 参数。
- 新准备状态作为 snapshot 的独立 `placement_preparation` 字段投影；没有
  准备记录的旧任务不回填 metadata 或改动默认 local fingerprint。网页聊天、
  `/btw`、普通 snapshot 和重启都不自动调用 prepare。
- 显式 Start 读取同一已固定计划；准备完成后仍由原 worker 授权闸门决定
  是否运行。此处不以准备 ACK 替代 Start，也不自动清除 stop/pause/UNKNOWN。

## 实施前固定检查

- prepare-for-placement 只有显式 operator 调用和已绑定目标可进入。
- 固定初始计划和 native Lead 计划均能到达 WAITING_PLACEMENT，worker 数为零。
- 重复请求/已完成规划只读回，未知规划不重发；检查 hash 不变。
- 准備后真实 task hash 可供 N2 绑定；Start 使用相同 plan/placement。
- 准备与 Start/assign 的竞争在控制器内明确排序；未就绪保持待处理而非成功。
- 独立 reviewer、RSI child、holdout、integration 不获得节点选择权限。
- 默认本机路径的 fingerprint、cached receipt、停止/预算及原验收继续通过。
- 真实手机与第二台机器仍等待 Orchestra A7/A8；本机协议闭环不替代它们。
