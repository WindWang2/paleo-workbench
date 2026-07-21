# 地震数据 (SEG-Y) 双级 LRU 缓存与异步预加载架构设计方案 (Issue #6)

**Author/Owner:** GeoViz Seismic Architecture Team  
**Date:** 2026-07-21  
**Status:** Proposed / Research Complete (Addresses Issue #6)

---

## 1. 现状分析与痛点 (Current State & Bottlenecks)

在现有的 `geoviz_seismic` 实现中：
1. **内存缓存机制简单且缺乏字节容量上限**：
   `cache.py` 中的 `SeismicCache` 采用基于 `OrderedDict` 的简单数量限制 LRU 缓存（默认 `max_slices=50`）。对于大型地震体（例如 $2000 \times 2000 \times 1000$ 的 32位浮点数体），单张切片大小可达 8MB ~ 16MB，50 张切片即占用 400MB~800MB 内存。缺少动态 Byte-budget 限制，在多工况或多体数据下极易引发 OOM。
2. **缺乏显存 (VRAM) / Texture 缓存机制**：
   每次切片在 2D 剖面 (ProfileWidget) 或 3D 正交切片 (Renderer3D) 渲染时，均需重复经历 CPU-to-GPU 的纹理上传（`glTexImage2D` / `QOpenGLTexture`）。重新浏览先前切片时产生不必要的传输开销。
3. **拖拽/切片浏览阻塞 UI 主线程**：
   在 `SeismicView._apply_pending_slice` 中，当 LRU 缓存未命中（Cache Miss）时，会直接在 UI 主线程上调用 `_loader.read_inline()` / `read_crossline()` / `read_timeslice()` 进行同步磁盘 I/O。对于 multi-GB 的 SEG-Y 文件，非连续寻道的切片读取（尤其是 Crossline 和 Time Slice）延迟高达数十到数百毫秒，导致界面拖拽严重卡顿。
4. **缺乏预读 (Prefetch) 与取消机制**：
   用户连续滑动切片条时，中间产生的许多无用切片读取请求无法撤销，造成磁盘 I/O 队列积压。

---

## 2. 双级 LRU 缓存架构设计 (Dual-Level LRU Cache: RAM + VRAM)

设计 **RAM (L1)** 与 **VRAM (L2)** 两级协同的 LRU 缓存体系，各层具备独立的字节容量 (Byte Budget) 策略与生命周期管理。

```
                 +-----------------------------------+
                 |    Slice Request (Type, Index)    |
                 +-----------------------------------+
                                   |
                                   v
                      +-------------------------+
                      |   L2 VRAM Texture Cache |  (Hit: 0ms GPU Upload)
                      +-------------------------+
                         | Hit               | Miss
                         v                   v
                    [Render GPU]    +-----------------------+
                                    |    L1 RAM Slice Cache |  (Hit: Decoded numpy array)
                                    +-----------------------+
                                       | Hit             | Miss
                                       v                 v
                                 [Upload VRAM]    +--------------------------+
                                                  | Async Preload Queue (I/O)|
                                                  +--------------------------+
                                                         | Disk Read
                                                         v
                                                   [Fill L1 -> Fill L2]
```

### 2.1 缓存键设计 (Cache Keying Scheme)
为了同时满足原始地震切片、属性切片与 GPU 纹理的唯一标识，定义强类型缓存键：
```python
@dataclass(frozen=True)
class SliceCacheKey:
    volume_id: str           # 文件路径或 Volume UUID
    slice_type: str          # "inline", "crossline", "time", "arbitrary"
    position: int            # 实际线号/采样点索引
    downsample_factor: tuple # (fi, fx, ft) 降采样因子
    attribute_id: str = "raw"# 属性类型 ("raw", "envelope", "freq", "rgb_fusion", etc.)
```

### 2.2 L1 RAM Slice Cache (内存切片缓存)
- **存储对象**：解算后的 CPU `np.ndarray` (float32 / RGBA)。
- **容量控制**：双重限制 —— **最大字节数 (Byte Budget)** (如默认 512 MB) 与 **最大切片数量上限** (如 200 张)。
- **淘汰策略**：基于 `OrderedDict` 的精确 LRU 淘汰。插入前检查 `current_bytes + new_bytes > max_bytes`，依次弹出 LRU 尾部元素并释放 NumPy 内存。
- **线程安全性**：使用 `threading.RLock()` 读写锁，确保后台异步预加载线程写缓存与主线程读缓存的原子性。

```python
class RamSliceCache:
    def __init__(self, max_bytes: int = 512 * 1024 * 1024):
        self._max_bytes = max_bytes
        self._current_bytes = 0
        self._cache: OrderedDict[SliceCacheKey, np.ndarray] = OrderedDict()
        self._lock = threading.RLock()

    def get(self, key: SliceCacheKey) -> np.ndarray | None:
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
            return None

    def put(self, key: SliceCacheKey, data: np.ndarray) -> None:
        size_bytes = data.nbytes
        with self._lock:
            if key in self._cache:
                self._current_bytes -= self._cache[key].nbytes
                self._cache.move_to_end(key)
            
            while self._current_bytes + size_bytes > self._max_bytes and self._cache:
                k, evicted = self._cache.popitem(last=False)
                self._current_bytes -= evicted.nbytes
                
            self._cache[key] = data
            self._current_bytes += size_bytes
```

### 2.3 L2 VRAM Texture Cache (显存纹理缓存)
- **存储对象**：OpenGL 纹理对象 `GLuint` Handle / `QOpenGLTexture` / CuPy GPU Array Tensor。
- **容量控制**：显存 Byte Budget (如默认 256 MB)。单张 $2000 \times 2000$ RGBA 纹理约 16 MB，256 MB 约可保留 16 张常驻 VRAM 纹理。
- **生命周期**：**必须完全在 Qt OpenGL 渲染主线程中操作**。当 VRAM LRU 淘汰发生时，显式调用 `glDeleteTextures([tex_id])` 释放 GPU 显存，防止显存泄漏。
- **属性更新协同**：当用户切换 Colormap 或属性算法时，清空或失效对应的 L2 VRAM 缓存，但保留 L1 RAM 原始浮点切片，实现 O(1) 毫秒级 Color Re-mapping。

---

## 3. 线程池异步预加载队列与拖拽预判 (Thread Pool Async Preloader & Motion Prediction)

### 3.1 架构设计
构建 `SeismicPreloadManager`，内部使用带优先级的 `QThreadPool` / `concurrent.futures` 管理后台 I/O 任务。

```python
class PreloadPriority(IntEnum):
    P0_IMMEDIATE = 0  # 当前用户停留/选中的目标切片
    P1_DIRECTIONAL = 1 # 拖拽运动方向上的预测切片 (pos + 1, pos + 2...)
    P2_SYMMETRIC = 2   # 反方向对称切片 (pos - 1)
```

### 3.2 运动矢量预判算法 (Drag Velocity Prediction)
追踪切片滑动条的变更轨迹与时间戳，计算滑动速度 $v = \frac{\Delta pos}{\Delta t}$：
- 若 $v > 0$（正向滑动）：优先预加载切片序列 $[pos + 1, pos + 2, \dots, pos + K_{ahead}]$。
- 若 $v < 0$（反向滑动）：优先预加载切片序列 $[pos - 1, pos - 2, \dots, pos - K_{ahead}]$。
- 动态调整预读窗口 $K_{ahead}$：默认 $K_{ahead} = 3$。若 I/O 吞吐良好且 Cache 有余量，可自动拓展至 5。

```python
class DragTracker:
    def __init__(self):
        self.last_pos = 0
        self.last_time = time.monotonic()
        self.velocity = 0.0

    def update(self, pos: int) -> float:
        now = time.monotonic()
        dt = now - self.last_time
        if dt > 1e-3:
            self.velocity = (pos - self.last_pos) / dt
        self.last_pos = pos
        self.last_time = now
        return self.velocity
```

### 3.3 过期任务取消与背压控制 (Cancellation & Memory Backpressure)
1. **Generation Token**：每次拖拽开始或切片类型切换时，自增 `generation` 编号。后台工人在执行 `segyio` 读取前和读取后检查 `token.is_cancelled()`，若已失效则直接丢弃。
2. **内存背压 (Memory Backpressure)**：当 L1 RAM 缓存使用率达 90% 以上且磁盘 Read I/O 堵塞时，自动挂起 P1/P2 预读任务，仅保留 P0 当前切片请求，避免由于频繁预读触发连续 LRU 抖动。

---

## 4. `geoviz_seismic` 模块集成路线图

1. **`cache.py` 改造**：
   - 替换现有的 `SeismicCache` 为 `DualLevelSeismicCache`（包含 `RamSliceCache` 与 `VramTextureCache`）。
2. **`loader.py` 增强**：
   - 在 `SeismicLoader` 中提供非阻塞切片读取与 `cancellation_token` 探针检查支持。
3. **新增 `preloader.py`**：
   - 实现 `SeismicPreloadManager`、`TaskPriorityQueue` 与 `DragTracker`。
4. **`seismic_view.py` & `renderer_3d.py` 对接**：
   - 重构 `_apply_pending_slice()` 逻辑：
     1. 尝试 L2 VRAM 命中 -> 0ms 渲染。
     2. 尝试 L1 RAM 命中 -> 异步纹理上传 -> 渲染。
     3. 未命中 -> 触发 P0 异步 I/O 任务，并在 Profile 界面显示轻量级 Loading 占位符。
   - Slider 滑动事件关联 `DragTracker`，向 `PreloadManager` 发起 P1/P2 预读队列。

---

## 5. 预期性能提升 (Expected Performance Outcomes)

| 指标 | 现有方案 (Current) | 新架构方案 (Proposed) | 提升效果 |
| :--- | :--- | :--- | :--- |
| **切片重复访问延迟** | 10 ~ 80 ms (CPU 纹理上传) | **< 1 ms** (VRAM Texture Hit) | **10-80x 渲染加速** |
| **拖拽/切片滑动帧率** | 10 ~ 20 FPS (卡顿明显) | **60 FPS** (UI 主线程无阻塞 I/O) | **流畅无卡顿** |
| **内存安全性** | 无 Byte 限制 (高 OOM 风险) | **精确 Byte Budget 限制** (如 512MB RAM + 256MB VRAM) | **完全消除内存溢出风险** |
| **磁盘 I/O 利用率** | 低 (频繁阻塞与重复读取) | **高** (按拖拽方向预测预读 + 过期任务及时取消) | **减少 70%+ 无效 I/O** |
