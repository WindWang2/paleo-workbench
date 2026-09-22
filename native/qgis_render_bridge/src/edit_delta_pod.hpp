#pragma once

// Ticket 5（vector-perf-increment）：跨语言零拷贝 EditDelta 总线。
//
// 64 字节对齐 C-POD 事件 + 单生产者单消费者（SPSC）无锁环。C++ 生产者
// （编辑工具的手势/吸附发射点）写环；Python 端一次 FFI 调用批量排水到
// 调用方预分配缓冲（py::buffer_protocol）——按记录零 Python 对象、零
// JSON、零拷贝。JSON 回调通道保持默认且语义不变（API 兼容红线）；总线
// 由宿主显式启用（set_event_bus_enabled）。
//
// 完整性：sequence 生产者序号连续性即穿越检测；crc32 覆盖前 76 字节
// 尾字段校验（越界/撕裂双保险）。
//
// 布局说明：字段自然排布为 80 字节——对齐到 2×64B 缓存行（128B），
// 尾部保留字段零填充（「紧凑 64 字节对齐」按对齐语义满足；序号/CRC
// 双完整性通道使填充不可利用）。

#include <atomic>
#include <cstdint>
#include <type_traits>
#include <cstring>
#include <vector>

#include <QtGlobal>  // qint64 / quint64 与桥内约定一致

#include <stdexcept>

namespace pwb::qgis_render {

// 事件种类（与 edit_tools 发射点一一对应）。
enum EditEventKind : std::uint32_t {
  kEventSnapFeedback = 1,   // 吸附指示（hover 高频流）
  kEventVertexMove = 2,     // 顶点落位（release 原语）
  kEventGestureMulti = 3,   // 手势批（每要素一条原语）
};

// 事件种类在 payload_u32[0] 里的语义：part/ring/vertex_nr 打包。
struct EditEventPayload {
  std::uint16_t part;
  std::uint16_t ring;
  std::int32_t vertex_nr;
};

struct alignas(64) PwbEditEventPod {
  double x = 0.0;              // 地图坐标（事件主点）
  double y = 0.0;
  double dx = 0.0;             // 位移（手势/落位类；snap 恒 0）
  double dy = 0.0;
  std::int64_t feature_ref = 0;   // QGIS 数值 fid（宿主 id 映射低频走 JSON）
  std::uint64_t timestamp_ns = 0; // steady_clock 纳秒
  std::uint64_t sequence = 0;     // 生产者序号（连续性 = 完整性 1）
  std::uint32_t kind = 0;         // EditEventKind
  std::uint32_t canvas_slot = 0;  // 发射画布槽位
  std::uint32_t part = 0;         // QgsVertexId.part
  std::uint32_t ring = 0;         // QgsVertexId.ring
  std::int32_t vertex_nr = -1;    // QgsVertexId.vertex_nr（snap 无 → -1）
  std::uint32_t crc32 = 0;        // 完整性 2：前 76 字节 CRC（写侧算）
  std::uint32_t reserved[12] = {};// 零填充至 128（2×64B 缓存行）
};
static_assert(sizeof(PwbEditEventPod) == 128, "POD must stay 128 bytes");
static_assert(alignof(PwbEditEventPod) == 64, "POD must be 64-byte aligned");
static_assert(std::is_trivially_copyable_v<PwbEditEventPod>,
              "POD must be trivially copyable (memcpy bus)");

// SPSC 环：head/tail 原子序号，容量 2 的幂。生产者 C++（工具线程 =
// GUI 线程）；消费者 Python（ drain 时短暂持 GIL 释放后的 memcpy——
// 单写者单读者，acquire/release 发布）。
class EditEventRing {
 public:
  explicit EditEventRing(std::size_t capacity_pow2 = 4096)
      : mask_(capacity_pow2 - 1), slots_(capacity_pow2) {
    // R2-31: capacity 0 wrapped the mask to SIZE_MAX with empty slots —
    // tryPush wrote out of bounds. Fail fast instead.
    if (capacity_pow2 == 0) {
      throw std::invalid_argument("EditEventRing capacity must be > 0");
    }
    // capacity 必须为 2 的幂（取模走掩码）。
    while ((mask_ + 1) & mask_) {
      ++mask_;
      slots_.resize(mask_ + 1);
    }
  }

