# Orchestra 实施状态

## 范围

见 TECHLEAD-ORCHESTRA-CONTRACT.md。最终要让用户在真实手机／网页发起同一任务，由本机和第二台机器协作，途中查询、补资料，刷新或重连后仍读到完整过程与结果。

## 当前推进状态（v42，2026-10-07）

**网页的图、进度与人可读工程结果已接到同一次任务捕获；真实双机与手机尚待各自验收。两所公开套利研究已产出易读报告，条件利润与真实盈利分开。**

### 网页：已实现与实测

- `/api/snapshot` 通过精确 opt-in header 一次取得原 `{id,snapshot,controller,controls}`，将原对象一次交给纯 S0，仅增第五个结果侧栏。图、进度和工程结果共用该 payload；没有第二次结果轮询，也不把非原子捕获包装成全局事务或重新验收。
- 页面先显示目标与结论，展开后显示实际 hash 增量、0/false 测量、审查理由、引用、集成与来源局限。错误、缺失、换任务和 stale 分开；保持原 Start、UNKNOWN、消息和控制权限，不因读取结果派发工作。
- 当前 Page `2404cd7d` / Console `c6bc670d`：固定有效原页面26、独立真实HTTP11、校准后预算1、真实长诊断码1，共 **39 项当前切片检查通过**；另有 **47 项旧邻接通过**，按各自选集记账。原47初始RED、旧13的HTTP helper错误与输入oracle差异、预算首次FAIL、DOM两次失败及新长码RED均保留，不称原47或旧13全绿。
- 独立原生 `claude-opus-5-5` 首轮抓到真实33字符诊断码被32字符校验误拒绝；先冻单例并复现，再只改诊断校验一行。新鲜独立原生审查为 **COMPLETED / actual claude-opus-5-5 / PASS / 0 findings**，所列源码与冻结材料保持。旧 native FAIL 保留。
- 真实本机网页接入独占的实际 Core/Hub：固定 value→answer 两节点，未 Start、0 次 controller native call、未验收。已在网页发 `/btw` 取得持久查询快照及补充信息 RECEIVED；补充还未绑定原生调用。切换到当前源码新进程后接回相同 mission_id 与两个消息，事件链有效。此为真实本机、桌面浏览器与持久化证据，不是模拟正例，也不是双机、手机或工程任务完成证据。

证据：[当前限定门与真实读回](/Users/xinhuang/github/sisyfus-techlead-rsi/artifacts/techlead/orchestra-20261007/web-current-source-replay-main-7dd878df02d94bdc80db8fcccf0b68f4/MAIN-CURRENT-S1-GATE-v4.1.json)、[当前实际Opus审查](/Users/xinhuang/github/sisyfus-techlead-rsi/artifacts/techlead/orchestra-20261007/web-source-native-review-main-v4-f9b1538dace5434084da0781125a1d52/native-outcome/outcome.json)、[真实桌面图与结果截图](/Users/xinhuang/github/sisyfus-techlead-rsi/artifacts/techlead/orchestra-20261007/web-current-source-replay-main-7dd878df02d94bdc80db8fcccf0b68f4/browser-current-graph-result.jpg)。

### 两所套利：给人的答案

- 只研究 Entropy 的 io 与 trade.xyz 的 xyz；四个重叠标的，三组当时盘口和24小时匹配资金费率有公开采样。当前 v3 报告经 Main 独立110项算术核对与原生Opus5.5独立 PASS；报价采样是2026-10-07约04:50 UTC，非持续在线或原子成交报价。
- 大成交额不等于盈利。被核对的公开策略是双 taker 的价差／premium-band回归；maker-taker 是另一种有成交概率条件的路径。完成开仓与平仓需四次成交，选定无账户优惠的 baseline 为4 taker成本3.6bp；只io开仓maker为3.0bp；io开平两次maker为2.4bp。资格返佣、points、队列成交与两所单位／公司行动条件均另列，未计作已到账利润。
- 当时约单边1000美元的立即往返三标的费后均为负；DRAM待价差回归的双taker路径仅约0.15美元／轮的条件数值。2000万美元总成交额、每轮单边净优势1bp，对应500美元的纯条件算式，不是观测容量或收益承诺。20k总资本的某月度资金费率场景约55.40美元，同样只在明确成本假设下成立。
- 真实订单0、私人账户0、realized PnL=null。旧短期PAPER窗口0闭环与负行保留；尚未证实长期可执行容量／稳定盈利。本公开研究页面单独保留来源pins，不冒充 S0 已具备研究发布或研究正文读取语义。

报告：[两所策略、净收益与风险的易读 v3](/Users/xinhuang/github/sisyfus-techlead-rsi/artifacts/techlead/orchestra-20261007/entropyio-tradexyz-public-economics-sol-efa65ce1b3804eb1965714d1ca076ec4/REPORT.zh-CN.v3.html)。

### 剩余条件与下一步

1. 真实双机：已信任且可达的 `ec2-3-114-104-180.ap-northeast-1.compute.amazonaws.com` 有现成Python3.14与Codex。最小20文件包仍只在本地；自动审查在任何远端写入前拦住传输，要求具体主机、私有源码和独占新目录／新节点凭据范围的明确确认。已提问，等待回答；无绕行、无SSH部署、无A7通过。
2. 真实手机：已观察到实体设备连接，但尚无Safari任务发起、/btw、补资料及刷新／重连的真机证据；现有严格loopback服务未为手机扩张公开入口。入口与操作需要单独确认；桌面窄屏或设备库存不记A8通过。
3. 原W3严格零写入／正常WAL辅助同步契约、研究读者原件根准入与报告认证路径、旧冻结oracle版本决定仍未选。WAL6无全目标通过的旧证据保持，本轮未重测或选契约。
4. 当前完成的是上述有限网页和公开研究切片，不是整个Orchestra、真实两机、手机、RSI晋升或实盘盈利验收。全局目标保持未完成。

## 历史推进状态（v41，保留）

**本轮完成的是“让人读懂工程结果”的底层模块与节点收尾修复；网页的新结果展示仍待接线。** 结果层围绕“要完成什么、现在结论是什么、具体改了什么、依据在哪里、还缺什么”组织内容。这里的工程验收不替代两个交易所的套利盈利答案，也不代表真实双机／手机闭环已经完成。

### 已完成和已观察

- **实际 Claude 复核完成。** 当前结果层 `lead_result.py`（`76b083e7`）与节点收尾 Console（`bd3903f2`）／CLI（`7d7c90f0`）分别获得独立原生 `claude-opus-5-5` 源码 PASS、零 findings；所列材料保持。仅按这两个版本和有限源码范围记账。
- **当前结果检查通过。** 先冻结成句11项与路径13项，分别保留真实 RED 6失败／5通过、6失败／7通过；两个根因仅增加44B现有成句过滤和26B路径 lookahead。最终纯逻辑298 PASS，原255产物流程也255 PASS（35.707s，原测试不变）。两组选集共享原254项，分开记录，不相加为553个独立检查。
- **原产物流程与独立物理读回完成。** 本机 fixture 真实执行2个生成评估器、20次原publisher发布和18次限定的可恢复Trash；Pauli与Main分别核对保留原输入、snapshot／candidate树、实际发布文件和Trash原inode／字节。Main读回215个原proof文件及其包含的19个fixture文件，未新增SQL／pytest／模型／评估器／网络／Trash动作。producer中的worker／review为typedStub，actual_model=null，与这轮真实Opus源码审查分列；评估器stdin只有源码空输入／EOF证据，未记录独立stdin流。
- **节点收尾源码门通过，旧oracle仍有差异。** 当前3项根因微回归通过；固定原10加type v3共10 PASS／1 FAIL。SOURCE04的同一compound谓词实际“事件存在=true、类型ValueError=true、字面message=false”；后续断言未触达。原11并非全绿。旧原生FAIL、ThreadDI差异、初稿／harness错误和旧测试保留，各按自己的版本归档。
- **网页接线点已核对。** 6个当前源文件与51段逐字摘录保持：复用已有同一次 `{id,snapshot,controller,controls}` capture可供结果投影，与图／进度共用来源。当前HTTP和页面尚未消费新结果；这是静态事实，不是新接口、错误策略、实施放行或浏览器验收。

