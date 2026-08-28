# ADR 0061: Zarr v3 + Sharding 作为百GB地震体内部存储格式

- Status: Accepted
- Date: 2026-08-28
- Deciders: WindWang2（产品裁决），ZCode wayfinder 会话（基准执行）
- 来源: Wayfinder 地图 [#1067](https://github.com/WindWang2/paleo-workbench/issues/1067) 工单 [#1068](https://github.com/WindWang2/paleo-workbench/issues/1068)（调研）[#1070](https://github.com/WindWang2/paleo-workbench/issues/1070)（基准）；规格书 `docs/specs/100g-seismic-volume-architecture.md` §1

## Context

100 GB float32 地震体（2500 万道）在 32 GB 桌面机上无法整载内存；SEG-Y 直读的 crossline/timeslice 跨道寻址在此规模不可用。需要内部署分块格式承载切片浏览、三维属性、AI 推理、渲染四条链路。

## Decision

**Zarr v3 + sharding**，默认参数 chunk (64,128,128) / shard (128,512,512) / zstd clevel 5 无 bitshuffle。HDF5 降为单文件分发备选；自研 bricklet 不做。

## 依据（100G 合成体实测，外置 USB-NTFS 冷缓存）

- 转换吞吐 95 MB/s（HDF5 45 MB/s）；落盘系数 1.24×（HDF5 1.25×）。
- 冷首读全面占优：inline 4.4 s / crossline 2.8 s / timeslice 11.8 s（HDF5 6.2 / 9.4 / 36.9 s）。
- HDF5 暖缓存优势（rdcc、毫秒级切片、×3.6-6.4 并发）在冷盘全部反转。
- sharding 将 100 GB 体收敛为 801 个文件（NTFS 友好）。
- 读放大模型实测精确验证：切片延迟 ≈ A（=法向 chunk 边长）× 解压吞吐⁻¹；bitshuffle 使读延迟劣化 3-7× 仅换 ~3% 落盘，故默认关闭（真实数据收益复测列为开放验证项）。

## Consequences

- 多分辨率（LOD）以 group 级联 `::2` 表达（懒构建）；zarr-python 3.3 同步 API 并行读未兑现（0.9-1.7×/8 线程），AsyncArray/多进程验证列为实施期验证项。
- 道头不入 zarr，结构化元数据走 zarr attributes + SeismicSurveyEntity（ADR 0059）。
