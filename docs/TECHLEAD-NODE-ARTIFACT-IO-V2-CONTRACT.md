# 产物 IO v2：已确认的可恢复暂存契约

用户本轮明确确认：采用固定描述符移入独立暂存目录后再 Trash 的更严格
新版契约，保留旧测试与失败证据。这个确认仅覆盖下面两个 Trash 位置检查；
信箱/UNKNOWN 旧契约差异、全局删除禁止、Orchestra A1–A8 保持各自状态。

## 版本关系

- 原80项 `test_remote_artifacts.py`、53项 roots 与29项 pinned-IO 文件保持
  原字节/hash。旧 `test_real_deletion_uses_exact_trash_argv_and_is_recoverable`
  和 `test_failed_trash_explicitly_retains_candidate_before_and_originals`
  要求直接 Trash candidate 原路径；旧完整运行的2 failed / 160 passed 保留。
- v2 用新文件 `test_remote_artifact_io_v2.py` 中两个一一对应的固定检查替换
  这两项原路径期待；其余原131项及新增29项继续必需。新版共162个固定检查。
  旧完整套件仍单独运行和报旧差异，原件保留/字节核验/错误诊断不删减。
- v2 新测试先冻结，再执行新版确定性检查及 fresh independent native review。
  新版全绿只描述该162项产物 IO 集合，不代表全项目、transport 或 A7/A8。

## 正常 Trash

- 真正 syscall 仍为 `/usr/bin/trash <absolute-path>`，严格两个 argv，无 `--`。
- 目标在独占0700 envelope 下私有0700暂存叶内；不在 candidate 路径下。
  同名、hash/size/单链接普通文件在 CLI 前核对；源/目的 descriptor-relative
  rename 被记录。没有覆盖旧工件或根目录重建。
- 原 source、input snapshot、before 的全树与字节保持；candidate 的已删
  文件缺失且完整树等于固定新树。实际 Trash 原字节读回。

## Trash 失败

- 注入已知 Trash 失败仍为显式 ArtifactError/trash_failed，无成功 candidate。
- 原 source/input/before 的全树及字节保持；独立暂存目录中原副本完整保留，
  失败报告给出 retained_staging，candidate 中不伪造原路径还在。
- 固定描述符关闭/目录替换/碰撞与文件、空目录竞态继续由原29项检查覆盖。
  没有永久删除、本机重新执行、scope 放宽或验收成功推断。