### 下一步与独立验收

1. 网页消费同一次capture，显示目标／结论／实质变化／检查量级／审查依据／缺口；先固定接口、mission身份、schema与失败／stale策略，再冻结回归、实施、独立复核和真实浏览器验证。保持 `CALLER_CAPTURED_NON_ATOMIC`，不补造实时状态、cursor或再次捕获来拼报告。
2. 真实手机发起／补资料／刷新重连，以及本机与真实第二主机依赖任务协作，仍需各自实测；窄屏或本机loopback不替代这些验收。
3. 研究“Entropy与trade.xyz能否套利、如何获利、净利润有多少”仍需要两所的实际费率、盘口／成交、资金成本与风险证据。工程结果模块不把未知收益写成已盈利。
4. W3严格原件零写入／正常WAL辅助同步契约、研究报告认证路径和旧oracle替换仍未选择；本轮源码PASS不改变这些条件。

证据：[结果源码实际Opus PASS](/Users/xinhuang/github/sisyfus-techlead-rsi/artifacts/techlead/orchestra-20261006/s0-current-source-native-pass-main-v7.json)、[节点源码实际Opus PASS](/Users/xinhuang/github/sisyfus-techlead-rsi/artifacts/techlead/orchestra-20261006/n6-current-source-native-pass-main-v5.json)、[当前298读回](/Users/xinhuang/github/sisyfus-techlead-rsi/artifacts/techlead/orchestra-20261006/s0-main-path-prefix-pure298-green-readback-v1.json)、[最终产物物理读回](/Users/xinhuang/github/sisyfus-techlead-rsi/artifacts/techlead/orchestra-20261006/s0-current255-v4-main-final-physical-readback-v1.json)、[旧11谓词纠正](/Users/xinhuang/github/sisyfus-techlead-rsi/artifacts/techlead/orchestra-20261006/n6-current11-main-qualified-predicate-correction-v3.json)、[RED/GREEN/REFACTOR与最终补记](/Users/xinhuang/github/sisyfus-techlead-rsi/artifacts/techlead/orchestra-20261006/S0-RESULT-TDD-FINAL-ADDENDUM-v3.md)。

## 历史推进状态（v39，保留）

**节点最小修复已实测，fresh Opus 又抓到一处真实关闭竞态；人类可读结果模块已新增，来源定位修复中。** 当前仍是候选实施窗口，尚未发布完整 Orchestra 或真机验收。

- Console `0eb48667`／CLI `7d7c90f0` STOPWRITE。原节点 NEW10 为 9 PASS／1 保留字面 oracle FAIL；相邻61候选45 PASS／16 FAIL，等价历史整源对照55 PASS／6 FAIL。新增10项 ThreadDI 兼容性失败直接依赖 target.__self__ 旧内部形状；4项动态counter比较、mkdir和guard域问题是共享6项。所有旧测试及失败均保持，不记相邻全绿。
- Main 独立同字节 RBS04 v3：历史整源有效 RED（exit130而非1）→当前真实 public import GREEN（2.08s；实际观察2.002s），校验拥有的原socket、bootstrap、typed安全诊断与8个实留文件。只增加版本化补证，原10与补证v2的 formatter 失败继续保留。
- 新原生独立审查实际 COMPLETED、模型 claude-opus-5-5、10个输入pin保持、严格二键形状通过，裁决 **FAIL／1项P3**：首次closer设置 closing 后、进入 finally 前的中断可能丢失 close_done，随后重试永久等待。该窗口先冻最小回归，再补根因；无 SOURCE PASS 别名。
- `lead_result.py` 首语义254结果 **253 PASS／1 FAIL**，producer未选。FC23指出 map键名字被错误标为 map值指针的 RECORDED；这是既有来源契约的真实源码缺陷。保持原测试/合同，用对应已记录的检查名、依赖身份值和精确语义关联修复，保持 RFC6901／原typed值一致性。
- 完整255的 producer runner 另有已保留 harness 过宽rename失败，以及 ABSENT前置条件过期时的0调用边界失败。候选兼容的严格Trash／真实evaluator新版 runner 已静态冻结，待两个源码写集稳定后唯一完整窗口。报告认证、W3与真实设备仍有各自条件。

证据：[独立原生FAIL读回](/Users/xinhuang/github/sisyfus-techlead-rsi/artifacts/techlead/orchestra-20261006/n6-native-v2-main-terminal-readback-v1.json)、[节点RED/GREEN分域说明](/Users/xinhuang/github/sisyfus-techlead-rsi/artifacts/techlead/orchestra-20261006/N6-ROOT-TDD-MAIN-v3.md)、[结果源码首交接](/Users/xinhuang/github/sisyfus-techlead-rsi/artifacts/techlead/orchestra-20261006/engineering-result-s0-source-carver-v1-20dbaa1884294ad6a081e53246091d33/FINAL-HANDOFF.json)。

## 历史推进状态（v38，保留）

**实际 Opus 提案和独立审查已返回，进入有限源码实施。** 原生身份和旧失败继续留存，当前未发布新的完整 Orchestra 或真实设备验收。

- 节点退出边界 NEW10 一次冻结检查为 **1 PASS / 9 FAIL**：8 项暴露重复中断、见证失败、输出失败、路径遮蔽、导入阶段与关闭等待的目标缺陷；RBS04 先在 raw stderr 的 JSON 解析处停住，后续断言未触达。其晚到真实 selector 异常实际为 `Invalid file object`，与冻结测试后段期待的人工 fileno 消息不同。该测试和失败保留，单独版本补证处理，不让源码伪造该字符串。
- Main 独立 NOFOLLOW 读回 49 个实际 fixture 文件、原日志与冻结材料共 61 项；950 个保护 regular 文件在此窗口仍同字节。源码只释放 Console／CLI 的选定根因，写集、2 秒拥有资源观察边界和独立复核门槛固定；实现进行中，尚未 GREEN 或 SOURCE PASS。
- 人类可读结果 S0 最终静态合同已核对，NEW255 planned cases 正式先冻／一次 RED 门释放。先问“要完成什么”，再回答当前结论，显示实质文件变更、检查与量级、审查理由和集成依据。纯投影模块当前仍缺席；该切片不会打开数据库、文件、环境或发模型调用，不伪造实时状态。
- 真实第二台机器、手机入口、同任务刷新／重连以及报告认证与 W3 物理观察契约依然各自验收。普通 Opus 执行恢复不替代这些条件。

证据：[节点只读实证](/Users/xinhuang/github/sisyfus-techlead-rsi/artifacts/techlead/orchestra-20261006/node-host-review-boundaries-main-final-readback-v1.json)、[两文件实施门](/Users/xinhuang/github/sisyfus-techlead-rsi/artifacts/techlead/orchestra-20261006/node-host-main-authoring-release-v1.json)、[结果先冻门](/Users/xinhuang/github/sisyfus-techlead-rsi/artifacts/techlead/orchestra-20261006/engineering-result-S0-main-freeze-red-gate-v1.json)。

## 历史推进状态（v37，保留）

**两条原生调用均已终结，实际模型均为 claude-opus-5-5；继续进入先测试、后实现的窗口。** 结果设计按目标、实质文件增量、检查与实测、审查理由、集成证据组织，Main 已选择纯已有工程事实切片。该切片只消费调用方捕获的同任务信封，不打开数据库、文件或环境，也不生成新的模型报告。

