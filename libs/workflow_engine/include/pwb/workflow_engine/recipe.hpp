// CONV-33 — workflow/recipe.py 契约冻结（轮1 签名桩；实装 = 轮2）。
//
// 可移植配方 *.paleo-workflow.json：WorkflowSpec 的序列化本体 + 元数据。
// 刻意不存任何执行事实（无密钥/令牌/绝对写路径/SQL/代码）——那些属于
// session/project/catalog。结构规则在 save 与 load 双端强制：夹带 API key、
// 查询或脚本的配方被拒绝，绝不静默携带（H4）。
//
// 生命周期：save（从 spec 或成功 run）→ load（迁移 + 结构校验）→ clone →
// rerun-with-new-inputs（槽位重绑定）→ diff → inspect。
//
// 落点裁决（33-decisions D2）：workflow_engine 新 TU —— 唯二仓内依赖 =
// workflow_spec model + validation（已字节级对齐）。time.time() 无 seam 的
// Python 直灌（L208/247/257）→ Clock 注入（store.hpp 先例）。
//
// 字节级纪律（E-3）：save 写出 json.dump(ensure_ascii=False, indent=1)
// 等价字节；原子写 `.tmp-recipe-` 前缀临时文件 + rename；后缀强改
// `.json` → `.paleo-workflow.json`（L160）。
#pragma once

#include <pwb/domain/json.hpp>
#include <pwb/workflow_spec/model.hpp>
#include <pwb/workflow_spec/validation.hpp>

#include <filesystem>
#include <functional>
#include <optional>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

namespace pwb::workflow_engine {

using domain::Json;
using Clock = std::function<double()>;  // epoch seconds（store.hpp 先例）

inline constexpr std::string_view kRecipeSchemaVersion = "1.0";
inline constexpr std::string_view kRecipeSuffix = ".paleo-workflow.json";

// recipe.RecipeError — 违反格式契约的 save/load 拒绝。
struct RecipeError : std::runtime_error {
    using std::runtime_error::runtime_error;
};

// recipe.RecipeDocument（L44）：元数据 + WorkflowSpec 本体。
struct RecipeDocument {
    std::string recipe_id;
    std::string name;
    workflow_spec::WorkflowSpec workflow;
    std::string description;
    std::optional<double> created_at;       // None → JSON null
    std::optional<std::string> source_run_id;
    std::vector<std::string> tags;
    std::string schema_version{kRecipeSchemaVersion};

    [[nodiscard]] Json to_dict() const;
    // migrate_recipe + WorkflowSpec::from_dict；版本未知 → RecipeError。
    [[nodiscard]] static RecipeDocument from_dict(const Json& data);
};

// ------------------------------------------------------------ security --

// structural_problems（L105）：格式契约违规（密钥/绝对路径/SQL/代码夹带）。
// 违规消息逐字冻结（": forbidden recipe key (" / "absolute path … — recipes
// are portable; use workspace-relative paths or slot bindings"）。
[[nodiscard]] std::vector<std::string> structural_problems(const Json& data);

// migrate_recipe（L114）：迁移到当前 schema 版本。v1 = 首版（恒等）；
// 未知未来版本 fail-closed 拒绝（绝不 best-effort 猜测）。
[[nodiscard]] Json migrate_recipe(const Json& data);

// validate_recipe（L135）：structural_problems + validate_workflow_spec。
[[nodiscard]] std::vector<std::string> validate_recipe(
    const RecipeDocument& recipe,
    const workflow_spec::ActionCatalog& registry);

// ------------------------------------------------------------ save/load --

struct SaveRecipeOptions {
    // null → 跳过 spec 校验（Python registry=None 分支）。
    const workflow_spec::ActionCatalog* registry = nullptr;
    // null → 墙钟（time.time() parity；oracle 冻结注入确定性时钟）。
    Clock clock = nullptr;
};

// save_recipe（L141）：结构安全门先于任何写出；原子写
// <name>.paleo-workflow.json。违规 → RecipeError（"; " 连接）。
[[nodiscard]] std::filesystem::path save_recipe(
    const RecipeDocument& recipe, std::filesystem::path path,
    const SaveRecipeOptions& options = {});

// load_recipe（L179）：读 + 迁移 + 结构校验。文件不存在 / JSON 损坏 /
// 结构违规 → RecipeError（消息逐字：does not exist / is not valid JSON）。
[[nodiscard]] RecipeDocument load_recipe(const std::filesystem::path& path);

// -------------------------------------------------- lifecycle helpers --

// recipe_from_spec（L196）：created_at = clock()。
[[nodiscard]] RecipeDocument recipe_from_spec(
    const workflow_spec::WorkflowSpec& workflow,
    const std::optional<std::string>& recipe_id = std::nullopt,
    const std::string& description = "",
    const std::vector<std::string>& tags = {},
    const Clock& clock = nullptr);

// recipe_from_run（L213）：成功 run 落配方 — run 的槽位值提升为该槽
// default（重跑只覆盖输入即可），source_run_id 记 lineage。
[[nodiscard]] RecipeDocument recipe_from_run(
    const workflow_spec::WorkflowRun& run,
    const std::vector<std::string>& tags = {},
    const Clock& clock = nullptr);

// clone_recipe（L253）：深拷贝 + 新身份（默认 "<id>-clone"），
// created_at = clock()，source_run_id 清空。
[[nodiscard]] RecipeDocument clone_recipe(
    const RecipeDocument& recipe,
    const std::optional<std::string>& new_recipe_id = std::nullopt,
    const Clock& clock = nullptr);

// diff_recipes（L262）：结构 diff（nodes/slots/params/max_concurrency），
// 供 inspect/review。键：nodes_added/nodes_removed/nodes_changed/
// slots_added/slots_removed/slots_changed/max_concurrency。
[[nodiscard]] Json diff_recipes(const RecipeDocument& a,
                                const RecipeDocument& b);

// inspect_recipe（L300）：人/agent 可读摘要（无执行事实）。
[[nodiscard]] Json inspect_recipe(const RecipeDocument& recipe);

}  // namespace pwb::workflow_engine