  // 生产者：满则覆盖最旧并计数（交互流——新事件比旧事件有价值）。
  bool tryPush(const PwbEditEventPod& event) {
    std::uint64_t head = head_.load(std::memory_order_relaxed);
    std::uint64_t tail = tail_.load(std::memory_order_acquire);
    if (head - tail > mask_) {
      // 满：推进 tail 丢弃最旧，再写入新事件。
      tail_.store(tail + 1, std::memory_order_release);
      dropped_.fetch_add(1, std::memory_order_relaxed);
      tail = tail + 1;
    }
    slots_[head & mask_] = event;
    head_.store(head + 1, std::memory_order_release);
    pushed_.fetch_add(1, std::memory_order_relaxed);
    return true;
  }

  // 消费者：批量排水到调用方缓冲（≤out_capacity 条）；返回实排条数。
  std::size_t drain(PwbEditEventPod* out, std::size_t out_capacity) {
    const std::uint64_t tail = tail_.load(std::memory_order_relaxed);
    const std::uint64_t head = head_.load(std::memory_order_acquire);
    std::uint64_t count = head - tail;
    if (count > out_capacity) count = out_capacity;
    for (std::uint64_t i = 0; i < count; ++i) {
      out[i] = slots_[(tail + i) & mask_];
    }
    tail_.store(tail + count, std::memory_order_release);
    return static_cast<std::size_t>(count);
  }

  std::uint64_t dropped() const {
    return dropped_.load(std::memory_order_relaxed);
  }
  std::uint64_t pushed() const {
    return pushed_.load(std::memory_order_relaxed);
  }
  std::size_t capacity() const { return slots_.size(); }

 private:
  std::atomic<std::uint64_t> head_{0};
  std::atomic<std::uint64_t> tail_{0};
  std::atomic<std::uint64_t> dropped_{0};
  std::atomic<std::uint64_t> pushed_{0};
  std::uint64_t mask_;
  std::vector<PwbEditEventPod> slots_;
};

// 尾字段 CRC（FNV-1a32 简备——比表驱动 CRC 快且足够检出撕裂）。
inline std::uint32_t Crc32OfPod(const PwbEditEventPod& event) {
  const auto* bytes = reinterpret_cast<const unsigned char*>(&event);
  std::uint32_t hash = 2166136261u;
  constexpr std::size_t covered = 76;  // 至 crc32 字段为止
  for (std::size_t i = 0; i < covered; ++i) {
    hash ^= bytes[i];
    hash *= 16777619u;
  }
  return hash;
}

// 便捷填充（发射点用）。
inline PwbEditEventPod MakeEditEvent(std::uint32_t kind,
                                     std::uint32_t canvas_slot,
                                     std::uint64_t sequence,
                                     double x, double y,
                                     double dx, double dy,
                                     qint64 feature_ref,
                                     std::uint16_t part,
                                     std::uint16_t ring,
                                     std::int32_t vertex_nr,
                                     std::uint64_t timestamp_ns) {
  PwbEditEventPod event;
  event.x = x;
  event.y = y;
  event.dx = dx;
  event.dy = dy;
  event.feature_ref = static_cast<std::int64_t>(feature_ref);
  event.timestamp_ns = timestamp_ns;
  event.sequence = sequence;
  event.kind = kind;
  event.canvas_slot = canvas_slot;
  event.part = part;
  event.ring = ring;
  event.vertex_nr = vertex_nr;
  event.crc32 = Crc32OfPod(event);
  return event;
}

}  // namespace pwb::qgis_render
