#pragma once

// 05 线 — 跨页面共享井身份（viz_a 测井页 ↔ viz_b 连井页 ↔ 04 数据页）。
//
// 背景（findings.md 缺口 3）：本产品此前井身份 = 井名字符串原样，A 页
// 加载的 LAS 井与 B 页加载的连井列即便指向同一口井也无法互认（"W-1" 与
// "w-1 " 互不相等），跨工程重开后更无从对账。
//
// 设计（新增集成能力，非 Python 行为转换——诚实声明）：
//   * 身份键 = 井名规范化（去首尾空白、内部空白折叠为单空格、ASCII
//     casefold）。规范化规则是封闭集，见 well_identity_key()；
//   * well_id = 键的确定性 128 位 FNV-1a 十六进制（"wi-" 前缀）——同一
//     井名在任何进程/任何工程/任何页面得到同一 id，无需落库即可跨会话
//     稳定（重开可复现的验收即建立在此之上）；
//   * Registry 进程级、互斥保护：first-register-wins 语义（同键后续注册
//     幂等返回既有身份），origin 记录首次来源页面供结果来源显示。
//
// 线程模型：registry 注册/查询任意线程可用；WellIdentity 值类型可跨
// JobOutcome 传递。

#include <cstdint>
#include <mutex>
#include <optional>
#include <string>
#include <vector>

namespace pwb::ui_workers {

// 身份键：trim → 内部连续空白（空格/\t/\r/\n）折叠为单空格 → ASCII
// casefold。空/全空白名 → 空键（调用方不应以空键注册）。
[[nodiscard]] std::string well_identity_key(const std::string& name);

// 确定性身份 id：128 位 FNV-1a over 身份键，"wi-" + 32 位小写 hex。
[[nodiscard]] std::string well_identity_id(const std::string& identity_key);

struct WellIdentity {
    std::string well_id;    // 确定性 id（主键，跨会话稳定）
    std::string key;        // 规范化键
    std::string name;       // 首次注册时的显示名
    std::string origin;     // 首次注册来源（"well_log_page" / "cross_well" / …）
};

// 进程级注册表（互斥；first-register-wins）。产品代码经 viz_a/viz_b
// 安装点间接使用；04/06 线经 snapshot()/find() 只读消费。
class WellIdentityRegistry {
public:
    static WellIdentityRegistry& instance();

    // 以显示名注册（键取 well_identity_key(name)）；name 为空或键为空时
    // 返回 nullopt（诚实拒绝，不生成假身份）。
    std::optional<WellIdentity> register_well(const std::string& name,
                                              const std::string& origin);

    // 按规范化键查询。
    [[nodiscard]] std::optional<WellIdentity> find(
        const std::string& identity_key) const;

    // 按显示名查（先规范化再 find）。
    [[nodiscard]] std::optional<WellIdentity> find_by_name(
        const std::string& name) const;

    [[nodiscard]] std::vector<WellIdentity> snapshot() const;

    void clear_for_tests();

private:
    mutable std::mutex mutex_;
    std::vector<WellIdentity> entries_;
};

}  // namespace pwb::ui_workers
