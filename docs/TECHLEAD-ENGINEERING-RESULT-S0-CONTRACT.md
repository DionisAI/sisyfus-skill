# Engineering Result S0 — 独立纯投影合同（NEW 静态 draft）

**阶段：STATIC DRAFT / OUTCOME HOLD。** 本文件与 NEW 测试供 Main 冻结前核对。尚未运行测试、真实 fixture capture 或实现生产源码。旧合同、旧测试、既有失败和设计回执保持原字节。设计、静态核对及将来的 fixture GREEN 分别记录；均不是 native SOURCE / Web / 手机 / 第二主机验收。

## 1. 权威来源与本轮范围

- `artifacts/techlead/orchestra-20261006/engineering-result-S0-main-selection-v1.json`
  SHA256 `76cbe2583b6733a8f8c7642a41a0d77891b1f966c9ca12211b73b5aa2dfc7463`

- `artifacts/techlead/orchestra-20261006/engineering-result-S0-main-selection-v1-addendum.json`
  SHA256 `50cb54fc579ded700aaa99d4a13ae25dc90cdef03ceb76a9f2c21c7fa9fd5fb9`

- `artifacts/techlead/orchestra-20261006/engineering-result-S0-main-selection-v1-addendum2.json`
  SHA256 `cec3323da6bae437b81835b0866398c52a195042b0e4e1bd5fb8eec2d8eff9d9`

- `artifacts/techlead/orchestra-20261006/engineering-result-native-design-v3-8e78b4101e564afaa37fd54adca095af/outcome/proposal.json`
  SHA256 `bba33ff72fb1924d6624608911886ae55fdd22edbd294ff24d4df034397eb3f3`

- requested implementer：`gpt-6.1-sol`；runtime attestation 单列，不由请求名推断。

- 本轮仅新增此合同、`tests/workers/test_lead_result.py` 与独占 artifact。`src/sisyfus/workers/lead_result.py` 仍 ABSENT / SOURCE HOLD。

- 输入仅是调用方已经捕获、controller-redacted 的 `{id,snapshot,controller,controls}`。S0 是纯参数投影，零 ENV / SQL / filesystem / clock / network / native / control mutation，不调用 `protocol.redact`、`digest`、`bounded`；没有 W3 reader、报告 job、生成、HTTP、页面或权限 API。

- Mission 的默认全局预算仍为 null/unlimited；本投影不创建 reservation，不增加计费或预算行为。

## 2. 精确公开 API 与输入边界

```python
def project_engineering_result(hub_payload: object, /) -> dict[str, object]: ...
class EngineeringResultInputError(ValueError):
    code: str
```

def project_engineering_result(hub_payload: object, /) -> dict[str, object]。同模块公开 class EngineeringResultInputError(ValueError)，只有一个属性 code: str，取自封闭拒收码集合；str(exc) 固定为 'engineering result input rejected: ' + code。抛出时使用 raise ... from None，不链接原异常，不回显输入。模块只能导入 __future__、json、math、re、typing，禁止导入任何 sisyfus 模块，包括 protocol（避免 redact 读取 ENV、递归无预算），也禁止 os/time/threading/sqlite3/socket/subprocess/pathlib/hashlib。

hub_payload 必须是 type(x) is dict，键集合恰为 {'id','snapshot','controller','controls'}，即 G02_OUTER 中 MissionHub.snapshot 的返回形状。controller 与 controls 只检查键存在，不遍历、不复制。id 是 str，UTF-8 1..128 字节，满足 ^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$。这条词法规则是提案，测试冻结前必须用真实 Hub ID 生成器的输出核对，不一致就修订契约，不放宽成任意字符串。snapshot 必须是 exact dict，即调用方已捕获、已经过 redact(snap) 的 M02 LeadMission.snapshot 值；本函数承认的上游脱敏只限这一层。必需键：objective（str）、phase（token）、revision 与 resume_epoch（非 bool 的 int，取值 0..2**63-1）、nodes 与 runs（exact list）、integration（exact dict）、unresolved（exact list）。可选键缺失记为 NOT_RECORDED，提供则严格校验：paused、stopped、project_verified、all_verified（exact bool）和 reason（str）。其余 snapshot 键（plans、diagnoses、format_errors、reviews、procedure、improvements、improvement_errors、rsi、rsi_configuration、procedure_trials、counters、budgets、budget_display、*_reservations、max_calls、controller_errors、roles、validation_kind、versions、placement_preparation 及将来的新增键）一律不遍历、不复制。所有被选分支只接受 exact builtin dict、list、str、int、float、bool、None。dict 子类、tuple、Mapping、自定义对象、bytes 出现在必需信封位置时拒收；出现在节点或证据内部时记一条分段诊断，并去掉该段的正向标签。title、mission_id、event cursor、event head 在输入中不存在，也不会被构造。

MS11 增补：在任何选定 dict lookup / key hash / equality / sort 前，先检查 exact dict、有限 key 基数、每个 key 的 exact builtin str 类型。禁止调用用户 key 的 `__hash__`、`__eq__`、repr 或自定义迭代。未知 key 只做有界结构核对；未知 value 不取、不遍历、不复制。controller/controls 仅要求信封 key 存在。

字典 key 基数：envelope 恰为 4；其余如下（超限整体 LIMIT_EXCEEDED，不做部分投影）：

```json
{
  "snapshot": 128,
  "task": 64,
  "verification": 32,
  "evidence": 128,
  "integration": 8,
  "continuation": 64,
  "continuation_context": 64,
  "run": 64,
  "run_receipt": 128,
  "build_record": 16,
  "build_data": 128,
  "check": 16,
  "classification": 16,
  "review": 16,
  "patch_item": 2
}
```

patch map / dependencies map / check_hashes map 沿用 512 / 64 / 64；measurement 沿用访问 4096 与 key-pattern 限制。所有被选择的字典都应用 exact str key 前置边界，未选择的 controller/controls 内容不检查。

## 3. 精确输出 schema

唯一 schema：`sisyfus.lead_result.engineering.s0.v1`；classification：`CAPTURED_ENGINEERING_PROJECTION_NOT_ACCEPTANCE`。顶层字段与顺序严格如下：

```json
[
  "schema",
  "classification",
  "question",
  "conclusion",
  "tasks",
  "integration",
  "attempts",
  "control",
  "provenance",
  "limitations",
  "diagnostics"
]
```

下列是被选择的完整原 schema；MS01–MS15 是唯一覆盖修正。Fact 的 missing/null 不等于 PASS。unsafe key 的 parent source / row_ordinal 是显式元数据，绝不拼回原 key。字段插入顺序固定，新建全部 dict/list，不共享任何输入容器，JSON 序列化确定且拒绝 NaN/Inf。

