#pragma once

#include <unordered_map>

#include <welllog/scene/curve_lod.hpp>
#include <welllog/scene/scene.hpp>

namespace welllog::detail {

class WELLLOG_SCENE_API ScenePreparer {
public:
  using CurveLodMap =
      std::unordered_map<EntityId, CurveLodPyramid, EntityIdHash>;

  [[nodiscard]] static Result<PreparedScene>
  prepare(const WellLogDocument &document,
          const ScenePresentation &presentation) noexcept;
  [[nodiscard]] static Result<PreparedScene>
  prepare(const WellLogDocument &document,
          const ScenePresentation &presentation, const CurveLodMap &curve_lods,
          const CurveLodQuery &query) noexcept;

private:
  [[nodiscard]] static Result<PreparedScene> prepare_impl(
      const WellLogDocument &document, const ScenePresentation &presentation,
      const CurveLodMap *curve_lods, const CurveLodQuery *query) noexcept;
};

} // namespace welllog::detail
