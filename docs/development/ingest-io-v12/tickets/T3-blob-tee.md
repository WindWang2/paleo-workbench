# T3 — 拷贝路径的 blob 同读分发（消灭对刚落盘 payload 的再读）

- 状态：done
- 阻塞边：T1
- 验收：
  1. `place_managed_file(register_blob=True)` 的单次读循环同时写 payload 临时
     与 blob 临时文件；digest 确定后 payload 先 rename（顺序与今天一致），
     诚实校验通过后 blob 再 rename 进 `blobs/xx/<digest>`。
  2. 已存在同 digest blob 时丢弃 blob 临时文件，绝不覆盖（幂等语义不变）。
  3. 任一失败路径两个临时文件都被清理，无部分落地。
  4. 每个目标保持 temp+fsync+rename+dir fsync+read-only 全套原子性。
  5. `_place_blob_bytes`/`place_blob` 公共 API 原样保留（其他调用方与测试用）。
  6. 导入过程中对已落盘 payload 的再读次数 = 0（T5 钉死）。

# T4 — 目录导入元数据收集并发化（保序）

- 状态：done
- 阻塞边：T1
- 验收：
  1. `_collect_folder` / `import_files` 用 ThreadPoolExecutor.map 并发执行逐文件
     采集；added/warnings/filtered 顺序与串行版逐字节一致。
  2. worker 预算与 scanner 共享同一辅助函数；无新第三方依赖。
  3. 每文件 OSError 捕获语义不变（warning 文案与归属路径不变）。
  4. `test_data_import_service.py`、`test_import_registration_flow.py`、
     `test_issue379_import_threading.py` 全绿；新增随机延迟下的确定性测试。

# T5 — 回归钉（含反向对照）

- 状态：done
- 阻塞边：T2、T3（钉的是它们的合并效果）
- 验收：
  1. `tests/test_ingest_io_v12.py`：UI 漏斗新内容导入 == 2 次源读 / 0 次 payload
     再读 / 2 次写 / dedup 命中 == 1 次源读 / 0 次写。
  2. 反向对照：人为注入双哈希回归，断言计数器读到 3（≠2），证明主断言非空断言。
  3. 通过 `test_no_tautological_assertions` 守卫（无 `or True` 类凑数）。
  4. 确定性钉：并发采集在随机延迟下结果顺序仍与输入顺序一致。
