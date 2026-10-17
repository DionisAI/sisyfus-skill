# W4：独立 NodeAgent CLI 冻结契约

本切片由明确 `gpt-6.1-sol` 编写新增测试及本文件，CLI 源模块留待主控
在 NodeAgent micro gate 后显式 release。W2 和其它既有源码、测试、合同保持
冻结；此契约及 loopback fixture 与真正第二台机器、手机、部署验收分别记录。

## 入口和参数

```text
python -m sisyfus.workers.node_cli --credential-file PATH --state-directory PATH
    [--idle-polls N] [--poll-seconds S]
```

- 两个 PATH 必需，直接交给公开 `NodeAgent(credential_file, state_directory)`。
  固定配置、0600 普通单链接 NOFOLLOW 凭据文件、0700 持久状态目录、真实目录
  祖先、当前用户和独占锁仍由 NodeAgent 核对。CLI 保留原文件/状态/失败目录，
  不修补权限、不复制凭据、不递归准备缺失的父目录、不清理旧执行。
- 默认恰好一次 `run_once()`；默认额外 idle 次数为 0。
- 显式 `--idle-polls N` 为 **额外** NO_WORK 查询次数，ASCII 十进制整数
  `1..100`。最多 `1+N` 次 run_once、N 次 sleep，始终使用同一个 Agent。
- `--poll-seconds S` 是有限数 `0.01..30` 秒，默认 `0.2`。单独指定 S 仍只
  run_once 一次，绝不暗中启用轮询。只在准备下一次 NO_WORK 查询前 sleep；
  最后一次查询或任何其它结果之后都没有额外 sleep。
- `-h` / `--help` 只显示本入口帮助、退出 0。所有其它参数、位置命令、参数
  缩写及重复单值参数均为 parse 错误，在 Agent 构造、文件读取或网络前结束。
  没有 secret、model、host、gateway、env-copy、shell、Start 或无限循环参数。

## 公开方法、返回值与停止边界

静态核对当前接口为 `NodeAgent(credential_file, state_directory, *, driver=None)`
和 `run_once(self)`，没有 CLI 可依赖的公开 close/context-manager 契约。
CLI 仅构造一次、调用 run_once，并把持久 request identity 的管理交还 NodeAgent；
不直接触及它的私有数据库、outbox、offer、续租或 native 方法。

有效结果严格为 `{request_id:str,status:str}`；request_id 为当前公开 Agent 生成的
`agent_` 加 32 个小写十六进制字符。CLI 输出一行最终结果 JSON，不增加 verdict、
all_verified、candidate、secret 或 receipt 字段，不从 native 状态猜任务验收。

| 最终结果 | 退出码 | 轮询 |
| --- | --- | --- |
| NO_WORK | 0 | 仅仍有显式额外次数时继续 |
| RECEIPTED | 0 | 立即结束 |
| UNKNOWN | 2 | 立即结束 |
| RECONCILIATION_CANDIDATE | 2 | 立即结束 |
| 错误、其它状态、坏 shape / identity | 1 | 立即结束 |
| KeyboardInterrupt | 130 | 立即结束 |

RECEIPTED 是传输回执，可能对应已知 native ERROR / INTERRUPTED；它与 PASS、资料
执行合规、checker、独立审核、集成无等号。CLAIMED、IN_FLIGHT、DONE、COMPLETED、
ERROR 等不是这个 run_once 公开终结 shape 的成功别名；遇到它们显式报错，绝不
再轮询或启动第二次任务。已有 IN_FLIGHT / UNKNOWN 仍由原 Agent 做一次同身份
状态读回，CLI 不再领取、补发、重建工作区或调用 native。

## 错误和进程边界

- 正常/未知结果只在 stdout 输出最终两字段 JSON，stderr 为空。
- 错误 stdout 为空，stderr 恰好一行 JSON：
  `{status:'ERROR',stage,error_type}`。stage 固定为 parse、construct、run_once、
  result 或 poll。parse 错误也退出 1；常规 argparse 的错误退出 2 在这里留给
  UNKNOWN / reconciliation。帮助仍退出 0。
- KeyboardInterrupt 保留发生的 stage，诊断 status 为 INTERRUPTED，类型为
  KeyboardInterrupt，退出 130；这仅说明 CLI 被中断，不证明 native 已停止。
- 诊断不回显 argv、路径、返回的异常字段、凭据内容、异常 message / traceback。
  error_type 只使用受限内建异常类名；自定义异常类名使用固定 Exception，避免
  类名本身携带秘密。所有诊断错误传播到对应非零退出码，没有重试成功别名。
- 复用 NodeAgent 和原 driver 的环境过滤；CLI 没有 provider 登录、环境复制、
  SSH、远端主机选择或公开网络入口。NodeAgent 自己保留有限 HTTP/native 边界。
- 任何移除只遵循 `/usr/bin/trash ABSOLUTE` 两个 argv、无 `--` 的既有政策。
  CLI 生命周期无需移除动作；所有输入、状态和失败留存。

## 仅供测试的公开依赖注入

未来模块固定 `main(argv=None, *, agent_factory=None, sleep=None) -> int`；模块入口
以 `SystemExit(main())` 返回该退出码。默认 factory 在 parse 成功后才取公开
NodeAgent，默认 sleep 为 time.sleep。测试 factory 接收恰好两个路径位置参数，
没有 driver/model/env 关键字；注入只固定状态机行为，没有对应的命令行开关。
fixture Agent 只实现 run_once，CLI 不假设 close 或额外方法。

新增冻结测试使用三类分别标记的证据：公开接口静态读回、Scripted factory 的
确定状态/有限轮询/错误边界，以及真实认证 loopback gateway 的默认 NO_WORK、
持久 UNKNOWN 重启。真实 CLI 子进程采用临时 fixture 审计：禁止 native process、
provider/SSH 和非该 gateway 的连接，保留永久删除保护与逐次独占 guard marker。
凭据均为该 fixture 新登记的合成身份，0600 文件在 state/workspace 外，原件和
失败都保留。原源码/测试 SHA 和 absent-module RED 在 release 前固定；不以这批
协议检查替代 NodeAgent micro 独立审查、W2 combined gate 或 N6/A7/A8 实际验收。
