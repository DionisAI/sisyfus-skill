# Engineering result web sidecar v1 — frozen W01–W14

本合同属于 Main 2026-10-07 选定的有界网页测试切片，不是原生模型、实际浏览器、手机、第二主机或研究收益验收。原 S0、Hub/Core 真值、验收、控制权限、所有旧测试及失败证据保持原样。生产源另需独立放行。

权威选择：`artifacts/techlead/orchestra-20261007/web-capture-main-0224a04ef9a54342a057ad78e238e50c/WEB-SAME-CAPTURE-TEST-AUTHORING-RELEASE-v1.md`。
运行时补充：同目录 `WEB-RUNTIME-SELECTION-ADDENDUM-v2.json`，只替换原先不存在的 Node 路径，不改变任何行为 oracle。

## 1. 同一捕获与精确 wire

现有 `GET /api/snapshot?mission_id=...` 使用 header `X-Sisyfus-Engineering-Result: 1`。不添加查询字段、第二路由或第二次结果轮询。

* 没有该 header：原 `id/snapshot/controller/controls` 精确四键，零 S0 导入、零投影。现有 auth/query/error/body/CSP 行为保持。
* `get_all` 得到恰好一个值且值为 `1` 才 opt in。其他值、重复值在原 security/query admission 之后、Hub 调用之前返回 HTTP400。其他路由忽略此 header。
* `cap = hub.snapshot(ident)` 只调用一次，原对象不变交给 positional `project_engineering_result(cap)`，调用一次。原四键的值直接交付，仅增加第五键 `engineering_result`。
* Hub 只在上游 redact snapshot；Handler.send 当前只 JSON 编码，不再次 redact wrapper。不存在新全 wrapper 清洗、JSON roundtrip 输入归一化、额外 Core capture、文件读取、模型、reservation、acceptance 或 control mutation。以 browser 收到的原四值为 S0 RFC6901 指针根。

第五值只有以下五键：

```json
{"schema":"sisyfus.lead_console.engineering_result_sidecar.v1","mission_id":"cap.id","status":"OK|REJECTED|FAILED","result":null,"error":null}
```

* OK：真实 S0 object；error=null。
* 真实 `EngineeringResultInputError`：REJECTED，result=null，error 精确 `{code}`，code 匹配 `[A-Z][A-Z0-9_]{0,31}`。
* 其他 Exception：FAILED，result=null，error 精确 `{code:"PROJECTION_INTERNAL_ERROR"}`；不展示异常文本/类型。
* BaseException 不消费。Hub capture 失败维持原 status/error，不拼 sidecar。局部投影 OK/REJECTED/FAILED 在有效 capture 时均为 HTTP200。
* OK 交付前验证真实 `protocol.redact(out) == out` 且 JSON 编码的 out 不含 server token 原文；否则 FAILED/REDACTION_ALTERED。已有 `[REDACTED]` 是 inert control，不是触发证据。此新 sidecar 护栏不构成原四值的全量 DLP 声明。

## 2. 原 S0 public shape，不发明 producer 字段

原模块/合同保持字节。Public API `project_engineering_result(hub_payload, /)`；原 exact4 输入。真实拒绝 fixture：snapshot.runs 缺失或非 list，固定 `SNAPSHOT_REQUIRED_FIELD`，不以普通 MALFORMED Fact 假冒顶层拒绝。

Positive 输出精确11组：schema、classification、question、conclusion、tasks、integration、attempts、control、provenance、limitations、diagnostics。schema=`sisyfus.lead_result.engineering.s0.v1`；classification=`CAPTURED_ENGINEERING_PROJECTION_NOT_ACCEPTANCE`。Fact `{state,value,source}`（不安全 key 可加 row_ordinal），RFC6901 转义，不重命名身份/路径。