- S0 返回完整九键提案，16 个冻结输入前后及 Main 当前读回保持；零原生工具调用。现在仅释放 NEW 合同和测试的静态编写，`lead_result.py` 仍缺席，测试结果／源码验收尚待。
- 节点组合独立审查提出 6 项，原生裁决为 `NEEDS_EVIDENCE`，重点是第二次 Ctrl-C 可能在 controller 仍存活时关闭网关，以及网关 shutdown 的等待边界。实际网关准入路径补核和 NEW 回归静态编写并行进行，源码继续 HOLD。
- SOURCE packet 请求扩展三裁决对象，而本轮通用 runner 期待二键 PASS／FAIL，所以 runner 的严格形状检查 exit1。原模型遵循 packet 返回，原 receipt、原失败和 40 个源／材料 pin 读回均保留；没有转换成 PASS、放宽原检查或重发原 session。
- 报告认证、W3 观察语义、原测试版本决定与真实第二机器／手机仍有各自门槛。提案、补充源码事实和静态测试均不计完整 Orchestra、真实设备或部署验收。

见 [原生终结与独立读回](/Users/xinhuang/github/sisyfus-techlead-rsi/artifacts/techlead/orchestra-20261006/resumed-native-terminal-main-readback-v1.json) 与 [本轮纯结果切片选择](/Users/xinhuang/github/sisyfus-techlead-rsi/artifacts/techlead/orchestra-20261006/engineering-result-S0-main-selection-v1.json)。

## 历史推进状态（v36，保留）

**用户已明确要求继续，原生登录就绪元数据已实际读回。** 已安装Claude Code 2.1.280，普通CLI状态为loggedIn:true／claude.ai；这不是Opus执行身份或额度数值证明。原native S0 ERROR与三轮blocked记录继续留存，当前按这次人类继续请求进入新的核对窗口；目标工具本身仍回报blocked，未用状态别名假造其恢复。

先执行当前固定Console9595／CLIcc7的独立原生Opus源码审查，以及同任务已有工程结果的纯投影Lead设计。旧S0 packet的Console6f pin已过期，新独占材料重新定位真实producer；旧v2脚本仍指向v1输出目录，所以保留它并另建fresh runner，避免覆盖或重复原调用。两条路径只传先前已允许的最小源码／合同／测试，不含凭据、私人账户、实际任务数据库或评估材料。

报告no-tools的bare／订阅隔离合同、W3观察语义与真实设备入口仍待原决定；额度恢复不选择这些合同、不授予Start／部署。生产源码、旧测试和旧证据保持HOLD，native最多同时2会话。见 [本次继续请求与就绪证据](/Users/xinhuang/github/sisyfus-techlead-rsi/artifacts/techlead/orchestra-20261006/user-resume-current-state-v36.json)。

## 历史推进状态（v35，保留）

**目标状态：blocked（待输入），不是完成。** 同一组前置条件连续3个goal turn没有变化，3个已分配Agent当前均终结，没有可继续等待的在途Agent句柄。完整的手机发起、本机＋第二台机器协作、途中消息与重连结果验收仍保留。

待确认项为：原生Claude登录就绪；报告订阅兼容隔离合同或保留bare／API计费；W3严格物理零写入或正常WAL辅助同步；原冻结测试版本决定；实际第二台机器及手机入口。已有问题继续有效，本次没有再发送重复问题。当前登录状态未探测，历史ERROR仅作为历史回执保存。

源码／测试／合同继续HOLD，零重复native派发、凭据操作、SSH或部署。状态和看板的本次更新只是如实记录阻塞，不计实施进展。见 [第三轮阻塞核对](/Users/xinhuang/github/sisyfus-techlead-rsi/artifacts/techlead/orchestra-20261006/goal-blocker-audit-v3.json) 与 [目标状态返回](/Users/xinhuang/github/sisyfus-techlead-rsi/artifacts/techlead/orchestra-20261006/goal-blocked-tool-result-v1.json)。收到能解锁路径的新输入后，恢复对应实施窗口；既有UNKNOWN与终结回执继续原身份核对。

## 先看结论（v34，2026-10-06）

**节点启停和错误诊断已有修复证据，新增6项边界测量也通过。现在最缺的是“同一个任务里的可读结论”及真实多机／手机运行；当前仍是稳定候选，不是完整 Orchestra 验收。**

### 本轮做成了什么

- 两条遗留线程路径已修复；纯净5005字符错误恢复原类型及4000字符前缀。改动仍只有 Console／主CLI 四个既有函数体和两个 import，正常返回仍决定权限，收尾事实不授予执行许可。原新增4项实际检查通过。
- **另外6项独立边界测量全部通过，exit0。** 覆盖未进入入口的超时、手工同线程假入口、外来线程假入口、后来hook拥有者、初始原hook异常和CLI-owned partial closing。前四项验证有限等待、原hook归属和避免误关其他线程；其被刻意拦住的线程在fixture救援前仍活着，明确记为负例事实，而非CLI已完成清理。后两项的原线程和双监听在fixture救援前已结束／关闭，无须fixture救援。
- 这6项是在既有实现后新增的 tests-after：先冻结，再运行一次；没有对应RED→GREEN修复。最终fixture线程均已结束，6个empty-unbound目录仍空，零native／provider／实际任务调用。

### 验证到了哪里

- 先前Main独立111项为110通过／1失败；另一次相邻273项为272通过／1失败。两窗口384项382通过／2失败，仍各自exit1。新增Carver6项为第三个独立窗口，单列6通过；原host54仍53／1，没有把三个窗口或旧测试记成全绿。
- 两个原失败仍是旧helper重复创建source的 FileExistsError，以及准备HTTP期望ERROR而实际canonical RECEIPTED。原测试、失败和尚未触达的断言均保留，版本决定待用户回复。
- Main独立读回6项XML、救援前／后资源、诊断和42份实际注册工件；当前保护域为**913个regular文件字节＋1条symlink指针元数据**。作者914域采用跟随指针的平面byte collector；Main不跟随alias，其canonical regular文件另在913域中读回。原NOFOLLOW读回ERROR保留，新v2明确域后通过，非生产缺陷／测试修复。
- 此前Main的392个candidate-window文件、390个非拥有parent文件、2个源码差异、递归61个非放行方法体和446个fixture regular文件读回证据继续有效，域保持分开。Sol静态核对及这6项有限测量不替代实际独立Opus源码审查，也不证明所有线程时序均覆盖。
- 新证据：[6项测量说明](/Users/xinhuang/github/sisyfus-techlead-rsi/artifacts/techlead/orchestra-20261006/node-host-observer-additional-verification-v1.md)、[Main v2资源与字节读回](/Users/xinhuang/github/sisyfus-techlead-rsi/artifacts/techlead/orchestra-20261006/n6-observer-controller-readback-v2.json)。原TDD v2、所有RED、setup失败、域错误和旧审查记录继续留存。

### 接下来为什么还没有完整闭环

