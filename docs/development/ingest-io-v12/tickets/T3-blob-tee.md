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