* provenance.capture_basis=`CALLER_CAPTURED_NON_ATOMIC`；captured_at/event_cursor/event_head_hash=null；pinned/bytes_reverified/projection_is_acceptance=false；live_runtime=`NOT_PROJECTED`。没有新验收证明。
* task 没有 title。真实 candidate 与 patch 在 task.deliverable，patch rows 的 before/after 保留64位 hash；checks 的 measurement.scalars 保留0和false；review 展示理由与 evidence_refs；integration 的历史/冲突/当前证据保持原 meaning。
* 真实 VerificationResult serializer 是8键，不加第9键。
* 原 bounds 保持：任务256、runs/unresolved2048、checks/reasons/refs/paths/ids64、patch dictionary512、diagnostics8192、statements4096、statement sources64；measurement 每 check selected visits4096、root深度4、最多64 emitted scalars；selected depth16/global visits262144；S0 output8388608B。字符串、容器和其他分组边界沿用冻结 S0 合同/源，不抬限。
* 所有 positive fixture 来自真实 public S0；独立 raw fixture 字段、模板和 pointer 校准在目标断言之前。负向 corruption 是 wire admission 测试，不当成 fake positive S0。

## 3. Page admission、ownership 与 legacy

现有唯一 snapshot 请求加 header1。保留 readSerial/kind/id/epoch/version、graph/progress、inbox/context、IME/draft、事件时序与 Start 权限。

* outer id 存在就必须等于选定 mission，assignment 前校验。outer id 缺失仅在没有 sidecar 的 legacy response 接受；带 sidecar 缺失或错误 id 不赋成新 Core。
* sidecar exact5/schema/id/status/result/error、positive exact11/source-defined bounded shapes 与非原子/no-new-acceptance flags 严格校验。无效或缺失 sidecar 清除旧 positive；valid Core graph/progress 继续画。
* 真实 REJECTED/FAILED 是 code-only 局部状态，不变成 Core load failure、PASS 或 Start permission。
* switch 立即清除旧 result；当前 request failure 保留此前 owned result 且明确 STALE。complete deferred Promise 测 newer-before-older、A→B→A、error/recovery；不以未完成 Promise 的提前退出算通过。
* 相同 revision/count/status 但 hash/measurement/review 内容变更必须刷新 human result；signature 包含完整 content。
* 保持 sparse legacy fixture，不补齐成伪造 S0，不把缺失 sidecar 当成功。可继续显示原 graph/progress/control。

## 4. 可读、有界、data-only DOM

真实 mission-view 声明 `engineeringResult`、`engineeringResultStatus`、`engineeringResultBody`。status role=status、polite。中文浅色、安静 human-first：目标问题/结论，再原生 details/summary 展开具体增量、数值、理由、集成与来源。不只摆 raw JSON。

显示上限：tasks64；每 task patch40/checks24/reasons12；每 check scalars16；statements200；diagnostics50；新 result DOM nodes 总计≤3000。明确省略/截断和原 withheld/omitted 计数；不裁剪 Core graph、不抬 S0 cap。边界数据使用真实≤256-task/≤4096-statement public projection，不以大于源 cap 的 synthetic OK 绕过。

0与false不当空值；展开证据保留 full hashes。指针/hash/path 为 textContent 数据，不赋 href/src/on*、命令或文件访问能力。R08 使用冻结合同 literal primitives 的独立 oracle，接受规定 `[REDACTED]` 替换，不使用 regex.search==None 错判合法 marker。

局部 result renderer 标准 DOM creation 异常：清除局部 partial/positive、固定安全诊断、不泄露异常文本/token，恢复 identical payload 时重画；不破坏有效 Core、控制、inbox或连接。只在真实、健康 DOM fixture 已校准后注入标准 API creation fault；不移除 API 或替换 renderer。

原生 details keyboard/focus、polite 状态、窄屏 wrapping/reduced motion 与 IME/draft 保留；renderer/query 不自动 POST/Start/model，不升级 UNKNOWN permission。真实 layout/phone/浏览器另验。

