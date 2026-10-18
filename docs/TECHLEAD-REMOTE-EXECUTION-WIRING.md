# 远端执行最终接线

这是原生 Opus Lead 接线建议的控制器细化，仍为待实施切片。
完整 Orchestra A1–A8、N1–N6 与原固定验收保持；下述源码接线不等于部署。
原建议和哈希读回保留在本轮 native-remote-wiring-design-v1。

## W1/W2：控制器准入与候选

- `LeadMission.remote_execution_ready` 是 host-owned 只读 callable，默认
  返回 False。不持久、不加入 spec，不修改既有 placement 的
  `execution_ready:false`。trial child 和直接构造默认保持本机。
- 准备完成后的 Start 只用该 callable 判断传输是否启用；在它返回字面
  True 之前，远端仍等待、不消耗任务尝试、不静默回到本机。登记、心跳、
  页面、普通聊天和 native 计划均不改变此能力。
- 默认本机 fingerprint、roles 内容、cached receipt 与错误闸门保持。
  只有新远端 reservation 的 fingerprint 额外固定完整 placement。
  已确认 canonical envelope 为 `digest({arguments,task,spec:digest(spec),
  placement:full_pin})`；本机原三字段保持，full_pin 不去掉 staging false。
  replay 先读原 canonical receipt/固定运行身份，不据当前机器重新派发。
- 新远端准入在原 reserve 事务内复核所观察 placement、ACTIVE 同任务
  node、固定 task hash、implementation/trial 排除与 host readiness。
  原 inbox.bind 与新 `run_placements` 记录同事务，失败一起回滚。
  role/driver/model/mode/原 cwd、node、snapshot/candidate 路径与 placement
  固定在该记录；它从来不提供验收或路径扩权。
- `LeadJournal.record_in(db, category, key, data)` 复用原 record 的 body，
  不嵌套事务；原 record 仅包一层原事务，shape、脱敏、幂等和事件不变。
  NodeClaims 的 lazy 初始化仍在 reserve 事务外完成。
- 只为普通 workers.execute 使用新分支。Lead、reviewer、integration、RSI
  和试验调用保持原路径，controller continuation 续租仍归原 runtime。
- 原 build_candidate 完成后，output_paths 固定为全部 prepared regular
  inputs 加明确文件写入路径；已有目录不被扩大成任意新增文件 allowlist。
  128 entries 及原包/单文件边界保持。未支持的树/路径留下 INVALID 诊断。
- RemoteCodexDriver 接受原 Request.cwd、固定 request/资料、运行 identity
  与 node；独占 remote-input 和 remote-candidate 各叶目录。事件已通过
  N1 提交的 native 接受/ACK 不再次发射；无新 reserve/complete/续租者。
- **当前成功 materialization 没有 status 字段**：精确结构是
  `{candidate:str,before:str,delta:dict}`，其中 delta.valid 必须为 True。
  before 是独立目录路径，不是 bytes/hash map。先以该目录实际文件/完整
  树读回对照原 prepared before，再以返回 candidate 计算原 patch/scope、
  输出限制和最终 artifact；同时确认原 Request.cwd 未变。
  原建议中 `MATERIALIZED` 和直接 `mat.before == before` 不作为实现接口。
- INVALID、NOT_MATERIALIZED、未知或缺 candidate 的结果绝不进入成功候选。
  已知 native 状态保持，附 integrity_error；UNKNOWN 保持未知及原件。
  Journal.complete、原 checker、独立审核、evidence_current 和 integration
  仍是原来的独立闸门，物化和 node receipt 不是 PASS。

## W3：host 服务生命周期

- MissionHub 可显式 `attach_node_gateway(gateway, *, serve_thread)`；Thread
  由 host 创建并传入，当前 NodeGateway 没有公开 serve_thread 属性。
  要求同 hub、真实 loopback listener、活跃 serve thread/未关闭 socket。
  第二次 attach 冲突；detach 幂等，只撤销进程内 readiness。
- Hub 给新旧 session 注入它自己的 readiness callable；不由 HTTP body
  注入。projection 单列 `{gateway,effective_ready,basis}`，说明这只是传输
  listener，不是节点在线、native 登录或任务验收。原库存字段保持。
- 固定公开只读 `MissionHub.node_gateway_state()` 返回上述三字段；未接入为
  gateway:null / effective_ready:false。gateway 只含固定 loopback url/host，
  basis 为非空诊断文字，不含 token 或 secret。session 的原
  `remote_execution_ready()` 只读取 host 生命周期，不能修改 spec/旧pin。
- 仅 CLI hub/serve/up 的显式 `--node-gateway-port` 接入；省略时保留原路径
  与输出。先成功绑定/启动独立 loopback gateway，再启用远端，最后绑定
  operator console；只有原明确 up/Start 权限派发任务。
  实际入口已静态核对为 `src/sisyfus/workers/lead_cli.py`（entrypoint.py 路由），
  不是顶层旧 cli.py。new/run/status 不接受该服务选项。
- listener/bind/attach 失败明确退出，零 worker；重启不自动 Start。
  关闭时保持 gateway 可供已有控制器合作停止/回执，等待后 detach 并关闭
  服务；保留未知执行、工作区和失败，无清除或永久删除动作。
- node-only 端口与 operator token/路由分开，默认地址不放宽。SSH 转发、
  第二台机器和手机入口仍由用户选择，不在此自动建立。

## W4 与验证

NodeAgent CLI 仅收固定0600 credential-file 与持久0700 state-directory，
不用 secret argv/env 或复制 provider 登录。默认 run_once 一次；显式有限
NO_WORK polling 也只重复查询/领取，IN_FLIGHT/UNKNOWN 从不重启 native。
具体 NodeAgent 公开 return/关闭接口以稳定模块为准，新增检查前静态核对。

先静态核对当前公共 shape，再冻结新增 W1/W2、服务和 CLI 检查，保留 RED。
控制器与 standalone 源码独立审核期间保持各自 source hashes；接线实施
按不重叠写入范围推进。固定本机、缓存、暂停/停止、UNKNOWN、资料与 RSI
检查及旧失败保留。随后 N6 真实 loopback 两进程协议闭环，明确记为 staging。
原生本机传输演练与 A7 真正第二台机器、A8 实际手机分别记录，不相互替代。