```json
{
  "Artifact": {
    "candidate_hash": "Sha（文件 hash map 的 digest，不是单个文件 hash，也不是 diff hash）",
    "candidate_location": "常量 'WITHHELD_ABSOLUTE_LOCATOR'，绝对 candidate 路径永不输出",
    "patch": {
      "row_count": "int，源 dict 的精确条目数",
      "rows": "[{path, change_kind, before, after, source}]，按 path 的码点排序。path 是安全标签或 null；change_kind 取值 ADDED|REMOVED|MODIFIED|REDACTED_AT_CAPTURE|WITHHELD|MALFORMED；before 与 after 是 64 位十六进制或 null",
      "withheld_count": "int"
    },
    "run_key": "Fact<str>"
  },
  "Check": {
    "candidate_hash": "Sha",
    "check": "Fact<str>",
    "check_hash": "Sha",
    "id": "Fact<str>",
    "measurement": {
      "complete": "bool（只有 omitted 与 withheld 都为 0 时为 true）",
      "execution_error_recorded": "bool|null",
      "omitted_scalar_count": "int，精确值",
      "scalars": "[{name: 点分路径, value: int|float|bool, source}]，≤64 个，按名称排序",
      "withheld_count": "int，精确值"
    },
    "status": "Token（classification.status，按记录原样）",
    "summary": "Text（classification.summary，评估器自己的说明）"
  },
  "Diagnostic": "{code, section, source}。code 来自封闭诊断码集合，section 取值 mission|task|check|measurement|review|integration|build|attempt。只有固定码和定位，不含原文。",
  "Fact<T>": "{state, value, source}。state 取值：RECORDED、FILTERED、NOT_RECORDED、REDACTED_AT_CAPTURE、WITHHELD、MALFORMED。value 仅在 RECORDED 或 FILTERED 时非 null。source 是以 hub_payload 为根的 RFC 6901 JSON Pointer（~0、~1 转义；数组下标是原始下标，不是重排后的位置）。若 key 本身不安全无法回显，pointer 只写到父容器，另加 row_ordinal（排序后序号），不回显 key。",
  "Review": {
    "candidate_hash": "Sha",
    "evidence_refs": "[Fact<str>]",
    "reasons": "[Text]（已解析的 canonical 审查理由，作为归属意见引用）",
    "recorded": "bool",
    "references_cover_recorded_checks": "bool|null",
    "run_key": "Fact<str>",
    "verdict": "Token"
  },
  "Sha": "Fact<str>，满足 ^[0-9a-f]{64}$；完整保留，不缩写。",
  "Task": {
    "acceptance": "Text（旧版缺失时为 NOT_RECORDED；它表示预期要求，不是已实现）",
    "acceptance_fingerprints": {
      "acceptance_hash": "Sha",
      "check_hashes": "[{check: Fact<str>, check_hash: Sha}]，按 check 名排序",
      "dependencies": "[{task_id: Fact<str>, evidence_id: Fact<str|int>, matches_captured_upstream: bool|null}]",
      "task_hash": "Sha"
    },
    "check": "Fact<str>",
    "checks": "[Check]",
    "currentness": {
      "active": "Fact<bool>",
      "label": "CURRENT_AS_CAPTURED | STALE | SUPERSEDED | INACTIVE | STATE_NOT_SUCCEEDED | NOT_APPLICABLE | UNDETERMINED",
      "stale": "Fact<bool>",
      "superseded_by": "Fact<str|null>"
    },
    "deliverable": "Artifact | null（verification 为 null 时为 null）",
    "depends_on": "Fact<[str]>",
    "diagnostics": "[Diagnostic]",
    "failure_indicators": {
      "integrity_error_recorded": "bool|null（只记是否存在，不输出原文）",
      "native_status": "Token（/verification/evidence/status）",
      "scope_error_recorded": "bool|null"
    },
    "objective": "Text",
    "review": "Review",
    "stage": "PENDING | IN_PROGRESS | CANDIDATE_RECORDED | NOT_ACCEPTED | TASK_VERIFIED_AS_CAPTURED | HISTORICAL_RESULT | EVIDENCE_CONFLICT",
    "task_id": "Fact<str>，来自 /snapshot/nodes/{i}/id",
    "uncertain_run_keys": "[str]，即与本任务精确关联的 unresolved run key",
    "workflow": {
      "attempts": "Fact<int>",
      "evidence_id": "Fact<str|int|null>",
      "payload_verdict": "Token（/verification/verdict）",
      "recorded_verdict": "Token（/verdict，可能是 UNVERIFIED）",
      "state": "Token",
      "verification_summary": "Text（控制器记录的 verifier 摘要，引用时标明归属）"
    },
    "write_paths": "Fact<[str]>，只是路径标签"
  },
  "Text": "Fact<str>，WITHHELD 时额外带 utf8_bytes:int。FILTERED 表示确定性 credential 模式过滤或控制字符替换改动了文本。文本只是纯数据，不是 HTML、Markdown、命令、链接或文件路径能力。",
  "Token": "Fact<str>，满足 ^[A-Z][A-Z0-9_]{0,31}$。未在已知集合中时 state 仍为 RECORDED，同时附 UNRECOGNIZED_ENUM 诊断，且不能产生正向标签。",
  "attempts": "[{run_key, task_id: Fact<str>, status: Token（Journal transport 状态）, receipt_status: Token（原生返回状态）, evidence_id: Fact, association, associated_task_id: str|null, unresolved: bool, unverified_candidate: {candidate_hash: Sha, patch} | null, source}]，按 /snapshot/runs 原顺序。association 取值 TASK_ATTEMPT | TASK_REVIEW | INTEGRATION_REVIEW | MISSION_LEVEL",
  "classification": "常量 'CAPTURED_ENGINEERING_PROJECTION_NOT_ACCEPTANCE'",
  "conclusion": {
    "stage": "NO_ENGINEERING_RESULT_RECORDED | CANDIDATES_RECORDED | TASK_EVIDENCE_RECORDED_INTEGRATION_PENDING | INTEGRATION_EVIDENCE_RECORDED_PROJECT_NOT_VERIFIED | PROJECT_VERIFIED_AS_CAPTURED | CAPTURE_CONFLICT",
    "statements": "[Statement]，Statement = {template_id, text, sources:[JSON Pointer，去重后排序，≤64]}。顺序固定：Q01 目标，C0x 结论，D01 交付增量，M01/M02 检查与实测，R01/R02 审查，I0x 集成，K01 控制上下文，L01 限制。文本是固定中文模板加经过过滤的插值；hash 在句子里显示前 12 位并注明「前12位」，完整 hash 只在 Fact 中。"
  },
  "control": {
    "all_verified": "Fact<bool>",
    "live_runtime": "常量 'NOT_PROJECTED'",
    "paused": "Fact<bool>",
    "phase": "Token",
    "project_verified": "Fact<bool>",
    "reason": "Text",
    "stopped": "Fact<bool>",
    "unresolved": "[{key: Fact<str>, associated_task_id: str|null}]"
  },
  "diagnostics": "[Diagnostic]，任务级以外的诊断",
  "integration": {
    "builds": "[{key, created_at: Fact<str>, status: Token, run_key, candidate_hash: Sha, patch, dependencies, label: 常量 'CANDIDATE_ONLY_NOT_ACCEPTANCE', source}]",
    "continuation_id": "Fact<str|int>",
    "continuation_state": "Token",
    "current": "Fact<bool>（按记录原样，不重新计算）",
    "diagnostics": "[Diagnostic]",
    "evidence_continuation_id": "Fact<str|int>",
    "evidence_id": "Fact<str|int>",
    "lead_integration_revision": "Fact<int>",
    "payload_verdict": "Token",
    "recorded_verdict": "Token",
    "result": "{deliverable: Artifact, checks: [Check], review: Review, acceptance_hash: Sha, check_hashes, dependencies, failure_indicators} | null；没有 task_hash",
    "stage": "PENDING | INTEGRATION_CANDIDATE_RECORDED | NOT_ACCEPTED | INTEGRATION_VERIFIED_AS_CAPTURED | HISTORICAL_RESULT | EVIDENCE_CONFLICT"
  },
  "limitations": "[{code, text}]，固定列表：NO_FILE_CONTENT、NON_ATOMIC_CAPTURE、NO_REVERIFICATION、SPEC_NOT_IN_SNAPSHOT、NOT_DLP、NO_LIVE_RUNTIME、NO_RESEARCH_RESULT、NO_DEVICE_OR_SECOND_HOST_ACCEPTANCE、MEASUREMENT_SELECTION_PARTIAL_BY_POLICY",
  "provenance": {
    "bytes_reverified": "常量 false",
    "capture_basis": "常量 'CALLER_CAPTURED_NON_ATOMIC'",
    "captured_at": "常量 null（本函数不读时钟）",
    "event_cursor": "常量 null（未提供）",
    "event_head_hash": "常量 null（MissionHub.snapshot 中不存在）",
    "mission_id_source": "常量 '/id'",
    "pinned": "常量 false",
    "projection_is_acceptance": "常量 false",
    "redaction": "常量 'UPSTREAM_CONTROLLER_REDACT_ASSUMED_PLUS_S0_PATTERN_FILTER_NOT_DLP'",
    "resume_epoch": "Fact<int>",
    "revision": "Fact<int>",
    "selected_source_fields": "固定 pointer 模板列表，与 source_mapping 一致"
  },
  "question": {
    "mission_id": "Fact<str>，source '/id'",
    "objective": "Text，source '/snapshot/objective'"
  },
  "rule": "返回新建的 dict 和 list，与输入完全分离：任何输出容器都不是输入容器的同一对象，只共享不可变的 str、int、float、bool。字段顺序固定，输出顺序就是给人阅读的顺序。同一输入产生 == 且 json.dumps(sort_keys=False, ensure_ascii=False, allow_nan=False) 字节相同的结果。",
  "schema": "常量 'sisyfus.lead_result.engineering.s0.v1'",
  "tasks": "[Task]，按 /snapshot/nodes 原顺序",
  "top_level_key_order": [
    "schema",
    "classification",
    "question",
    "conclusion",
    "tasks",
    "integration",
    "attempts",
    "control",
    "provenance",
    "limitations",
    "diagnostics"
  ]
}
```

附加精确约束：patch row 基本键为 `{path,change_kind,before,after,source}`，仅在 withheld key 时加 `row_ordinal`；Fact 基本键 `{state,value,source}`，只允许对应场景的 `row_ordinal` / `utf8_bytes`。Diagnostic 仅 `{code,section,source}`，没有输入原文或任意 message。build label 精确为 `CANDIDATE_ONLY_NOT_ACCEPTANCE`，不使用 FC16 简写 `CANDIDATE_ONLY`。

真实 VerificationResult serializer 精确 8 键：

```json
[
  "assurance",
  "evidence",
  "lessons",
  "metrics",
  "summary",
  "verdict",
  "verification_mode",
  "verifier_id"
]
```

integration.result 仅 `{deliverable,checks,review,acceptance_hash,check_hashes,dependencies,failure_indicators}`；没有 task_hash。provenance.pinned / bytes_reverified / projection_is_acceptance 固定 false；captured_at / event_cursor / event_head_hash 固定 null；mission_id_source 固定 `/id`。

## 4. 精确来源映射