1. **结果桥接尚未实现。** Reader源码事实已核对，但公共load会建目录／登记项目；basis只有snapshot_hash/event_count，缺少顶层结论与执行状态；发布缓存不重新验文件，控制入口会先发生状态变更。结果应从实际产物、测量、审查和集成证据回答“结论是什么、量级多少、依据及条件是什么”；先明确只读根准入、控制器身份／预算／停机边界和结果版本归属。归一化工程任务没有title字段。接口仍未选，`lead_result.py`仍缺席，静态事实和提案不等于产品可用。
2. **报告认证与普通Lead登录是两件事。** 当前报告author/reviewer走no-tools并固定`--bare`；S0工程结果设计走read-only，当前分支没有bare。Main独立核对13个pin、32片段／205行，确认这个源码区分。当前官方文档说明bare跳过订阅OAuth／keychain，走API key或显式helper；这不是本机安装版／当前登录探测。[官方bare文档](https://code.claude.com/docs/en/headless#start-faster-with-bare-mode)
   旧报告STATUS已记录该兼容性问题；订阅兼容零工具新合同或保留bare/API计费的偏好问题仍待回复，未再重复提问。S0原`Not logged in`回执保持，具体根因待验，不据bare解释它。旧no-tools ERROR的精确公开回执定位尚未独立取得；auth-status文件不是ERROR回执。旧合同／测试／失败保持，没有认证重试、参数变更或凭据操作。
3. **跨设备只有接线前核对。** Agent的loopback拨号端口与wire Host可分开，受信任的本机转发形状与现有节点准入相容；手机普通LAN／公共URL与当前严格Host／Origin不同，需要明确入口身份契约或设备本地可信转发。这是源码推断，没有选择部署或实际连通。[接线前说明](/Users/xinhuang/github/sisyfus-techlead-rsi/artifacts/techlead/orchestra-20261006/cross-device-source-admission-preflight-v2.md)

### 当前固定版本与执行边界

- Console **9595c8ee**／主CLI **cc7d4006** 继续稳定HOLD；5f1af759／31d468ec是留存parent。生产源码、所有既有测试／合同与历史证据保持冻结，当前source authoring放行文件数为0。只有Main状态／报告与新的独占补证工件写入。
- 下一步分开处理报告认证选择、普通只读Lead登录就绪、Reader合同与W3观察语义，再推进同任务实质结果及真实多机／手机接线。W3严格物理零写入或正常WAL辅助同步合同尚待选择；WAL6最终证据保持，未重跑。
- 新双源码／组合门、A5／A7／A8、真实第二台机器与手机发起／查询／补资料／重连结果均待验。已有本机原生任务、协议fixture、真实Chrome和560px桌面视口不代替这些验收。零SSH／部署／实际研究任务启动。

## 历史实施与验证记录（保留）

以下为各历史固定窗口的原记录；其中“当前”仅指当时版本，最新候选以上文及其完整hash证据为准。

- 开发分支：codex/techlead-orchestra-inbox。继承并保留报告流水线及先前所有未提交工作。
- 已完成能力核对；现有 installed 0.9.0 与历史服务保持分开。
- 已实现 canonical mission inbox、查询/消息 API、资料与调用的原子绑定，以及任务运行页输入框。原 bound draft 仍冻结。
- 本地首轮固定信箱测试 20 项通过，原始测试 hash 保持；后续根因修复各自新增并先冻结回归，保留红灯记录。
- 原生设计：claude-opus-5-5 请求与 runtime attestation 一致、COMPLETED。
- 独立源码复核 v1：原生 claude-opus-5-5、FAIL，三个 P2 已修复：长历史改双游标增量、RSI improvement 隔离资料及已含资料的 Lead session、超长提示词保持原 durable ERROR 路径。旧 fieldless wire 单独兼容，canonical 已确认后禁止降级。
- 独立源码复核 v2：同样为新原生只读 Opus 会话、FAIL。三个 P2 已实施根因修复：仅已交付资料降优先级、已知终结/缺接受证据显示 NOT_APPLIED 且原子推送更新、脱敏后的成功 POST 按原 request_id 确认。另补了真实 GUI 发现的 mission/native COMPLETED 文案区分与 schema-2 缓存迁移。
- 本轮回执测试存在明确版本冲突：五项 v1 冻结回归期望 BOUND，v2 的更严格终结语义为 NOT_APPLIED；保留源文件与失败回执，已请求用户确认版本升级。另一项新增测试把 Journal.events 公共字段 type 写成 event_type，修正前保留红灯，未据此修改生产 API。源码独立复核 v3 已 COMPLETED、实际 claude-opus-5-5、严格 PASS、零 findings、源码 hash 未变；这是更严格修订的源码审查，不替代上述用户契约版本决定及新冻结检查。
- 首轮执行回归：257 passed，37 项 HTTP setup 被沙盒 socket bind 拦下；保存失败日志，后续按许可重跑，不修改原测试。
- 首轮主控定向回归：548 passed，1 skipped；该 skip 是 opt-in loopback 测试，随后显式启用 loopback，HTTP 57 项全部通过。v1 修复后主控 backend/RSI/report 为 438 passed；frontend/旧聊天 HTTP/graph/preflight 为 196 passed，均保留工件。v2 新修复仍需重新验证。
- 完整回归 v1：1209 passed，11 failed。10 项为未改动的旧删除路径触发保留工件的永久删除 guard，1 项为进程组信号权限；该单项在许可下复测 1 passed。保留原失败、未关闭 guard、未改写旧测试，不宣称全量绿。
- 真实本地原生两子任务已完成：在 prepare-seed 调用运行时通过网页 `/btw` 查询并补充 operator_note，第二个子任务的 turn_bound 后资料为 APPLIED；两任务及集成均有 canonical PASS、独立原生 Opus 审核。固定 acceptance/source hash 不变，event chain 有效。
- 原生调用总数 5：worker 2 次明确请求 gpt-6.1-sol，其 native actual_model 遥测缺失（不据配置推断）；reviewer 3 次实际回报 claude-opus-5-5。此场景不替代另一台机器、实际手机或全目标完成。
- 隔离服务进程已真实重启并接回同一数据库/身份：历史资料 APPLIED、整项验收及集成仍保留，网页又发送一次 `/btw` 并读回既有结果，未 Start。新读回仍为 5 次 native call，全部 receipt hash 和 acceptance hash 相同。此时服务是前轮已实跑版本；最新回执/缓存修订尚未切换到该服务。
- v2 修复定向结果：前端 77 passed；backend/Lead/reader 251 passed、6 failed（上述五项语义冲突及一项新增测试字段笔误）；单独 reader/report 64 passed、原 v2 新增回归 14 passed。回归失败保留，不宣称当前全绿。
- 第二阶段身份/领取基础初始为 106 个固定测试。独立原生 Opus foundation review v1 为 FAIL：晚到回执遇到 PREPARING 上传被丢失、Receipt 输入字段缺少类型边界。两项已修复，新增 236 个冻结回归，主控 combined 342 passed。
- native foundation review v2 为 FAIL：已排队 offer 在别的调用变为 UNKNOWN 后仍可领取，且 sidecar UNKNOWN 未参与共享 spending fence。同库 claim/reserve admission 闸门已实施；新增固定回归 63 passed，原 342 项为 341 passed、1 failed。失败为 test_revoked_offer_is_never_claimed：其 helper 先 reserve，新的 UNKNOWN 闸门更早抛 DispatchBlocked，而旧测试只认后续节点检查的 PermissionError。保留旧测试与红灯，已请求显式新版错误顺序契约；未用异常类型别名取绿，未改 core status/receipt，不据 timeout 结算或补派。新独立复核仍待契约确认及稳定源码。
- 远端传输设计原生 Opus COMPLETED、实际 claude-opus-5-5。下一执行切片及固定接口见 TECHLEAD-NODE-INTEGRATION-CONTRACT.md；此为设计建议，尚未接入 remote driver/agent/API、SSH 部署或外网服务。
- N1 单事务远端事件流/资料接受回执已实现：event_in 复用原 Journal 事件边界；sync 按严格序号/digest 去重、redact 后持久保存、原 deadline 与 core continuation 在提交前终检。新冻结测试由 318 failed / 2 passed 到 320 passed；含旧 inbox/foundation 的选集 815 passed / 7 failed，失败名单与修复前相同。主控独立重跑 N1/UNKNOWN/registry 为 406 passed。节点源码复核 v3 原生 COMPLETED、实际 claude-opus-5-5、源码 hash 未变；由于严格 JSON 前多了前言而判 FORMAT_INVALID，保留回执，不将其作为结构化 PASS。新独立源码复核 v4 已 COMPLETED、实际 claude-opus-5-5、严格结构化 PASS、零 findings，源码 hash 未变；原 v3 格式失败保留。该 PASS 是节点基础/N1 源码审查，7 项旧契约冲突仍在，不据此宣称全量绿或远端执行接通。
- N2 operator 节点登记/库存/撤销与固定 placement 已实现，默认本机 fingerprint/replay 保持。确切 X-Sisyfus-Node 头遗漏另冻回归由 8 failed / 1 passed 到 9 passed；N2 三文件共 123 passed，operator 联测 233 passed、零 skip。邻接选集 1042 passed / 7 个既有契约冲突。远端保持 execution_ready:false，选择远端时在 reservation 前明确 ERROR，未伪装成本机派发；独立原生 N2 源码复核已 COMPLETED、实际 claude-opus-5-5、严格 PASS、零 findings，hash 未变。为实际网页选机器还需 N3 显式准备边界，见 TECHLEAD-NODE-PLACEMENT-LIFECYCLE.md；不靠启动后抢在 reservation 前选择机器。
- 主控跨模块最新回归（执行/审核/集成、RSI、信箱、节点、网页/graph 与 reader/report）为 1616 passed / 7 failed，384.03 秒。失败全部对应已记录的三组旧契约冲突，零新增组；未修改期望、未关闭 guard、未宣称全项目绿。产物基础正在独立根因修复，此选集不包含该模块。
- N3 输入/产物基础已新增 remote_artifacts：固定 snapshot、完整树诊断、delta/scope/upload 全量核对以及独占 before/candidate。先冻结测试红灯；首轮 79 passed、1 Trash 沙盒权限失败，许可后 80 passed，真实 Trash 原字节读回。尚未与 node 身份/lease/receipt、Driver/Agent 连线。独立原生源码复核 v1 为 FAIL 一项 P2：仅文本路径比较遗漏 APFS 大小写别名/firmlink，可能先把目标写进原输入树再报错；已补 inode/祖先根因修复，新冻结回归从 46 failed / 7 passed 到 53 passed；原80+新53合计133 passed，主控也133 passed，实际APFS/firmlink与原件树读回覆盖。独立原生 v2 仍 FAIL 两项 P2：后续绝对路径写入会重新解析已更换目录，以及 Trash 字符串路径可遇到中间组件 symlink 替换。正在另冻结 pinned-fd 写入/私有 Trash staging 的竞态回归并修根因，原133项保持；未部署该候选。
- 第二台机器目标和手机访问方式已询问；本机实现继续推进。
- N3 pinned-IO 源码修复已回传：新增冻结回归 29 failed → 29 passed；主控独立合跑为160 passed / 2 failed，失败均为旧固定的 candidate 原路径 Trash 断言，与新 descriptor-relative 私有 staging 流程冲突。旧测试/133-pass历史保留，已请求明确版本决定；新测试含真实文件及空目录 Trash 字节读回、28个错误边界原件树一致与fd收回。独立 native 源码复核仍待进行，此结果尚未晋升/部署。
- 下一接线切片已分开写入范围实施：NodeClaims 固定输入/状态/撤回/interrupt/完整树服务，独立 NodeGateway HTTP，显式 plan-before-placement 控制器边界，以及独立 RemoteCodexDriver。对应合同先固定、新增测试先冻结；此刻尚未把它们作为可执行闭环或真实跨机器证据。
- 用户已确认产物 IO v2 暂存契约：独立冻结两个一一对应新检查，旧两个原路径检查/失败与其余131项保持。v2首次为161 passed / 1 failed / 2旧项明确替换未选入；新失败是检查对象下标误取upload路径而非固定预期树，原版本/回执保留，纠正决定已询问。单独报告162项新版集合，不混称全项目绿。
- fresh native产物源码复核v3：COMPLETED、实际claude-opus-5-5、源码及逐函数固定依赖未变、严格FAIL两项P2。第一项是Trash退出0但对象仍在时缺少retained_staging定位，正在新增冻结回归及最小修复；第二项是通用pytest重复fixture名称的Trash读回可能读到旧同名对象。当前retained runner每fixture为UUID名称，仍新增每次独立文件名/字节核验强化证据；未修改旧冻结测试，也未宣称晋升。此复核只调用Read/Grep。
- 显式准备边界源码已稳定：新Mission检查21 passed；HTTP/Hub为69 passed / 1 failed；相关回归1217 passed / 8 failed / zero skip。新增失败为测试把canonical run状态预期成ERROR，实际原Journal分离为RECEIPTED与receipt.status ERROR，保留该断言及失败。原7项不变；fresh独立原生Opus源码复核进行中。准备为零Sol调用，未就绪远端Start继续等待机器，不吞作本机执行。NodeAgent另开独立模块切片推进。
- 上述准备 fresh review v1 已终结：COMPLETED、实际 claude-opus-5-5、hash 未变、FAIL 一项 P1。持久 REQUESTED 与线程启动之间崩溃，或跨 Hub Start 先拿锁，会留下确定未执行但所有重试都被挡住的准备状态。仅显式新请求可在原控制器锁下接替已知未执行步骤；旧请求归档且旧线程失效。新回归先冻结，原21/70测试保持，修复进行中；不把页面读回或 Start 变为自动重发。
- 产物微修主控独立2 passed，源 hash 7ae73ce5994b5570706fa28405cf58f4f6dec70e2382894a45a9a4a89f92cab1，冻结测试 ad50695ec6ff8fdb712cc580de2268463d1389de6bdc441eac0a98cced187d87；真实 Trash 每次 UUID 名称和独立随机字节保持。fresh review v4 已终结：COMPLETED、实际 claude-opus-5-5、hash 未变、FAIL 一项 P2。generic 失败分支在 rename 前或 Trash 移走后仍声称对象留在暂存路径；另开冻结定位检查并修最小诊断，成功路径与旧证据保留。
- NodeClaims 传输服务已稳定：新增190项红到绿，源码 hash 533ca8f38dc09eca27c880f0221783bef34e5e97a7c51fc49fd3829e00025e14。主控重新运行传输/N1/UNKNOWN/identity 选集为596 passed；作者扩展选集1005 passed / 原7 failed。逐函数固定共享 helpers/constants保持；fresh独立原生源码复核v1已COMPLETED、实际claude-opus-5-5、严格PASS零findings、源码hash保持。此为独立源码闸门，尚未据此宣称Driver/Gateway/Agent闭环或真实第二台机器验收。
- 网页入口第二缺口已固定为 TECHLEAD-NODE-WEB-CONTRACT.md：原聊天Start会立即派发，新增明确“先规划，接着选机器”与最后Start两步；普通聊天零派发，首次secret不进入页面历史或图。Chat backend独立实施中，HTTP/真实网页接线仍待。
- 产物定位微修已稳定为58dc9542163c152db4eeb181d391597a5dfb38e06763dab7b9f29ad5fcfb7d60；新增7项先冻结红到绿、原随机字节Trash2项保持。主控全部173项为170 passed / 原3 failed（用户确认替换的旧2项及待决定的env[3]检查对象笔误），零新失败组。fresh review v5已COMPLETED、实际claude-opus-5-5、严格PASS零findings、主源码及固定依赖hash保持；只计源码闸门。失败定位只报告经描述符/绑定/身份/字节核对的实际位置，未观察到的Trash结果保持UNKNOWN。
- 网页规划HTTP59项已先冻结为443ad448fb3c83e338758d4303dec70c81d99567207ba68b12c733838389a588；真实Handler的首轮为44 failed / 15 passed，缺路由造成红灯。新route尚未实现，安全边界、精确请求字段、零Start和错误透传不可据结果修改。
- 上述HTTP路由已实施并由主控59 passed；ChatSessions新准备backend112 passed，作者同选集旧99与新112为211 passed，旧检查保持。新的独立 native chat-preparation v2 已 COMPLETED、actual claude-opus-5-5、严格PASS零findings，主源码和逐函数固定依赖不变。普通沙箱首轮缺CLI登录返回ERROR，原回执保留；在用户批准最小传输范围内通过现有原生登录复核，不读取或复制凭据。此为源码审查，网页/设备验收另计。
- Standalone RemoteCodexDriver源码 b4369f4b614d64ea17058f5862e90db8f35af47e4e4f6fe90e4d6ff6cd176737，原新116项与另冻等待竞态2项主控118 passed。native source review v1 COMPLETED、actual claude-opus-5-5、严格PASS零findings，原版本固定依赖保持；record_in依赖新增后开启v2独立读回。Driver原Request.cwd不变，known native terminal与物化/验收分开，UNKNOWN不重发，旧offer只读。尚未接入Lead或部署远端。
- 准备独立审查v2为FAIL一项P2：SUPERSEDED归档与新REQUESTED分两次提交。最小修复由 LeadJournal.record_in 复用精确旧body并纳入同一次保存事务。helper新20项保留19 passed / 1原SQL注入误判：代理按原SQL startswith未覆盖旧多行缩进事件INSERT，实际没有注入异常；无源码空白alias。独立lstrip fault证据确认异常透传与metadata/hash-chain回滚，邻接157 passed。原20文件/RED保留，不混称20全绿。准备新原子检查与fresh审查随后单独记账。
- 网页机器交互新增20项已固定文档、静态核对当前公共shape、冻结 e6e479a6d5c217d696e0cc6783e4ab3948fa210d7d76a58bc58d446c0c592f0c；初跑20 failed，失败来自缺少规划/机器交互，现有页面未提前改动。新公开GET placements只读接口先实施，前端不依赖浏览器缓存猜测固定机器。NodeAgent配置已核对严格六字段，不把Registry namespace错当Hub身份。
- 准备原子微修主控合跑 helper20/atomic13/prep21/HTTP70/recovery12 为129 passed / 4原oracle差异，源码33de85a9d7a007dffcd017352fe150d1c1220e3c50bcbb29955f6378a4dbefad 与helper c9a43649全程保持。fresh native preparation v3已COMPLETED、actual claude-opus-5-5、严格PASS零findings、主源/最小console依赖保持。原检查失败仍为helper SQL未实际注入、两处Hub wrapper.phase误取、canonical RECEIPTED/native ERROR混淆；不加alias或据结果修改。
- fresh Driver v2保留FAIL一项P2：最后clock callback在最终currency guard后执行，失去lease/epoch/core后仍多sleep一轮。仅把sample移到guard之前，新clock_wait5先冻结为0f16905ff3306d622f97e2bf8ea4f69e0d5fe8d8c369b727c947192bbed23ae5，RED3/2到GREEN5，主控独立5 passed；作者原118+新5共123 passed且真实UUID Trash保持。源码f2925736b26157ebdd5a8cc509fbc1ea4cef553592db7ab02781551f0334375b，fresh v3复核进行，未沿用旧PASS冒充新版本通过。
- Gateway整连接微修主控214 passed / 原3 failed（new25全通过），query无原文、16慢连接释放容量。fresh native v2仍FAIL一项P2：_session取锁/加载越过deadline后，在下一check之前仍会lazy构造NodeClaims/remote目录。现另冻session-deadline回归并做最小前置check，原25/192及失败保持，未称当前gateway已全通过。
- GET placements只读接口已落地，主控新60+原chatHTTP59为117 passed / 2新增fixture setup差异：新历史计划按完整spec重新load但只有check a，遗漏spec固定required check b，尚未进入待测API。原两检查/失败保留，正在新增使用原validate_plan(existing=固定历史任务)的独立有效场景，禁止放宽必需验收。冷启动观察不构建controller/backend，读取同原只读事务。
- 下一host/CLI服务15项已静态核对真实 workers/lead_cli.py，冻结e15c11c4666ab1614fe09efe37d5b5534f8d8d031c6a43f97f1ea323e348c83b；首轮9 failed / 6 passed为缺少attach/detach/readiness与显式flag。该接线source尚未开始；默认无gateway、页面/node注册不授予远端派发，关机顺序保留合作停机及未知原件。
- Driver微修 fresh native v3已COMPLETED、actual claude-opus-5-5、严格PASS零findings，f292源码及固定依赖保持。原v1PASS/v2FAIL与全部RED不变。准备v3同样PASS后，正式放行Sol实现W1/W2 Lead执行入口：新增80项在源码前冻结bba204c8ab6002e1bf07db3cab3e8e9c77997abc611a218c5ef4ce83a7896b32，保留61 failed / 19 passed首轮；本机原fingerprint和cached调用不变，新remote原子固定完整placement/context，成功只用独立candidate经过原checker/review/integration。此刻接线仍在实施，不以component源码PASS宣称端到端或真机通过。
- 本轮主控补跑 Gateway3/25/192 为217 passed / 原3 failed，源码a604及冻结文件前后保持；只计隔离认证loopback。fresh native v3c COMPLETED、actual claude-opus-5-5、源及逐函数依赖保持、FAIL一项P2：deadline为ValueError而落入HTTP400，timer稍迟时可能在后台已提交claim后发过期响应。新增检查先冻再修；旧v1/v2失败、session3的RED/GREEN均保留。两个此前主控审查预检失败在native reservation前结束（_event实际override、并发源写入不完整），独立保留，不作模型调用或PASS。
- 机器读回历史/WAL新2为独立附加验证，冻结1f3cedc86467a6dd6a9e019d876b6ba3815c69185b03978ca6c64e48d7324595后首跑2 passed、零源修改，不宣称RED/fix或替代原60错误。主控新60/2/HTTP59为119 passed / 原2 failed。fresh readback native v1 COMPLETED、actual Opus5.5、hash保持、FAIL一项P2：approved_spec与随后的DB连接之间缺身份绑定，warm/cold均可能串读。另开冻结路径竞态微修，W3服务接线继续HOLD。
- NodeAgent稳定fe5efc13dbd586b11bdc43c6ca57bea952e592b41b7d2a9fe0a30d064994c7d2，新冻结116为e5957efd35c61a15f1a48b1312ab271b2cfb3c998c03e9be56cb8f92dc379f87。主控103 passed / 13 legacy get()['tree'] KeyError，保持原公共get无tree、status/receipt完整tree；额外冻结公共wire验证独立进行，不加alias、不把辅助数据库读回称原116通过。当前真实原生/手机/第二机器均未据此验收。
- 网页页面稳定c4c67eeee73743cf0509abae6e5d060afa586543ac4ecbde6bfc0336b4b8b0f6，主控新20+原80=100 passed，先前20 RED和冻结e6e479保持；补充9为8 passed / 1跨VM对象原型比较错误，实际正确/revoke wire另有只读证据。原20的revoke fixture漏/revoke且被错误路径捕获，绿灯不是该动作正向证明；独立页面审查与真实浏览器仍待，不假设这些fixtures等于设备验收。
- 本轮两个主控选集首轮pytest已运行，但zsh只读status变量使记录footer失败；原完整日志和补充哈希读回保留，同选集用rc重跑并准确保存退出码，结果仍217/3及119/2，删除guard保持。首次readback native也已产出COMPLETED/FAIL回执后footer错误，直接读回原receipt/findings而非重复native调用。
- Lead远端执行入口当前稳定c8bfff380d322e0593ff65bf13ec656eea9a88787b5dc51eb086b5364e68c7da，helper整文件c9不变；主控固定W2原80及另冻readiness3共83 passed、前后源码/测试hash一致。新3为未prepare远端Start零尝试、已完成与UNKNOWN回放不被当前readiness:false覆盖，RED3和freeze72210f7ce812cfb2caa51c974d3aaf1be19f9ba718e7547fa44d5fbcd5c15269保留。新的组合Opus审查已启动，尚未据此放行host/部署。
- NodeAgent fresh native v1 COMPLETED、actual Opus5.5、hash保持、FAIL两项P2：controller存储的redact(tree)与本地raw tree比较，合法sk样式文件名导致已收回执永久被判ACK错误；credential在APFS大小写别名下仍可实际位于state内部。另冻真实路径/ACK回归再做最小修复，原116/13差异及辅助读回不变。
- 网页fresh native v1 COMPLETED、actual Opus5.5、hash保持、FAIL一项P1和两项P2：matchingPreparation只比身份不验证ACK/control proof，UNKNOWN被清pending并导航；prepared chat任务Start只走/api/control，绕过原approval/spec/placement_start；pin.request_id缺凭据检查与clean。三个根因分开新增冻结回归并修页面，不改变backend授权或原100测试。浏览器/手机验收仍待。
- Lead接线 fresh combined v1 已 COMPLETED、实际 claude-opus-5-5、严格 PASS、零 findings；LeadMission c8bfff38、LeadJournal c9及固定Driver/Artifact/Claims和依赖前后保持。主控83 passed保留。只放行该源码组合门，不计W3服务生命周期、N5原生执行、A7/A8或全量旧契约通过。
- NodeAgent 两项 v1 根因微修稳定8c6fa0b1；另冻10项cb2624e2保留 RED8失败/2通过及 GREEN10通过。主控原116+新10合跑113 passed / 13原legacy get/tree KeyError、源码及Gateway/测试哈希保持。实际APFS路径和raw树/脱敏ACK证据保留。历史fe5版本固定的辅助公共tree13不是当前8c版本验收，独立v2待稳定Gateway后进行。
- 只读选择路径身份微修稳定6f507a1e，另冻45项1006873d保留RED45及GREEN45；主控60/2/45/HTTP59合跑164 passed / 原2无效revision fixture失败。fresh v2已COMPLETED、实际Opus5.5、hash保持、FAIL一项P2：warm store._transaction(immediate=False)内部仍创建连接及PRAGMA WAL，竞态拒绝发生在副作用之后。源码HOLD；拟warm/cold统一URI mode=ro单事务，旧warm-hook检查与失败均保留，等待契约版本确认，先冻新副作用检查。
- W4当前仅新增CLI合同与测试冻结：公开NodeAgent.run_once、默认一次、显式有限NO_WORK轮询、exact两字段回执和无异常message诊断。模块仍缺失时RED保留；N5/Gateway新门通过前源码保持未实现。CLI退出0不是任务PASS，uncertain不重派native，也不额外配置或复制凭据。
- Gateway late-response微修f35cd643、新14冻结851a6271保留RED13失败/1通过；主控新14+原3/25/192为231 passed / 3原差异，源码/测试前后保持。fresh native v4 COMPLETED、actual Opus5.5、hash保持、FAIL两项P2：无效secret+REVOKED先查状态而回403；NodeClaims.offer/bind尚未拒绝HTTP脱敏会改变的Node样式凭据文本，可能CLAIMED已提交但响应永久500。Gateway认证和Claims发布前准入各自另冻回归后最小修，旧版本533/f35及所有PASS/FAIL只按原pin记账。
- 页面首轮微修ab4b736b、新35冻结833d2bc3保留RED32失败/3通过；主控135 passed、原100及61既存测试哈希保持。fresh native v2 COMPLETED、actual Opus5.5、hash保持、FAIL一项P2：未成功完整读回聊天清单时误认任务无关联chat，generic Start绕过原prepared Start。新独立回归将覆盖失败/初始缓存/chatIssues/恢复边界；不凭空给旧任务套chat、不隐藏清单错误。
- NodeAgent fresh v2 COMPLETED、actual Opus5.5、源/依赖保持、FAIL四项P2：localleaseflag跳上传使上游可能误判及时，controller绝对期限与远端wall clock比较，IN_FLIGHT/UNKNOWN重启未传原outbox，partial dict receipt未作canonical ACK比较。仅放行对应源和NEW回归；先冻结RED再局部修，raw回执/body/原seq/原身份保留，native重派仍禁行。
- W4 TEST-ONLY已稳定冻结test4195b4ba及contract35051ff7。retained93结果2 passed / 91 errors / 0 failures / 0 skipped，91均精确缺node_cli模块、未过CLI setup；2通过只计公开签名及实际loopback NO_WORK。独立数据库读回1条NO_WORK、fixture凭据0600/状态0700/原source字节保持。255baseline与110旧测试读回保持；模块未实现，不称CLI/N5或native通过。
- Claims Node文本微修dc6e4460、NEW40 ad4e8baa保留RED29失败/11通过→GREEN40；主控40 passed、前后source/test一致。Gateway认证微修74edd423、NEW15 58e31989主控新旧249为246 passed / 原3 failed；页面eee0775f、新13 07a13ac8与另冻完成marker1 a824aa1f主控149 passed；Agent68194a4b、新17 731e20ee主控143为130 passed / 原13 failed。旧tests、失败及guard保持，全部选集前后依赖hash一致。
- Agent原8c RED至681 GREEN期间Gateway f35→74ed漂移明确披露，不改原测量。独立固定依赖74ed/dc6只读内存control复现exact8c的14失败/3通过，held681同依赖17通过；初次harness被guard拦住、0 checks另留，不计业务检查。只证明该有限复现中Gateway漂移单独解释不了原失败，不计时序压力或A7/A8证明。
- fresh admission v1与Gateway v5均COMPLETED、actual Opus5.5、source/deps保持，分别FAIL一项P2/P1，指向同一offer完整记录redact遗漏；计一次根因微修。只放行offer事务前的完整immutable检查和NEW冻结回归，不清历史poisoned/UNKNOWN、不改N1digest，原dc6/40与全部旧证据保留。
- fresh Agent v3 COMPLETED、actual Opus5.5、source/deps保持、FAIL一项P2：HTTP409也可能为IdempotencyConflictError/OSError，当前误当LeaseLost，live claim正常失败被冻结partial receipt_body。另冻严格bounded error.type分类检查，仅确证上游租约/权限丢失走subset，其他错误显式留待同身份retry，禁止native重派。
- fresh页面 v3 COMPLETED、actual Opus5.5、hash保持、FAIL一项P1：uncertain machine操作未提交时缺同请求显式retry，pending阻断所有动作与Start。另冻当前mission、完整GETnodes/placements读回后exact原path/body/id重试；无自动重发、新ID或猜pin。真实浏览器/手机仍待。
- SQLite只读副作用新增29项为22 failed / 7 passed，包含4项已记录的absence-oracle假阳性，原test不修。实测URI mode=ro仍创建/更新shm，现连接建议尚非充分根因修复。console6f/store87继续HOLD，已补问原件严格零写入或正常WAL辅助同步的语义；旧warm-hook/原60/45/2与其失败保留。
- offer完整记录微修稳定0073e15c，仅新增2行protocol.redact检查，helpers/constants和bind原样；NEW64冻结275110c1保留RED39失败/25通过→GREEN64，主控新64+原40共104 passed、源/测试/依赖前后保持。作者固定1116检查为1109 passed / 7旧失败，Driver/W2附加220 passed / 3旧失败单列，不用其替代主控或whole-stack验收。fresh transport v2与Gateway v6仅固定该新版本源码门。
- NodeAgent错误类型微修稳定5bab92bc；NEW20冻结901e2e1f保留RED11失败/9通过→GREEN20，主控新旧163为150 passed / 原13 get-tree KeyError，源及0073/74ed依赖、原tests前后保持。仅bounded error.type决定真实authority loss，正常IO/conflict保留完整pending事实供原身份retry，不freeze局部body。fresh独立v4进行，W4仍test-only/source ABSENT。
- SQLite原件只读可行性另外冻结artifact-only三候选×existing/missing shm的6fixture，强制真实WAL-only generation、独立writer和旧snapshot、reader-only观测树与合法writer变化分列。无productionimports/全局VFS注册、无原mission访问；全部os._exit保留WAL/shm。此checkpoint只有staticfreeze，没有DB outcome，不选择生产契约、不改变原29/60/45/2或W3闸门。
- 三项fresh独立源码审查已终结，实际模型均claude-opus-5-5，源与依赖窗口均保持：node-agent-review-v4 PASS零findings；node-transport-full-admission-review-v2 FAIL一项P2、node-gateway-review-v6 FAIL一项P1，后两者是同一claim请求ID的先提交后不可传输根因。原审查结果/旧失败不替换，后续NEW冻结测试与最小源修复分别记账；W4源仍ABSENT。
- WAL primitive artifact-only固定6例已运行一次，原freeze d0e97a29/d487aa7d保持。4例三列PASS但zero-write FAIL；2例SQLITE_IOERR_LOCK 3850均INCONCLUSIVE，测量exit1。主控独立文件与trace读回exit0只说明保留证据一致：54边界/157快照payload/35当前文件/16guard-active trace，零SQLite打开/子进程启动/网络/移除；它不是测量GREEN。证据wal-primitive-controller-readback-v1.json。生产契约、系统调用全覆盖、真实设备与整栈均未据此放行。
- 领取ID与网页重试已FINAL HOLD并主控复测：Claims8302/NEW71 53ec、Gateway9878/NEW28 a5e7、Pagebf2/NEW41 7e2f。原失败/RED/首次实现/依赖漂移记录不删；主控单独当前固定窗口320/1、274/3、190保持全部beforeafter hashes。Gateway新28加载真实只读0073源码控制，独立解释HTTP入口改动，其他旧249在当前8302下另行记账。新增独立native三session在途，当前Lead83/Driver123/Agent163依赖兼容369合跑在途；无重复调用或已有未知回执重发。
- 当前依赖兼容369由主控终结356通过/13原get(tree) KeyError，全源/原测试beforeafter保持，证据current-dependencies-compat-controller-v1.json/log。fresh transport-v3 PASS零findings；Page-v4 FAIL一项P2在途POST/GET竞态；Gateway-v7 FAIL一项P1完整响应预算、一项P2选定路径ID的redact稳定性。实际模型均claude-opus-5-5，审查窗口各版本源和依赖保持；原审查FAIL与旧阳性/阴性记录保留。
- Gateway响应原语另开一次最小原生Lead只读设计，explicitOpus、固定文件包与事务片段、禁止源码/测试写入。原响应所有depth/item/byte边界及原完整shape保持，不使用byte-only放松、提高上限、裁剪ACK或重写真相。动态view必要预算拟在原mutable transaction提交前做pure controller validation，方案/新冻结测试/源实现还各自有门；此时W4模块仍ABSENT、N6仍HOLD，严格零写入/WAL aux契约仍待用户选择。
- 该最小Lead设计已COMPLETED、实际claude-opus-5-5、所列源及事务片段前后保持；它不是源码通过。主控选择TEST-ONLY新增固定合同：NodeClaims.receipt可选pure admit_response(None默认原行为)，首次关联写事务在commit前验证detached完整view，失败回滚关联receipt/tree/event而保留先行独立expiry/upload事实；Gateway维持原完整frame/64层/50000项/4MB，路径不可表示时404在auth/lazy前拒绝，缺新公开能力在dispatch前显式500依赖错误。原有函数/源码仍HOLD，NEW测试先静态/SHA冻结/RED后才另行放行实施；候选其他route边界推断、item floor、可达byte负例及真实event cache还需源证明，模型方案不替代这些事实。证据gateway-response-admission-test-release-v1.json，W4/N6仍HOLD。
- A1–A8 尚待本轮实施与验证，不把窄屏或本机协议测试计作真实手机/多机器验收。

## 证据目录

`artifacts/techlead/orchestra-20261006/` 保留完整目标/源码 baseline、红灯日志、失败诊断、native-lead 回执、Sol 写入范围、后续回归/原生/浏览器证据。

## 使用语义

- 进入“任务”，而非继续修改已开工的规划草案，在同一页面输入 `/btw` 或 `/btw 现在卡在哪？` 查询。
- 普通文本是资料补充。先显示“已收到”；绑定下一次合适的 Lead/worker 调用后显示绑定回执；原生确认接受该提示词后才显示“已应用到调用”。这不是模型遵循或任务验收的声明。
- 已知调用结束但没有接受资料证据将显示 NOT_APPLIED；UNKNOWN 或仍在运行的调用保留待核对，不假设资料交付成功。该状态及增量更新正在收敛验证。
- 当前调用不被补写，已停止/暂停状态不因消息改变。独立审核、RSI 对照与 holdout 不接收这条资料通道。

## 提交前完整回复检查：v2 新冻结红灯与实施窗口

- 主控已核对新直接服务190项冻结：164失败/22通过/4本机bind setup错误保留；原样获批loopback续跑4项均失败，真实reserve→offer→HTTP复现claim/heartbeat提交后500。两轮联合覆盖不是一轮190全部重跑。
- 新HTTP v2 92项（4c546808…）先冻后RED84失败/8通过、无setup错误；旧预先正式冻结66项82e13/契约0a1b原件保持，新v2另文件，不用一参数或状态兼容别名制造绿灯。
- 源码写入分别只放行Halley的NodeClaims与Pauli的NodeGateway：五方法可选二参数纯验证、同事务控制快照、hook分支更严格原deadline前后检查。默认None、只读/缓存/重放、原独立expire与upload PREPARING/文件效果保持。
- 先编译、原样新回归、相邻回归和真实工件读回，稳定停写后再由主控发起新独立原生Opus审查。当前不是源码/整栈验收，CLI/W3/N6/部署/实际多机与手机仍各自待验。

## 用户决定：NodeAgent 超时竞态修复（2026-10-11）

- 根因：`NodeAgent._call` 的 socket 单次 recv 超时与 watchdog 共用同一截止时间，socket 先到期时原始 `TimeoutError('timed out')` 未转换，`test_node_agent_network_profile` 每次随机 12–14 项失败。
- 先冻结新测试 `tests/workers/test_node_agent_deadline_race.py`（1ca421cb）：延迟 watchdog 使 socket 必然先到期；RED 为 `'timed out'`，最小修复（node_agent 2f0abd23，新增 `except TimeoutError` 转换为聚合截止错误）后 GREEN，3/3。
- network_profile 由随机 12–14 失败变为固定 1 失败；节点集合 122→110 失败（修复 13、新增 0 其他失败），相邻 node_agent 使用者 100 passed。
- 唯一新增失败为冻结范围锁 `test_static_constructor_cli_and_only_duration_change`（要求 `_call` 与固定 baseline 仅差 duration 一行）。用户已确认保留修复：该范围锁就此修复视为被取代，测试原样保留、不修改、不 skip。

## 用户决定：放置恢复测试读取修正（2026-10-11）

- 根因：`tests/workers/test_node_placement_recovery.py` 第65、109行从 `MissionHub.snapshot()` 信封顶层读取 `['phase']`；信封自 HEAD 起即为 `{id, snapshot, controller, controls}`，`phase` 位于 `['snapshot']`。两项测试因此在该行 KeyError，其后的归档与 driver 请求断言从未执行；属测试读取错误，非源码问题。
- 用户批准修改该冻结测试：仅两行改为 `['snapshot']['phase']`，其余字节不变；文件 fa12ef4f → 171ab539。原哈希仍被 222 项既有记录固定，这些记录指修改前版本，原失败记录保留。
- 修改后同文件 12 passed，3/3；此前未执行的归档与 driver 请求断言首次运行并通过。无源码修改，无其他测试导入该文件。
