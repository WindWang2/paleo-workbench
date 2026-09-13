# 04 — 已知限制与未做项（诚实录）

> 这些是本 Goal 明确**没有**做到或**有意不做**的事，不粉饰。

## 1. 「读 1 遍 + 写 1 遍」的字面目标不可达，本次交付的是可达下界

D5 给出证明：在「落盘结构不变 + dedup 命中 O(1) 免拷贝 + manifest 行为不变 +
诚实校验保留 + 不硬链接」的约束下：

- 新内容导入下界 = **2 次完整读**（dedup 判定需要拷贝前 digest ⇒ 一次读；
  诚实校验要求拷贝中哈希 ⇒ 拷贝读）。本次达到 2R+2W（原 3R+2W）。
- 写下界 = **2 次**（payload 与 blob 是两个必须完整落盘的文件）。硬链接
  被 `test_no_writable_hardlink_is_created` 与不可变性文档语义排除；reflink
  不可移植到 Windows。
- 去重命中下界 = **1 次读**（UI 漏斗已达到；service API 未知来源 digest 保持
  2 次中的复核那次——这是钉死的契约，不是遗漏）。

若未来愿意接受「首次导入版本直接指向 blob（落盘结构变化）」，1R+1W 才可行，
那是一次显式的语义变更决策，不属于本 Goal。

## 2. 相对路径 + CWD==项目父目录 时，UI 漏斗 dedup 命中仍是 2 次读（BASE 持平）

`import_service` 对项目内文件记录 project-relative 路径。lifecycle 对相对
路径不标记新鲜度（D6/P2-2 修复的安全边界），此时：
- CWD ≠ 项目父目录（常态）：lifecycle 哈希失败 → adapter 自己哈希解析路径
  → 新鲜 → 1 次读 ✓
- CWD == 项目父目录：lifecycle 哈希成功但不标记 → dedup 复核 → 2 次读
  （= BASE 行为，无回归，也无改进）

彻底修复需要 lifecycle 拿到项目路径来解析（端口协议目前不暴露），属于
另一个 Goal 的接口变更。

## 3. 无 digest 的重复内容导入：blob 临时文件写了再删（Spec 评审 P2-3，接受）

`service.import_raw(src)` 不带 `known_sha256` 且内容已在 blob store 时
（interchange 适配器的直接调用路径），单次流式读无法预知 digest，tee 必然
先写 blob 临时文件、digest 出来后发现已有 blob 再丢弃。BASE 在同路径是
O(1) 免写。语义不变、多付一次临时写；换回「再读 payload 写 blob」是 3R，
更差。已在 03-verification 注明。

## 4. tmpfs/全缓存小文件场景下，并发采集比串行慢

270 文件 best-of-3：串行 25.5ms → 并发 60.5~100.7ms（共享机器上噪声大）。
线程池启动开销在页缓存全命中时大于收益。真机械盘/网络盘（本产品的目标
场景：GB 级地震数据、NAS 工程目录）stat+探针延迟远大于线程开销，并发才
兑现收益。保持与 `scanner.py` 一致的无条件并发（仓库既有取舍），未加
自适应阈值（避免引入新可调参数）。

## 5. external 资源注册时 lifecycle 仍会做一次无效哈希（BASE 行为保留）

`link_external` 与 adapter external 分支从不消费 checksum，但 BASE 的
lifecycle 对 external 资源也补哈希。为保持逐字节 BASE 平价而未优化
（D6 修正记录了取舍）。

## 6. 本 Goal 未做的事

- derived/result 注册路径（run 产物）的 pre-hash 未动（D9 范围排除）。
- `catalog/service.py` 缓存/事务框架、schema 版本未动。
- `native/`、`third_party/`、QGIS 桥、`_vendored/` 未碰，未做任何 C++ 构建
  验证（本 Goal 纯 Python，不需要）。
- wayfinder/to-tickets 的 ticket 保存在本地 docs（D4），未发 GitHub Issues。
- 未跑全量测试套件（按编译/并发预算只跑相关文件 + 守卫），未依赖 CI。
- `run_env_io.sh` 等既有包装脚本未更新（它们属于其他 worktree 的产物，
  不在本 worktree 内）。

## 7. 测试环境的诚实说明

- 主验证环境是「主 checkout venv + PYTHONPATH 指向本 worktree」（D10，
  仓库 `run_env*.sh` 的既有约定；已核实包解析指向本 worktree）。
- 独立 worktree venv 在网络恢复后补装完成，全部相关套件（348 项，含
  tautological/integrity 守卫）在其上复跑通过，双保险。
- Linux 单平台验证；Windows 分支（`fsync_dir` 的 win32 短路、NTFS 只读位、
  打开文件的 unlink 限制）靠既有跨平台测试与代码审查覆盖，未在 Windows
  实机跑过。