```json
[
  {
    "meaning": "Hub 信封给出的身份。snapshot 顶层没有 mission_id，也不从路径、run key 或 objective 重建。",
    "output": "question.mission_id",
    "source": "/id（G02_OUTER 中的 ident）"
  },
  {
    "meaning": "已冻结的任务意图，只是问题本身，不是已完成的证明。",
    "output": "question.objective",
    "source": "/snapshot/objective（M02 中的 self.spec['objective']）"
  },
  {
    "meaning": "捕获时控制器的元数据，只用于定位，不是 CAS 或租约，pinned=false。",
    "output": "provenance.revision / resume_epoch",
    "source": "/snapshot/revision、/snapshot/resume_epoch（M02）"
  },
  {
    "meaning": "记录的控制状态。STOPPED 不表示进程已终止，COMPLETED 不表示原生返回成功。",
    "output": "control.phase / reason / paused / stopped",
    "source": "/snapshot/phase、/reason、/paused、/stopped（M02 中的 phase 推导）"
  },
  {
    "meaning": "按记录原样展示的控制器标志。all_verified 另外取决于 trial IDLE，不能用任务计数推出；缺失时不视为成功。",
    "output": "control.project_verified / all_verified",
    "source": "/snapshot/project_verified、/snapshot/all_verified（M02）"
  },
  {
    "meaning": "状态为 UNKNOWN 或 IN_FLIGHT 的待核对调用。精确关联不上的保留在 mission 级。",
    "output": "control.unresolved / tasks[].uncertain_run_keys",
    "source": "/snapshot/unresolved/{k}，按精确 key 关联 /snapshot/runs/{r}/key 和 /task_id"
  },
  {
    "meaning": "已冻结的任务契约。没有 title；interface、repair_of、driver、max_attempts 不展示。",
    "output": "tasks[].task_id / objective / check / depends_on / write_paths / acceptance",
    "source": "/snapshot/nodes/{i}/{id,objective,check,depends_on,write_paths,acceptance}（T01_02_NORMALIZE 规范化后的任务字段，M02 中的 {**task}）"
  },
  {
    "meaning": "continuation 工作流状态，不证明进程健康。",
    "output": "tasks[].workflow.state / attempts",
    "source": "/snapshot/nodes/{i}/state、/attempts（M02 中的 cont['state']，默认 ADMITTING；attempt_count）"
  },
  {
    "meaning": "三个独立的当前性事实。stale=false 只在 state 为 SUCCEEDED 时有意义。",
    "output": "tasks[].currentness.active / superseded_by / stale",
    "source": "/snapshot/nodes/{i}/active、/superseded_by、/stale（M02）"
  },
  {
    "meaning": "canonical evidence 行上记录的裁决。没有行时为 UNVERIFIED，属于正常缺失。",
    "output": "tasks[].workflow.recorded_verdict / evidence_id",
    "source": "/snapshot/nodes/{i}/verdict、/evidence_id（M02 中的 latest_evidence 行）"
  },
  {
    "meaning": "verifier payload，必须与行裁决一致才可能有正向标签。summary 作为归属文本引用。",
    "output": "tasks[].workflow.payload_verdict / verification_summary",
    "source": "/snapshot/nodes/{i}/verification/verdict、/summary（VerificationResult.as_dict 中的 verdict、summary）"
  },
  {
    "meaning": "记录的候选文件 map digest。本函数不读取文件、不重新哈希。",
    "output": "tasks[].deliverable.candidate_hash / run_key",
    "source": "/snapshot/nodes/{i}/verification/evidence/candidate_hash、/run_key（M04 中的 receipt.update(candidate_hash=sha)；M07 中的 data['run_key']）"
  },
  {
    "meaning": "文件 hash 的增量，只能说明新增、删除或内容改变，不含代码正文，也不推断功能或收益。",
    "output": "tasks[].deliverable.patch.rows[].{path,before,after,change_kind}",
    "source": "/snapshot/nodes/{i}/verification/evidence/patch/{path}/before|after（M04 中的 patch[p]={before,after}，只保留 before≠after 的条目）"
  },
  {
    "meaning": "原生返回状态和错误是否存在，与 verifier 裁决是不同维度。原始错误文本不输出。",
    "output": "tasks[].failure_indicators.native_status / *_error_recorded",
    "source": "/snapshot/nodes/{i}/verification/evidence/status、/integrity_error、/scope_error（M04 中的 receipt.update(status|scope_error)；M06 的 verify 分支）"
  },
  {
    "meaning": "已记录检查的身份和固定评估器指纹，用于和所属候选做一致性比对。",
    "output": "tasks[].checks[].{id,check,check_hash,candidate_hash}",
    "source": "/snapshot/nodes/{i}/verification/evidence/checks/{j}/{id,check,check_hash,candidate_hash}（M06 中 saved 加 id=key）"
  },
  {
    "meaning": "评估器自己的分类和说明，不重新 classify。exit=0 或原生 COMPLETED 不会被换算成 PASS。",
    "output": "tasks[].checks[].status / summary",
    "source": "/snapshot/nodes/{i}/verification/evidence/checks/{j}/classification/status、/summary（M06）"
  },
  {
    "meaning": "已记录测量中有界选出的有限数值或 bool 标量，名称就是记录中的 key。字符串和复合值只计数后不输出。这是测量记录，不是改进结论。",
    "output": "tasks[].checks[].measurement.scalars / execution_error_recorded",
    "source": "/snapshot/nodes/{i}/verification/evidence/checks/{j}/measurement/...（M06 中 redact(observation)，含 execution）"
  },
  {
    "meaning": "已解析的 canonical 独立审查。reasons 是归属意见；evidence 应为精确的 check id；run_key 应等于 'review:'+evidence.run_key。不读 receipt.output。",
    "output": "tasks[].review.{verdict,reasons,evidence_refs,run_key,candidate_hash}",
    "source": "/snapshot/nodes/{i}/verification/evidence/review/{verdict,reasons,evidence,run_key,candidate_hash}（M07）"
  },
  {
    "meaning": "按记录原样的验收指纹，dependencies 的值是上游 evidence id。snapshot 不含冻结 spec，所以无法独立再验。",
    "output": "tasks[].acceptance_fingerprints.{acceptance_hash,check_hashes,task_hash,dependencies}",
    "source": "/snapshot/nodes/{i}/verification/evidence/acceptance_hash、/check_hashes/{check}、/task_hash、/dependencies/{task_id}（M06 中 data.update；M04）"
  },
  {
    "meaning": "集成工作流的身份和状态，lead_integration 只与 /snapshot/revision 比对。",
    "output": "integration.continuation_id / continuation_state / lead_integration_revision",
    "source": "/snapshot/integration/continuation/id、/state、/context/lead_integration（M02 中 integration_continuation）"
  },
  {
    "meaning": "集成 canonical 证据行。continuation 必须匹配，行裁决与 payload 裁决必须一致。",
    "output": "integration.evidence_id / evidence_continuation_id / recorded_verdict / payload_verdict",
    "source": "/snapshot/integration/evidence/id、/continuation_id、/verdict、/payload/verdict（M02 中的 proof 行；VerificationResult.as_dict）"
  },
  {
    "meaning": "控制器的当前性判断，按记录原样，不重新计算。其真实返回类型必须用生产 fixture 钉住，非 exact bool 一律不作正向解读。",
    "output": "integration.current",
    "source": "/snapshot/integration/current（M02 中的 self._current_payload(integrated)）"
  },
  {
    "meaning": "真正的集成 payload，按任务证据同一白名单投影；没有 task_hash。不用 builds 或任务证据代替它。",
    "output": "integration.result.*",
    "source": "/snapshot/integration/evidence/payload/evidence/{candidate_hash,patch,checks,review,dependencies,acceptance_hash,check_hashes,status,integrity_error,scope_error,run_key}（M06 中的 integration 分支）"
  },
  {
    "meaning": "集成候选的创建记录。COMPLETED 只表示候选已创建，不表示通过验收、已安装或已部署。",
    "output": "integration.builds[]",
    "source": "/snapshot/integration/builds/{b}/{key,created_at,data/status,data/run_key,data/candidate_hash,data/patch,data/dependencies}（M02 中 journal.records('integrations')）"
  },
  {
    "meaning": "历史调用的事实。RECEIPTED 是 transport 终态，receipt COMPLETED 是原生返回，二者都不是 verifier PASS。receipt 里的候选标为 UNVERIFIED。receipt.output、usage、session、request、prompt、cwd、role_metadata 都不遍历。",
    "output": "attempts[]",
    "source": "/snapshot/runs/{r}/{key,status,task_id,evidence_id,receipt/status,receipt/candidate_hash,receipt/patch}（M02 中 journal.runs()；M04 中 receipt 字段）"
  },
  {
    "meaning": "标明非原子捕获、未重新验证、不是 DLP，以及没有文件正文、研究结果或设备验收。",
    "output": "limitations / provenance 常量",
    "source": "无输入；固定常量"
  }
]
```

MS04：RECORDED 的 Fact 用 RFC6901 解析回原捕获值，类型与值精确相等；FILTERED 的 pointer 仍指向原值，值有意变化；WITHHELD/REDACTED/MALFORMED value=null，unsafe key 改为安全父 pointer +排序后 row_ordinal。所有 hash 分项展示，不重算、不合并、不互相替代。

## 5. 原 R01–R21，按 Main 的显式修正生效

- R01 拒收与诊断的边界。信封或 snapshot 必需结构不合法时，抛 EngineeringResultInputError，码为 INPUT_TYPE、ENVELOPE_KEYS、MISSION_ID_INVALID、SNAPSHOT_REQUIRED_FIELD 或 TEXT_ENCODING。任一基数、深度或访问上限超出，抛 LIMIT_EXCEEDED、DEPTH_EXCEEDED、VISIT_LIMIT 或 INPUT_CYCLE；输出超过上限抛 OUTPUT_LIMIT。这些情况一律不返回部分结果，也不返回看似成功的空投影。节点、证据、检查、审查或 run 内部的字段畸形不导致整体拒收，只记分段诊断，该段没有正向标签，其他有效段照常保留。

- R02 绝不静默截断。结构上限一律整体拒收。只有两类选择性不输出：measurement 的选择策略，以及单个可选展示文本超过字节上限（state=WITHHELD，附精确 utf8_bytes 和 TEXT_LIMIT 诊断）；两者都带精确计数和 complete=false。身份类字符串（id、key、hash、path）超限时记为 MALFORMED。