## 5. 固定十四逻辑目标 / 有限 variants

|目标|固定行为与校准|
|---|---|
|W01|默认 exact4；一次真实 capture；零 import/project；原缓存/安全头|
|W02|一次真实 Hub/Core/S0；同对象/同 bytes；真实上游 Bearer marker transform；wire pointer equality|
|W03|empty/zero/duplicate opt-in；Host/Origin/Bearer/Node/query precedence；other route inert|
|W04|真实缺失/错误 runs typed rejection；200 REJECTED code-only，原四值不变|
|W05|真实 absent/bad-id capture errors；public projection negative Exception/BaseException，不假成功|
|W06|真实 redact改变/原 server token predicate 与 `[REDACTED]` control；secrecy只指 sidecar|
|W07|legacy 无/有 outer id，原 sparse shape；MISSING visible，一 snapshot GET/header1|
|W08|outer/side身份、schema/extra/status/error/groups/provenance/container bounds；真实局部 REJECTED/FAILED|
|W09|所有 deferred Promise 完成；newer-before-older、A→B→A、STALE/recovery|
|W10|same revision/count 内容刷新：改 patch/measurement/review，不止计数缓存|
|W11|真实集成/历史/冲突 S0，目标/结论/hash/0/false/理由/refs；不是 transport PASS|
|W12|真实有界 overflow、textContent/RFC6901/R08/Storage 与 HTTP CSP；不裁 Core|
|W13|健康 DOM 后 first/mid creation fault、安全局部失败、identical payload恢复|
|W14|真实声明/原生 disclosure/IME/draft/UNKNOWN gate，不 dispatch|

## 6. 唯一未来 RED 的精确能力范围

当前只静态编译与 SHA 冻结；零 pytest/Node/HTTP/Hub/SQL outcome。唯一 RED 等 Main immutable gate。

Python：installed release venv `<release-venv>/bin/python`，`-I -B`；runner 在 pytest import 前安装 process-local audit guard，调用原 `scripts/test_retained.py` 的 RetainedPaths/RetainedTemporaryFiles/guard_deletion（不执行其 CLI main）。只 collect 本新文件，不启用 cacheprovider；retained fixture/output/log/XML 全保留。

HTTP：SISYFUS_TEST_LOOPBACK=1；仅新 owned fixture 中 real Hub + 原真实 SQLite Stub surface；仅127.0.0.1:0 bind后登记 actual effective port，与此端口的 client；finite socket3s、entry2s、owned loop cleanup/join2s。无 Start/native/evaluator。

Node：runtime addendum 固定 realpath `<nvm>/versions/node/v24.12.0/bin/node`，SHA256 `90ee1d271eec831fd38d16c78c19cc36809548ac5cd034a6e0c10c4389c881ef`。不依赖 PATH、安装或 alias。原 HARNESS 与 _DOM_SUPPORT 原字节导入，不补 missing HTML，不实现 page 私有 functions。child argv 精确 `[node, new_owned_case.js]`、cwd=new child directory、stdin empty+EOF、env仅 LANG/LC_ALL、timeout15s、combined output≤1048576B。保留 code/argv/hash/startup/completion/finite Promise marker/stdout/stderr/returncode；Node 另有 filesystem/network/native/deletion 拒绝 guard，Python audit 不冒充 child guard。此 guard 约束冻结的自有 code，不声称 hostile-code sandbox。

保留永久删除 guard；无 remove/rename/Trash、生产/旧 DB、credential/provider/native/SSH/device/cleanup、全局工具配置变化。只允许一次120s pytest window；超时或 setup/helper/oracle failure单列，禁止自动重跑/skip/xfail。导入/返回记录 source pins；Main可另 gate source candidate，不覆盖冻结父 pins。所有旧失败保持。GREEN、独立原生 source review、实际 browser、第二主机、phone、public two-venue economics各自分列。
