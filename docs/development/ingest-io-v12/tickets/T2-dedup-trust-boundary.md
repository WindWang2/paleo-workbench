# T2 — dedup 快路径的新鲜摘要信任边界

- 状态：done
- 阻塞边：T1（先有基线数字才能证明改进）
- 验收：
  1. `place_managed_file`/`register_version`/`import_raw` 新增私有参数
     `_sha256_verified=False`；True 时 dedup 分支跳过 `_digest_of` 复核，
     size 检查与 OSError 回退保留；拷贝分支不变（仍 inline 哈希并比对）。
  2. `adapter.register_input` 仅当 digest 由本调用内的新鲜哈希得出时置 True。
  3. `lifecycle.register_resource_input` 透传 `resource.checksum`（不再自行补哈希）；
     external 资源不再被无效哈希。
  4. `tests/test_catalog_dedup.py` 全绿（service 层复核契约不动）。
  5. UI 漏斗 dedup 命中 = 1 次源读（T5 钉死）。