- R03 缺失与畸形的区别。字段不存在、值为 null，或是挂起状态下的正常空缺（verification=null、review 在检查失败后不存在、旧版没有 acceptance 或 write_paths、ERROR build 字段稀疏），都记为 NOT_RECORDED，没有错误码。字段存在但类型、枚举、hash 格式或一致性不对，记为 MALFORMED 或对应诊断码，该段不能有正向标签。

- R04 精确类型。bool 必须 type(x) is bool，0、1、'true' 都不算。int 必须 type(x) is int，不能是 bool，计数字段取 0..2**63-1，exit_code 取 -2**63..2**63-1。float 必须有限，NaN 或 Inf 记 NUMERIC_NONFINITE 并不输出该值。字符串必须能严格 UTF-8 编码，孤立代理项属于 MALFORMED。

- R05 循环与共享。只在白名单分支内迭代下降，用祖先 id() 栈检测循环：必需位置出现循环抛 INPUT_CYCLE，深度上限另行兜底。非祖先的共享引用允许。不遍历白名单外的分支，所以那里的循环、自定义对象或超大内容不影响结果。

- R06 重复与依赖图。nodes 中 id 重复，所有同 id 节点记 DUPLICATE_ID，stage 为 EVIDENCE_CONFLICT，mission 结论为 CAPTURE_CONFLICT。runs 中 key 重复，记 DUPLICATE_ID，这些 run 不参与关联。同一组 checks 中 id 或 check 名重复，记 DUPLICATE_ID。review.evidence 有重复，记 REVIEW_REFERENCE_MISMATCH。depends_on 指向未知 id 或形成环（用有界迭代检测），涉及的节点记 DEPENDENCY_GRAPH_INVALID，不能有正向标签。

- R07 捕获时的脱敏标记。上游 redact 会把 key 匹配 (?i)api.?key|authorization|password|secret|token$ 的 dict 值替换为 '[REDACTED]'。因此 patch 路径、dependencies 的 task id、check_hashes 的 check 名、measurement 的 key 都可能被整体替换。当 key 匹配同一常量正则且值恰为 '[REDACTED]' 时，记 REDACTED_AT_CAPTURE，不算畸形。本函数自带这条正则常量，不导入 protocol，也不读 ENV。被替换的值是 hash 位时，不能参与正向一致性判断，所以该段不能有正向标签，但这不算冲突。

