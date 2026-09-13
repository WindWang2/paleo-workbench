# T1 — 基线实测：单次受管 RAW 导入的读/写遍数

- 状态：done（见 ../01-baseline.md）
- 阻塞：无（首个票）
- 验收：`measure_io.py` 输出各漏斗的 源读遍数 / payload 再读遍数 / 写遍数（mkstemp 计数）/
  SHA-256 全量遍数，数字与 §3 静态分析吻合（3R+2W / dedup 2R）。

# 说明

用运行时包装（Path.open / tempfile.mkstemp / checksum.sha256_file）计数，
不用静态推断。脚本随文档入库（`measure_io.py`），PR 前后各跑一次。
