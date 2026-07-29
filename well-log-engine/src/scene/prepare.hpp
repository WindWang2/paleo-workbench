#pragma once

#include <welllog/scene/scene.hpp>

namespace welllog::detail {

class WELLLOG_SCENE_API ScenePreparer {
public:
  [[nodiscard]] static Result<PreparedScene>
  prepare(const WellLogDocument &document,
          const ScenePresentation &presentation) noexcept;
};

} // namespace welllog::detail
