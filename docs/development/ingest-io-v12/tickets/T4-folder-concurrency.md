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

- 阻塞边补充：T1（基线）。
- 验收补充：新增显式路径变体钉（不是文件 warning、`._` 不跳过）与 lifecycle 新鲜度边界钉。