- R08 额外的确定性文本过滤，属于纵深防御，不是 DLP。对所有输出 Text，先检查长度，再按顺序应用固定正则：\bsk-[A-Za-z0-9_-]{12,} 替换为 [REDACTED]；(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+ 替换为 Bearer [REDACTED]；\bAKIA[0-9A-Z]{16}\b；\bgh[pousr]_[A-Za-z0-9]{36,}；\bxox[abprs]-[A-Za-z0-9-]{10,}；(?i)\b(api[_-]?key|password|passwd|secret|token)(\s*[:=]\s*)\S+ 替换为 \1\2[REDACTED]。只要出现 -----BEGIN [A-Z ]*PRIVATE KEY，整段文本记为 REDACTED_AT_CAPTURE 且 value=null。C0 控制字符（\n、\t 除外）、DEL 到 U+009F、以及 U+200E、U+200F、U+202A..U+202E、U+2066..U+2069、U+FEFF 替换为 U+FFFD。有改动则 state=FILTERED。所有正则不含嵌套量词。这不能证明敏感的用户散文已被清除。

- R09 路径只做词法准入，不触碰文件系统。合格 path 是相对 POSIX 路径，UTF-8 不超过 1024 字节、不超过 64 段，满足：不以 / 开头，不含 \ 或 NUL，没有控制字符或 bidi 字符，没有空段、. 或 .. 段，第一段不含 ':'（排除盘符和 URI scheme），没有 %2e、%2f 一类编码。不合格的行记 change_kind=WITHHELD、path=null 加 UNSAFE_PATH 诊断，pointer 只写到 patch 并附 row_ordinal。如果某一段（不区分大小写）匹配 ^\.env(\..*)?$、^\.ssh$、^\.aws$、^\.netrc$、^\.npmrc$、^\.pypirc$、^id_[a-z0-9]+$、\.(pem|key|p12)$，或包含 holdout，路径不展示，但该行的增量种类和 hash 保留，并记 WITHHELD_SENSITIVE_PATH。不做 resolve 或大小写归一化；路径不是链接，也不赋予打开能力。

- R10 patch 行。值必须是 exact dict 且键恰为 {before,after}，每个值是 64 位十六进制或 null。before 为 null、after 有值，记 ADDED；反之记 REMOVED；两者都有值且不同，记 MODIFIED。两者相等或都为 null，记 MALFORMED_DELTA，因为生产者只保留不同的条目。条件满足时按 R07 处理。空 patch dict 合法，句子固定为「未记录文件增量」，不能理解为目标已完成。

- R11 任务 stage 判定，取第一个命中的规则。(1) 存在冲突类诊断：DUPLICATE_ID、VERDICT_MISMATCH、CANDIDATE_HASH_MISMATCH、CHECK_HASH_MISMATCH、CHECK_NAME_MISMATCH、REVIEW_RUN_KEY_MISMATCH、REVIEW_REFERENCE_MISMATCH、DEPENDENCY_EVIDENCE_MISMATCH、DEPENDENCY_GRAPH_INVALID、MALFORMED_DELTA，或 verification 非 null 而 recorded_verdict 为 UNVERIFIED，判 EVIDENCE_CONFLICT。(2) active=false 或 superseded_by 非 null：有 verification 时判 HISTORICAL_RESULT，label 为 SUPERSEDED 或 INACTIVE；否则判 PENDING，label 同前。(3) stale=true，判 HISTORICAL_RESULT，label=STALE。(4) verification=null：state 为 RUNNING 或 VERIFYING，或有精确 task_id 关联且 status=IN_FLIGHT 的 run，判 IN_PROGRESS；有精确关联的 run，其 receipt 带合格 candidate_hash 且 receipt_status 不是 UNKNOWN，判 CANDIDATE_RECORDED；其余判 PENDING。(5) recorded_verdict 与 payload_verdict 都是 PASS，state=SUCCEEDED，review 已记录且 verdict=PASS，所有检查 status=PASS，hash 与引用一致，没有 MALFORMED 字段，判 TASK_VERIFIED_AS_CAPTURED，label=CURRENT_AS_CAPTURED。(6) 两个 verdict 都是 PASS 但 state 不是 SUCCEEDED，判 HISTORICAL_RESULT，label=STATE_NOT_SUCCEEDED。两个 verdict 都是 PASS 但 review 缺失，或有字段为 REDACTED_AT_CAPTURE、WITHHELD，判 HISTORICAL_RESULT，label=UNDETERMINED，不升级。(7) 其余裁决（FAIL、ERROR、INVALID、INCONCLUSIVE 或未识别 token），判 NOT_ACCEPTED，保留原 token，不合并成「实现失败」。

- R12 检查与审查的一致性，只比对已记录事实，不重新验证。每个 check.candidate_hash 必须等于所属的 candidate_hash。set(check_hashes) 必须等于 {checks[].check}，且对应的 check_hash 相等。任务证据必须恰有一个 check，且其 check 等于 node.check。review.candidate_hash 必须等于所属 candidate_hash。review.run_key 必须等于 'review:'+evidence.run_key（M06 中 key 的构造方式）。review.evidence 必须是记录中 check id 的子集；verdict=PASS 时两者集合必须相等。verdict=INVALID 时 evidence 可以为空。

- R13 依赖。evidence.dependencies 的 key 必须属于 node.depends_on，值的类型和数值都必须精确相等（str 与 int 不互转）。若上游节点被捕获的 evidence_id 等于该值，且上游 stage 为 TASK_VERIFIED_AS_CAPTURED，则 matches_captured_upstream=true；不相等或上游不当前则为 false。当前任务出现 false，记 DEPENDENCY_EVIDENCE_MISMATCH（非原子捕获的竞态或漂移），不给正向标签。

- R14 集成 stage 判定，取第一个命中的规则。(1) continuation、evidence 都为 null 且 builds 为空，判 PENDING。(2) 存在冲突：evidence.continuation_id≠continuation.id 记 INTEGRATION_CONTINUATION_MISMATCH；行裁决≠payload 裁决记 VERDICT_MISMATCH；或出现 R12、R13 类冲突。此时若 current 为 True 判 EVIDENCE_CONFLICT，否则判 NOT_ACCEPTED 或 HISTORICAL_RESULT 并附诊断。(3) 只有 evidence 为 null：有 COMPLETED 且候选合格的 build，判 INTEGRATION_CANDIDATE_RECORDED，否则判 PENDING。(4) current 恰为 True，continuation 为 SUCCEEDED，两个裁决都是 PASS，checks 全部 PASS 且一致，review 为 PASS 且覆盖全部检查，lead_integration 等于 revision（缺失时只有在其余条件都满足时才允许，并附 limitations），每个 dependency 都匹配到 TASK_VERIFIED_AS_CAPTURED 的节点 evidence_id，判 INTEGRATION_VERIFIED_AS_CAPTURED。(5) current 为 True 但 (4) 不成立，判 EVIDENCE_CONFLICT。(6) current 为 False 或 null 而裁决为 PASS，判 HISTORICAL_RESULT。(7) 其余裁决判 NOT_ACCEPTED。current 不是 exact bool 也不是 null 时，记 CURRENT_FLAG_SHAPE，不作正向解读。builds 一律标 CANDIDATE_ONLY_NOT_ACCEPTANCE，不按时间顺序推断为当前。

- R15 mission 结论，取第一个命中的规则。(1) CAPTURE_CONFLICT：project_verified=True 但集成 stage 不是 INTEGRATION_VERIFIED_AS_CAPTURED；all_verified=True 但 project_verified 不是 True；phase=COMPLETED 但 project_verified 不是 True；存在节点 DUPLICATE_ID；当前证据中记录的 acceptance_hash 互不相同（记 ACCEPTANCE_HASH_DIVERGENT）；project_verified 或 all_verified 出现非 bool 值。(2) PROJECT_VERIFIED_AS_CAPTURED：project_verified=True 且集成 stage 为 INTEGRATION_VERIFIED_AS_CAPTURED。(3) INTEGRATION_EVIDENCE_RECORDED_PROJECT_NOT_VERIFIED：集成 stage 为 INTEGRATION_VERIFIED_AS_CAPTURED，而 project_verified 不是 True（包括缺失）。(4) TASK_EVIDENCE_RECORDED_INTEGRATION_PENDING：有任一 TASK_VERIFIED_AS_CAPTURED。(5) CANDIDATES_RECORDED：有任一候选或证据（CANDIDATE_RECORDED、NOT_ACCEPTED、HISTORICAL_RESULT），或有 INTEGRATION_CANDIDATE_RECORDED。(6) 其余为 NO_ENGINEERING_RESULT_RECORDED。all_verified=false 与 unresolved 非空作为 K01 控制上下文另行列出，不能把结论提升，也不会抹掉已有的历史事实。

- R16 UNKNOWN 与 IN_FLIGHT 的叠加。精确关联的 unresolved key 只附在 uncertain_run_keys 上，任务 stage 保持原判定，不新增 stage，也不推断解决。关联不上的留在 mission 级。不重发、不新建 job、不 resolve。RESOLVED_UNKNOWN 只作为记录的 token 展示，不授权任何新动作。

- R17 attempts 关联只用精确等值。run.task_id 等于某节点 id 且不是 'planner'，判 TASK_ATTEMPT。run.key 等于某节点 review.run_key，判 TASK_REVIEW。run.key 等于集成 review.run_key，判 INTEGRATION_REVIEW。其余判 MISSION_LEVEL。不按最新一条推断，不把缺省 role 当作 worker 的权威，不遍历 role_metadata。receipt 中的候选永远是 unverified_candidate；同一 evidence_id 的 run 若 verdict 与节点 verdict 不同，记 VERDICT_MISMATCH。

- R18 文本与证据来源。receipt.output、plans、diagnoses、format_errors、controller_errors、procedure、rsi、usage、session、request、prompt、cwd、controls、controller、counters、budgets、materialization.driver_report、candidate 绝对路径，都不作为答案、证据或输出。review.reasons 与 classification.summary 只是归属引用，不授予 scope 或真相。

- R19 provenance 与 hash。每个 Fact 都带精确 pointer。acceptance_hash、check_hash、candidate_hash、task_hash、dependencies 的 evidence id、before/after hash 各自独立输出，不合并、不互相替代。所有 hash 都是记录中的证据，不是重新校验过的字节。S0 不计算 projection hash；即使将来计算，也不是验收或当前性证明。pinned 永远为 false，cursor、head、captured_at 永远为 null。

- R20 纯度。函数只读入参数，不写全局状态，不缓存，不记日志，不发事件。模块导入期间也没有副作用。不调用 protocol.redact、digest 或 bounded（避免导入 protocol）。W3 保持 UNSELECTED：本阶段不打开任何 DB，测试不得用 mode=ro 或文件字节、mtime 作为 oracle，也不重跑 WAL6。

- R21 supplemental（Feynman）映射的取舍。采纳 F01 到 F18 的字段白名单、hash 增量语义和 review、run 精确关联。不采纳的部分：project_engineering(captured_snapshot, mission_id, cursor) 这个签名（身份改取 /id，没有 cursor 参数）；AVAILABLE、PARTIAL 这种部分成功的顶层状态（改为结构拒收加分段诊断）；隐藏路径段一律拒收（.github 是真实交付物，只拒收凭据类段）；基于规则组的 measurement 选择器（其 classification 内部结构不在本次内联的逐字源码中，不能断言），改为有界的通用数值标量选择。


### 优先修正（MS01–MS15，原 R14 缺失 revision 例外已撤销）

- **MS01**：Positive AS_CAPTURED labels are optional display projections, never acceptance. Require all their listed prerequisite fields RECORDED, exact, nonempty checks, and complete consistent hashes/dependencies/review; absence/redaction/malformed/withheld suppresses the positive label. Missing record is NOT_RECORDED, not automatic PASS. Do not call verifier or recompute recorded classification. Missing dependencies cannot count as satisfied; for a task, complete dependency key set must match depends_on.

- **MS02**：Real producer _current_payload returns exact bool on every actual branch. Hub creates mission or m_+32hex, both satisfy proposed id lexical bound. Real VerificationResult.as_dict has EIGHT output keys (verdict,verifier_id,summary,metrics,evidence,assurance,verification_mode,lessons); do not invent a ninth field. Pin real captured integration.current using fixed public harness, not just a handwritten bool.

- **MS03**：FC01 reuses actual test_lead_mission.make_spec/mission/Stub outside the pure-call trap in NEW retained fixture only; create a single Hub with actual LeadMission and explicit fixture drivers before its run, perform public snapshot capture outside pure call, json roundtrip, then invoke projection under traps. No native, provider, evaluation data or actual mission. Current Hub constructor/single=true and explicit allow-local execution are fixture-only and not operator Start/device acceptance.

- **MS04**：FC23: RFC6901 resolves the original recorded source. For RECORDED values, assert exact source equality; FILTERED values carry original source locator but intentionally differ from raw input. WITHHELD/REDACTED/MALFORMED have null projected value and parent locator+row_ordinal when unsafe keys. Do not fabricate a source equality after filtering.

- **MS05**：R14: missing lead_integration revision is NOT_RECORDED and cannot yield INTEGRATION_VERIFIED_AS_CAPTURED. No missing-generation exception. Positive integration needs exact recorded continuation/evidence identities and recorded current=true. Keep controller flags separately, do not treat a projection-derived label as an execution permission.

- **MS06**：All selected cycles reject INPUT_CYCLE and all selected traversal work is bounded. Unselected controller/controls/snapshot extra values are not iterated or copied, and their cycles/custom objects are ignored. Sparse error evidence/run/build still produces diagnostic facts rather than false success. Source paths and pointers themselves must not leak excluded secret/unsafe-key text.

- **MS07**：Native prose, credential data, unused role/control/private fields, object repr and input exception text never escape. Additional deterministic filtering remains defense-in-depth, not DLP. No protocol.redact/environment/file/time imports or reads inside module. Selected caller-provided inputs are not source capabilities.

- **MS08**：Statements must include actual objective, substantive added/modified/removed path+recorded hash facts, actual check name/classification/summary and finite numeric measurement facts, review reasons/references, and integration facts. Use fixed Chinese templates; no count-only or preregistration-only substitute. Renderable structured plain data only; no HTML, open-links or fabricated profit/capability improvement.

- **MS09**：Expose the exact public function and content-free EngineeringResultInputError per proposal. Frozen error codes are INPUT_TYPE,ENVELOPE_KEYS,MISSION_ID_INVALID,SNAPSHOT_REQUIRED_FIELD,TEXT_ENCODING,LIMIT_EXCEEDED,DEPTH_EXCEEDED,VISIT_LIMIT,INPUT_CYCLE,OUTPUT_LIMIT. Author must define exact fixed diagnostic set/template IDs in NEW contract before outcome; report any genuine ambiguity to Main before freeze, never revise after outcomes.

- **MS10**：RED records missing public feature explicitly, not a broken import/setup oracle: lazy public import at test call and precise assertion for the absent NEW module/function, no fake replacement module/output. At least one explicit public-availability/actual captured-envelope behavior assertion must fail for that missing feature. Disclose which subsequent behavior branches were unreachable at absence; no claim those semantic branches have individual RED proofs. Freeze all planned tests BEFORE any production implementation.

- **MS11**：Before any selected dictionary lookup/comparison/sort, check exact dict type, bounded key cardinality, and exact builtin str keys; do not execute user-defined key __hash__/__eq__/repr/iter. Envelope4 keys; snapshot128 keys; task64 keys; verification32 keys; evidence128 keys; integration8 keys; continuation64 keys; continuation.context64 keys; run64 keys; run.receipt128 keys; build.record16 keys; build.data128 keys; check16 keys; classification16 keys; review16 keys; patch item2 keys; measurement existing visit4096/key pattern rules. Other existing collection caps remain as native proposal. Unknown values in snapshot/controller/controls/unlisted evidence fields are not read/traversed/copied. Unsupported key types are content-free mandatory input rejection or segment diagnostic as appropriate, never interpolated.

- **MS12**：All output strings including IDs, path labels and JSON Pointers must satisfy deterministic credential-pattern/unsafe-key suppression. For identity/key/path strings, do not rename them via filtering and thereby claim a new source identity: WITHHELD and null value with parent pointer+row_ordinal if applicable. Any key containing R08 credential patterns (including sk-/Bearer/private-key-like text) must not appear in a pointer, diagnostic or statement. Raw safe exact IDs can be compared internally within bounds, but withheld identities cannot support positive display labels. Add adversarial key __eq__/__hash__ sentinels and credential-shaped path/opaque-key tests before freeze.

- **MS13**：Known contradictory native status or integrity/scope failures suppress positive task/integration labels. If recorded row+payload claim PASS but evidence.status is present and not COMPLETED, or nonempty integrity_error/scope_error is supplied, retain recorded facts and add VERDICT_MISMATCH (closed existing code); no TASK_VERIFIED_AS_CAPTURED/INTEGRATION_VERIFIED_AS_CAPTURED. Missing optional error text is normal and not by itself malformed. No native output, model identity or fresh check may be inferred. All controller flags remain separately recorded.

- **MS14**：Deterministic visit/depth units: envelope root depth0; each selected dict/list child edge adds1; selected scalar depth does not consume container-depth allowance. Every entered selected input value, including root/container/scalar, counts one value visit at its source position. Keys are shape-checked under key caps but are not value visits. Reusing one object at distinct nonancestor source positions counts once per distinct position; repeated use of an already processed position for comparisons/statements does not recount. Unselected field values do not count; denied measurement-key subtree counts its selected root once, is withheld once, not traversed. Output containers/constants do not count. selected total >262144 =>VISIT_LIMIT; per-check measurement visits include measurement root, >4096 =>LIMIT_EXCEEDED. First check selected ancestor cycle, then container global depth16, then measurement container depth4 (measurement root is0); exceeding either selected container-depth bound =>DEPTH_EXCEEDED, not pruning/partial success. Then count visit and enforce budgets before scanning/copying children; scalar/string validators apply afterward. Unknown/unselected values are not descended. Add depth4 allowed/depth5 reject, measurement4095 scalar+root allowed/4096 scalar+root reject, and a duplicate-use repeat deterministic visit case before formal freeze.

- **MS15**：Do not claim whole error-free producer fixture based on AST alone. The public capture helper in draft is approved for NEW retained fixture-only outcomes (make_spec/mission/Stub and actual Hub create/control/snapshot); Stub.probe is known stub metadata only, zero real provider/native probe or task acceptance. Scope Source model jobs remain excluded. Check projection feature absence via public call after capture; mark subsequent semantic assertions unreachable on absent feature. Existing dependency stdout/stderr/receipts and original source full tree readback must be retained.


明确解释：
- Positive AS_CAPTURED 仅是显示标签，必须具备 exact / RECORDED / 非空检查 / 完整依赖集 / 一致 hash 与 review。缺失、畸形、WITHHELD 或 capture redaction 抑制标签，缺失不是自动通过。
- task dependencies key set 必须完整等于 depends_on；精确比较 evidence id 类型与值。
- 集成 missing lead_integration 为 NOT_RECORDED，永不允许原 R14 的例外升级。
- FC05 UNKNOWN receipt 候选仍可列为 unverified_candidate；按 R11 不升级 task，READY 下仍 PENDING。IN_FLIGHT 仅作为 workflow/uncertain 事实，不推断 resolve、不重发。
- MS12 适用于所有输出字符串：Text 可以 FILTERED；path / ID / map key 身份不改名，命中 credential pattern 时 WITHHELD/null，必要时用父 pointer+row_ordinal。原安全精确 ID 可在内存内比对，WITHHELD 身份不参与正向显示结论，不构造带 secret 的 pointer/statement/diagnostic。
- MS13 将已知 native 失败与已有 PASS 的冲突归入现有 VERDICT_MISMATCH。任务与集成保留原 PASS、检查和审查事实，但正向标签受抑制；不重 classify、不重验、不篡改 controller 的 project_verified/all_verified。正常缺失、null 或空的可选 error 文本不表示已知失败。

## 6. 拒收码、分段诊断码、模板与固定限制说明

拒收码（封闭，唯一十码）：

```json
[
  "INPUT_TYPE",
  "ENVELOPE_KEYS",
  "MISSION_ID_INVALID",
  "SNAPSHOT_REQUIRED_FIELD",
  "TEXT_ENCODING",
  "LIMIT_EXCEEDED",
  "DEPTH_EXCEEDED",
  "VISIT_LIMIT",
  "INPUT_CYCLE",
  "OUTPUT_LIMIT"
]
```

错误精确为 `EngineeringResultInputError`，仅额外实例属性 `code`；`str(exc) == "engineering result input rejected: " + code`，`raise ... from None`。信封类型/不支持 key 类型为 INPUT_TYPE；信封键集合差异 ENVELOPE_KEYS；id 词法/编码非法 MISSION_ID_INVALID；snapshot 必需结构/类型错误及必需 selected dictionary 的 unsupported key 为 SNAPSHOT_REQUIRED_FIELD；必需文本编码错误 TEXT_ENCODING。结构上限、深度、总访问、循环和输出分别用固定相应码。内部非必需 segment 的 unsupported exact key/type 为 MALFORMED 诊断，绝不调用对象转换。

作者冻结前定义的精确诊断码集合（新增名称只限 revision mismatch 与 MS12 withholding）：

```json
[
  "MALFORMED",
  "TEXT_LIMIT",
  "HASH_INVALID",
  "UNRECOGNIZED_ENUM",
  "NUMERIC_NONFINITE",
  "UNSAFE_PATH",
  "WITHHELD_SENSITIVE_PATH",
  "MALFORMED_DELTA",
  "DUPLICATE_ID",
  "VERDICT_MISMATCH",
  "CANDIDATE_HASH_MISMATCH",
  "CHECK_HASH_MISMATCH",
  "CHECK_NAME_MISMATCH",
  "REVIEW_RUN_KEY_MISMATCH",
  "REVIEW_REFERENCE_MISMATCH",
  "DEPENDENCY_EVIDENCE_MISMATCH",
  "DEPENDENCY_GRAPH_INVALID",
  "INTEGRATION_CONTINUATION_MISMATCH",
  "INTEGRATION_REVISION_MISMATCH",
  "CURRENT_FLAG_SHAPE",
  "ACCEPTANCE_HASH_DIVERGENT",
  "WITHHELD_SENSITIVE_ID"
]
```

MALFORMED 覆盖内部分段的 exact type/shape/range/encoding 问题；TEXT_LIMIT 是可选文本有计数 withholding；HASH_INVALID 不等于 hash mismatch。INTEGRATION_REVISION_MISMATCH 仅表示已记录 revision 与捕获 revision 冲突；missing 不发这个诊断。WITHHELD_SENSITIVE_ID 仅表示 ID/key 的确定性模式 withholding，WITHHELD_SENSITIVE_PATH 保留合法 delta 的种类/hash，但不显示路径。没有任意追加码或诊断正文。

VERDICT_MISMATCH 同时覆盖行/payload 裁决不一致，以及 MS13 的「行与 payload 均记录 PASS，但已记录 native status 非 COMPLETED 或存在非空 integrity_error/scope_error」。诊断集合仍是原 draft 的 22 码，模板仍是 20 个；此修订不新增码、不改 schema。

Diagnostic.section 封闭集合：

```json
[
  "mission",
  "task",
  "check",
  "measurement",
  "review",
  "integration",
  "build",
  "attempt"
]
```

中文模板 ID 及模板全文（`D01` 的空 patch 特例全文精确为 `未记录文件增量`）：

```json
{
  "Q01": "目标问题：{objective}。",
  "C01": "尚无已记录的工程结果。",
  "C02": "已记录候选或历史证据；不表示已通过验收。",
  "C03": "已记录任务证据；项目集成证据仍待记录。",
  "C04": "已记录集成证据；控制器未记录项目通过。",
  "C05": "捕获时控制器记录项目通过；本投影不是验收。",
  "C06": "捕获记录存在冲突；保留分项事实，不给出通过结论。",
  "D01": "{subject}文件增量：{path}，{change_kind}；before={before}，after={after}；hash 为前12位。",
  "M01": "{subject}检查 {check}：记录分类 {status}；评估器说明：{summary}。",
  "M02": "{subject}检查 {check} 的记录测量：{name}={value}。",
  "R01": "{subject}独立审查：记录裁决 {verdict}；归属理由：{reason}。",
  "R02": "{subject}审查记录引用：{reference}。",
  "I01": "尚无已记录的项目集成证据。",
  "I02": "已记录集成候选；不表示通过项目验收。",
  "I03": "集成记录未被接受；continuation={continuation_id}，行裁决={recorded_verdict}，payload裁决={payload_verdict}。",
  "I04": "捕获时记录集成通过且 current=true；continuation={continuation_id}，evidence={evidence_id}，revision={revision}。",
  "I05": "保留历史集成证据；current={current}，行裁决={recorded_verdict}。",
  "I06": "集成捕获记录存在冲突；continuation={continuation_id}，evidence={evidence_id}。",
  "K01": "控制器记录：phase={phase}，paused={paused}，stopped={stopped}，project_verified={project_verified}，all_verified={all_verified}，待核对调用={unresolved_count}；这不是实时进程终止证明。",
  "L01": "限制：非原子捕获，不重新验证字节，不是脱敏完备性证明；没有文件正文、研究结果或设备及第二主机验收。"
}
```

结论与集成模板映射：

```json
{
  "conclusion": {
    "NO_ENGINEERING_RESULT_RECORDED": "C01",
    "CANDIDATES_RECORDED": "C02",
    "TASK_EVIDENCE_RECORDED_INTEGRATION_PENDING": "C03",
    "INTEGRATION_EVIDENCE_RECORDED_PROJECT_NOT_VERIFIED": "C04",
    "PROJECT_VERIFIED_AS_CAPTURED": "C05",
    "CAPTURE_CONFLICT": "C06"
  },
  "integration": {
    "PENDING": "I01",
    "INTEGRATION_CANDIDATE_RECORDED": "I02",
    "NOT_ACCEPTED": "I03",
    "INTEGRATION_VERIFIED_AS_CAPTURED": "I04",
    "HISTORICAL_RESULT": "I05",
    "EVIDENCE_CONFLICT": "I06"
  }
}
```

模板插值只来自已投影的安全事实；RECORDED/FILTERED 插入其安全 value，缺失/withheld/null 用固定 `未记录` / `已隐藏`，绝不 repr 对象。subject 是固定 `任务 {task_id}` 或 `集成`；change_kind 用固定中文 `新增` / `修改` / `删除` / `已隐藏` / `畸形记录`；hash 在句子中只用记录的前12位，结构 Fact 保留完整64位；null hash 用 `未记录`。bool 为 `true`/`false`，有限数字使用 JSON 原值，不舍入、不换算收益。D01 每行、M01 每检查、M02 每实测标量、R01 每理由、R02 每引用；sources 只用对应原 source pointer，去重且码点排序。顺序为 Q01、C0x、任务与集成的 D/M/R 分组、I0x、K01、L01；不以数量或 preregistration 取代实际目标、路径/hash、分类/summary、测量、理由/引用与集成事实。

固定 limitation 列表顺序与文本：

```json
[
  {
    "code": "NO_FILE_CONTENT",
    "text": "仅展示记录的文件hash增量，不包含文件正文。"
  },
  {
    "code": "NON_ATOMIC_CAPTURE",
    "text": "输入由调用方非原子捕获，不是同一事务的全局事实。"
  },
  {
    "code": "NO_REVERIFICATION",
    "text": "本投影未重新运行检查、审查或重新验证文件字节。"
  },
  {
    "code": "SPEC_NOT_IN_SNAPSHOT",
    "text": "输入不含完整冻结spec，所列指纹仅按记录展示。"
  },
  {
    "code": "NOT_DLP",
    "text": "确定性模式过滤是纵深防御，不是敏感内容清除证明。"
  },
  {
    "code": "NO_LIVE_RUNTIME",
    "text": "不展示实时进程、节点在线性或原生终止事实。"
  },
  {
    "code": "NO_RESEARCH_RESULT",
    "text": "本投影没有研究结果或研究发布状态。"
  },
  {
    "code": "NO_DEVICE_OR_SECOND_HOST_ACCEPTANCE",
    "text": "本投影没有手机、设备或第二主机验收。"
  },
  {
    "code": "MEASUREMENT_SELECTION_PARTIAL_BY_POLICY",
    "text": "仅展示有界有限数值或bool测量；不输出项与省略项分别计数。"
  }
]
```

## 7. 保持原上限，不抬限、不静默截断

```json
{
  "check_hashes_per_artifact": 64,
  "checks_per_artifact": 64,
  "dependencies_per_artifact": 64,
  "depends_on_per_task": 64,
  "diagnostics_total_reject_above": 8192,
  "envelope_keys_exact": 4,
  "float": "只接受有限值，不舍入；NaN 和 Inf 记 NUMERIC_NONFINITE 并不输出",
  "hash_hex_chars_exact": 64,
  "int_range": "计数字段 0..2**63-1；exit_code 与 measurement 中的 int 取 -2**63..2**63-1，超出记 MALFORMED",
  "integration_builds": 256,
  "measurement_depth_below_measurement_root": 4,
  "measurement_key_pattern": "^[A-Za-z_][A-Za-z0-9_.-]{0,63}$；不符合或命中敏感 key 正则 (?i)(api.?key|authorization|password|secret|token|credential|cookie|session|private|bearer|holdout) 的子树只计 withheld 1 次，不展开",
  "measurement_scalars_emitted_per_check": 64,
  "measurement_visits_per_check_reject_above": 4096,
  "mission_id_utf8_bytes": 128,
  "nodes": 256,
  "objective_and_acceptance_code_points": 20000,
  "objective_and_acceptance_utf8_bytes": 80000,
  "opaque_id_or_key_utf8_bytes": 256,
  "other_text_utf8_bytes": 16384,
  "output_canonical_json_utf8_bytes": 8388608,
  "patch_rows_per_artifact": 512,
  "path_segments": 64,
  "path_utf8_bytes": 1024,
  "policy": "表中所有上限都在复制或扫描之前检查（len() 先于迭代和正则）。超过结构上限整体拒收；measurement 选择与可选文本超限按 R02 显式不输出，并给出精确计数。这些数值是本提案的取值，不是现有验收，要在 Main 选定后测试冻结前确认。",
  "review_evidence_refs": 64,
  "review_reasons": 64,
  "runs": 2048,
  "runtime_bound": "总工作量与 selected_value_visits_total 加上被选字符串总字节成线性关系；正则没有回溯爆炸。",
  "selected_container_depth_from_envelope": 16,
  "selected_value_visits_total": 262144,
  "statement_sources_each": 64,
  "statements_total": 4096,
  "token_chars": 32,
  "traversal_order": "信封，question，nodes（按原顺序；checks 按原顺序；patch 与 measurement 按 key 码点排序），integration（continuation、evidence、payload、builds 按原顺序），runs（按原顺序），unresolved，control，mission 结论。没有 set 迭代顺序泄漏。",
  "unresolved": 2048,
  "write_paths_per_task": 64
}
```

输出字节 oracle 为 `json.dumps(result,sort_keys=False,ensure_ascii=False,allow_nan=False).encode("utf-8")`；完整输出超过 8388608 字节 OUTPUT_LIMIT，无部分成功。measurement omitted / withheld 和 Text.utf8_bytes 分别精确展示，不把已隐藏的未知字符串当作数值 0。所有选择前先 len / exact type / key 边界，之后才做有限扫描/正则。

## 8. NEW 测试场景（原测试未改）

- FC01 真实生产者 fixture（必需）：在测试里用现有 lead mission 测试使用的确定性 fake-driver harness，在 tmp_path 中走完一次任务加集成。实现者必须引用确切的现有 helper；若现有 harness 无法产出带 review 的已验证集成，就把这一点作为缺口记录，不允许伪造。然后在 projection 之外调用 MissionHub.snapshot 捕获结果，经 json.dumps/json.loads 往返，再在 FC20 的陷阱上下文中调用投影。断言：conclusion.stage=PROJECT_VERIFIED_AS_CAPTURED；patch、checks、review、acceptance_hash 在 integration.result 中与 snapshot 原值逐字相等；integration.current 的真实类型在此被钉住。

- FC02 手写字面 fixture，键严格按 M02、M04、M06、M07、G02 的形状，覆盖 nodes={**task, state, attempts, active, superseded_by, verdict, evidence_id, verification, stale}、verification={verdict, verifier_id, summary, metrics, evidence, assurance, verification_mode, lessons}、evidence 中含 receipt 字段及 output。断言 'output'、usage、session_id、requested_model 的值不以任何形式出现在 json.dumps(result) 中。

- FC03 空任务：nodes=[]、runs=[]、integration 三个 null 和 builds=[]，判 NO_ENGINEERING_RESULT_RECORDED；Q01 是第一句；输出不含任何 PASS 计数字段。

- FC04 PENDING 与 IN_PROGRESS：verification=null 时，state=READY 判 PENDING；state=RUNNING 或存在精确的 IN_FLIGHT run 时判 IN_PROGRESS。没有虚构的候选、检查或 0 值测量；诊断为空。

- FC05 receipt 有候选但没有 evidence，判 CANDIDATE_RECORDED，attempts 中为 unverified_candidate。若 receipt_status=UNKNOWN，不升级，且出现在 uncertain_run_keys。

- FC06 检查 FAIL、ERROR、INVALID、INCONCLUSIVE 各一组，都判 NOT_ACCEPTED；status token 和 summary 原样保留；没有 review 时 review.recorded=false 且无诊断。

- FC07 检查 PASS 而 review 为 FAIL 或 INVALID（evidence 为空），判 NOT_ACCEPTED；reasons 被引用；INVALID 的空 evidence 不产生诊断。

- FC08 完整一致的任务，判 TASK_VERIFIED_AS_CAPTURED 和 CURRENT_AS_CAPTURED；同时没有集成时，conclusion 为 TASK_EVIDENCE_RECORDED_INTEGRATION_PENDING。

- FC09 stale=true 判 HISTORICAL_RESULT/STALE；active=false 且 superseded_by='x2' 判 HISTORICAL_RESULT/SUPERSEDED；两个字段分别展示；旧的 PASS 永不标为 current。

- FC10 verdict 为 PASS 但 state=READY，判 HISTORICAL_RESULT/STATE_NOT_SUCCEEDED。

- FC11 一致性冲突，每种各一组，都应判 EVIDENCE_CONFLICT 并给出对应码：check.candidate_hash 不同、check_hashes 不一致、check 名≠node.check、review.run_key≠'review:'+run_key、PASS review 的引用不覆盖全部检查、行裁决≠payload 裁决、verification 非 null 但 verdict 为 UNVERIFIED。

- FC12 patch 行：ADDED、REMOVED、MODIFIED 各一；before==after 和 null/null 判 MALFORMED_DELTA；hash 为大写或长度 63 判 HASH_INVALID；路径为 '/abs'、'a/../b'、'C:x'、'a\\b'、含 U+202E 时，path=null 并附 row_ordinal；'.github/workflows/ci.yml' 允许；'.env' 和 'x/holdout/y' 路径不展示但保留 change_kind。

- FC13 捕获时脱敏：patch key 'cfg/secret.py' 或 dependencies key 'rotate-token' 的值为 '[REDACTED]'，判 REDACTED_AT_CAPTURE，没有冲突诊断，也不升级为 TASK_VERIFIED_AS_CAPTURED。

- FC14 文本过滤：objective 和 reason 中的 sk-、Bearer、AKIA、ghp_、xoxb-、password=、PRIVATE KEY 块、C0 控制字符和 bidi 字符，分别替换为 FILTERED 或 REDACTED_AT_CAPTURE；'<script>' 原样作为字符串保留，不转义成 HTML 实体（转义由渲染层负责）。

- FC15 measurement：嵌套的 {'execution':{'exit_code':1,'timed_out':false,'error':'x'},'score':0.5,'notes':'t','token_count':3,'nan':NaN（in-memory）} 中，emitted 为 execution.exit_code、execution.timed_out、score；withheld 计数精确；execution_error_recorded=true；token_count 在敏感 key 下不输出；NaN 产生诊断；超过 64 个标量时 omitted 计数精确且 complete=false；measurement 访问量为 4097 时拒收 LIMIT_EXCEEDED。

- FC16 集成：只有 build COMPLETED 时判 INTEGRATION_CANDIDATE_RECORDED，build 标签为 CANDIDATE_ONLY；current=False 加 PASS 判 HISTORICAL_RESULT；current=True 但 continuation_id 不匹配，或 lead_integration≠revision，或某个 dependency 不匹配节点 evidence_id，判 EVIDENCE_CONFLICT；current 为 'yes' 或 dict 时记 CURRENT_FLAG_SHAPE；字段稀疏的 ERROR build 不产生诊断。

- FC17 mission 冲突：project_verified=True 而集成为 PENDING，判 CAPTURE_CONFLICT；all_verified=True 而 project_verified=False，判 CAPTURE_CONFLICT；project_verified 和 all_verified 缺失时为 NOT_RECORDED，不可能得到 PROJECT_VERIFIED_AS_CAPTURED；两个任务证据的 acceptance_hash 不同，记 ACCEPTANCE_HASH_DIVERGENT。

- FC18 控制上下文：phase 为 STOPPED、PAUSED、UNKNOWN、TRIAL_FENCED、STALE 时，旧结果保留，K01 句子不出现「已终止」「已完成」字样；unresolved 中关联不上的 key 留在 mission 级。

- FC19 拒收：信封非 dict、dict 子类、多一个或少一个键、id 非法、snapshot 缺 objective、revision 为 True 或 -1 或 1.0、nodes 为 tuple、nodes 有 257 个、单个 patch 有 513 行、自引用 dict 形成循环、objective 有 20001 个码点、输出超限。每种只抛 EngineeringResultInputError，code 固定，str 中不含任何输入片段，__cause__ 为 None。

- FC20 副作用陷阱：monkeypatch 让 os.environ 的 __getitem__、get、__iter__、items 抛异常，同样处理 builtins.open、pathlib.Path.open、sqlite3.connect、socket.socket、subprocess.Popen、threading.Thread.start、time.time、time.monotonic、datetime.datetime.now，以及 sisyfus.workers.protocol.redact（若已被导入）。所有用例照常成功。AST 检查 lead_result.py 的导入只在 {__future__, json, math, re, typing} 中，且没有 global 或 nonlocal 写入。

- FC21 分离与不修改：调用前 copy.deepcopy 输入，调用后输入与副本 deep-equal；遍历输出的所有 dict 和 list，与输入所有容器的 id() 集合不相交；修改输出不影响第二次调用的结果。

- FC22 确定性：同一输入调用两次，以及节点内 dict 键插入顺序不同的等价输入，json.dumps 字节完全相同。

- FC23 provenance：每个 Fact.source 都能用 RFC 6901 在 hub_payload 上解析到同一个值（不可回显的行除外，它们有 row_ordinal）；pinned 为 false，event_cursor、event_head_hash、captured_at 为 null；输出中没有 title、snapshot.mission_id 或 URL scheme 前缀的链接字段。

- FC24 attempts 关联：role 调用的 task_id='planner' 且 key 等于 review.run_key，判 TASK_REVIEW；没有 role 字段的 run 不被当作 worker；重复的 run key 记 DUPLICATE_ID 且不参与关联。

- FC25 依赖图：depends_on 指向未知 id 或形成 a→b→a 环，相关节点记 DEPENDENCY_GRAPH_INVALID，不给正向标签。

- FC26 回归边界：本阶段不修改任何现有测试或契约；W3 不进入断言；不运行 WAL6；no-tools role 的 NOT_READY 用例不改动。


增补 MS01–MS15 cases：完整/缺失依赖与 hash、missing integration revision、真实八键与 bool/Hub ID AST witness、所有 selected cycle 与 nonancestor sharing、unselected poison、内部 sparse ERROR、确定性完整 schema/limitation、纯度 traps、dict malicious hash/equality 两类型、每个 key-cap 超限、credential-shaped path / opaque identities / map keys / pointers；任务/集成的 PASS 与已知 native 失败冲突、正常缺失/空/null error 正对照；measurement 深度4/5、4095/4096 scalar 加 root、denied subtree root 计数、cycle 优先于深度，以及同一对象多源位置计数与重复调用的确定性。

### 后续 fixture-only capture 的确切路径（本轮仅 authored）
- fixture 在 NEW independently rooted retained tmp_path 使用现有 `test_lead_mission.make_spec`、`mission`、`Stub` 原函数；mission(root,spec) 安装真实 Stub 类型，Hub.single=True 与 root/control 相同。
- 实际 `MissionHub.create` → `control("mission","start",allow_local_workers=True)` → public `MissionHub.snapshot`，全部在纯调用 traps 外；没有 fake Hub / fake output / fake feature module。所有 driver 必须在 run 前已是原 Stub；snapshot 经 JSON roundtrip 后在 traps 内投影。
- 实際 captured single ID=mission；m_+32hex 的真实 generator 在当前 MissionHub.create AST 核对，两种合法值的 projector 接受测试不冒充第二个 actual Hub capture。
- 真实 producer 的 integration.current exact bool、八键 serializer、checks/review/patch/acceptance_hash 逐项引用原捕获事实；budget null/unlimited、实际 Stub attestation=None 单列。
- MS15 已选择此 NEW retained fixture-only capture；本轮 outcome 仍 HOLD，尚未执行。原 Stub.probe 仅用于检查已知 fixture metadata，不是实际 provider/native probe，更不是任务或模型验收。
- 后续 capture 在 retained root 的 `s0-producer-evidence` 保留原 captured envelope、所有 task/integration verification（含已有 dependency check 的 stdout/stderr）、原 run receipts，以及 original source 完整文件 hash tree 的 before/after。现有 fixture controller DB、依赖原始文件和 runner stdout/stderr 均由 retained guard 保留，不移除失败材料。
- 捕获上游调用包含 fixture 文件/SQL/评估器 Python 子进程，严格位于纯函数 traps 外；投影本身始终零副作用。capture 不属于 W3 的 readonly / WAL 语义，Source model jobs 仍排除。AST/compile 不代表捕获路径已经无错误。

### Missing public feature 的 RED 记账（尚未运行）
module/function/error 在每个 test call 内 lazy import；只在 exc.name 精确等于 NEW module 时给明确 `missing S0 public module: sisyfus.workers.lead_result` assertion，不掩盖依赖导入错误。Availability 与真实 captured-envelope test 必须因缺 feature 给 assertion；不造替身 module 或输出。feature 缺失时后续 semantic assertion 未触达，单独披露，不声称所有分支各有独立 RED。

## 9. MS14 已选定的精确深度与访问单位
1. 信封 root 的 container depth=0；每个 selected dict/list 的 child edge 加1，scalar 的深度不占 container allowance。measurement 自身为 measurement depth=0，depth4 container 合法，depth5 container 抛 DEPTH_EXCEEDED，不 pruning、不返回部分结果。
2. 每个进入的 selected 源位置 root/container/scalar 各计1；key 只做 type/cap 核对，不计 value visit。不同非祖先位置引用同一对象，各位置分别计；同一已处理位置再用于比较、Fact 或 statement，不再计数。output/container 常量不计。unknown/unselected value 不进入、不下降、不计数。
3. 每检查 measurement 的 root 也计1：4095 scalar+root=4096 合法；4096 scalar+root=4097 抛 LIMIT_EXCEEDED。denied measurement-key subtree 的 root 计1、withheld 计1，不访问其子值。4094 scalar+measurement root+1 denied root=4096 合法；增加第二个 denied root 得4097并拒收。
4. 判定顺序为 selected ancestor cycle → global container depth16 → measurement container depth4 → 源位置 value visit 及预算 → scalar/string 校验 → 有界扫描/复制子值。cycle 与 depth5 同一边发生时必须 INPUT_CYCLE。selected total>262144 抛 VISIT_LIMIT；不存在访问预算的重复派生计费。
5. NEW 共享对象 case 把同一 measurement 的4095文字标量+root放在64个不同源位置：仅 measurement 的下界已经64×4096=262144，再加确实被选择的其他源位置证明超限，不猜额外常数。32位置正对照保留全部精确 withheld 数，重复调用 JSON 相同；64位置重复拒收及等价独立容器拒收均使用 VISIT_LIMIT。原230-case draft与两项未定问题留在 Main 原件和作者旧 namespace，非本版 outcome。

## 10. 仍待后续 gates
本轮 STOPWRITE 后由 Main 检查 revised exact draft，再授权 formal freeze+一次 retained guard-on RED（在此 outcome gate 可使用已选 MS15 NEW retained fixture-only capture）。本轮没有 formal freeze、pytest 或 capture outcome；production 实现与 fresh independent Opus SOURCE review 仍另发release。safe capture/currentness、HTTP/page、研究结果与Mission-owned报告、W3选项、第二主机和手机均仍后置。
