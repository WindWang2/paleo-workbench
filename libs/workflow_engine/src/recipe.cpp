// CONV-33 轮1 契约桩 — recipe.hpp 声明面的 fail-loud 占位实现。
// 轮2（并行实现波）逐符号替换为 Python parity 实装 + oracle 冻结 replay；
// 桩绝不伪造行为：任何调用即刻失败并点名缺失实现。定义参数匿名
//（形参名以头文件声明为准）。
#include "pwb/workflow_engine/recipe.hpp"

#include <stdexcept>

namespace pwb::workflow_engine {
namespace {

[[noreturn]] void freeze_stub(const char* symbol) {
    throw std::logic_error(std::string("CONV-33 round-2 implements ") +
                           symbol + " (contract freeze stub)");
}

}  // namespace

Json RecipeDocument::to_dict() const {
    freeze_stub("RecipeDocument::to_dict");
}

RecipeDocument RecipeDocument::from_dict(const Json&) {
    freeze_stub("RecipeDocument::from_dict");
}

std::vector<std::string> structural_problems(const Json&) {
    freeze_stub("structural_problems");
}

Json migrate_recipe(const Json&) {
    freeze_stub("migrate_recipe");
}

std::vector<std::string> validate_recipe(const RecipeDocument&,
                                         const workflow_spec::ActionCatalog&) {
    freeze_stub("validate_recipe");
}

std::filesystem::path save_recipe(const RecipeDocument&,
                                  std::filesystem::path,
                                  const SaveRecipeOptions&) {
    freeze_stub("save_recipe");
}

RecipeDocument load_recipe(const std::filesystem::path&) {
    freeze_stub("load_recipe");
}

RecipeDocument recipe_from_spec(const workflow_spec::WorkflowSpec&,
                                const std::optional<std::string>&,
                                const std::string&,
                                const std::vector<std::string>&, const Clock&) {
    freeze_stub("recipe_from_spec");
}

RecipeDocument recipe_from_run(const workflow_spec::WorkflowRun&,
                               const std::vector<std::string>&, const Clock&) {
    freeze_stub("recipe_from_run");
}

RecipeDocument clone_recipe(const RecipeDocument&,
                            const std::optional<std::string>&, const Clock&) {
    freeze_stub("clone_recipe");
}

Json diff_recipes(const RecipeDocument&, const RecipeDocument&) {
    freeze_stub("diff_recipes");
}

Json inspect_recipe(const RecipeDocument&) {
    freeze_stub("inspect_recipe");
}

}  // namespace pwb::workflow_engine
