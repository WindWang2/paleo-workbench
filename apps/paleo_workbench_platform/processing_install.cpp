// processing_install — see processing_install.hpp. The QGIS->closure_agent
// vocabulary conversion lives here so neither library depends on the
// other: qgis_processing supplies the registry truth, closure_agent
// consumes plain structs.

#include "processing_install.hpp"

#include <algorithm>

#include <QStringList>

#include <pwb/qgis_processing/runner.hpp>

#ifdef PWB_WITH_CLOSURE_AGENT
#include <pwb/closure_agent/registry.hpp>
#endif

namespace pwb::app {

std::vector<ProcessingToolInfo> paleo_processing_tool_infos() {
    std::vector<ProcessingToolInfo> infos;
    const QList<pwb::qgis_processing::PaleoAlgorithmInfo> registry_infos =
        pwb::qgis_processing::paleo_algorithm_infos();
    infos.reserve(static_cast<std::size_t>(registry_infos.size()));
    for (const pwb::qgis_processing::PaleoAlgorithmInfo& info :
         registry_infos) {
        infos.push_back({info.id.toStdString(),
                         info.display_name.toStdString(),
                         info.group_id.toStdString()});
    }
    std::sort(infos.begin(), infos.end(),
              [](const ProcessingToolInfo& a, const ProcessingToolInfo& b) {
                  return a.id < b.id;
              });
    return infos;
}

#ifdef PWB_WITH_CLOSURE_AGENT
std::size_t register_paleo_agent_actions(
    pwb::closure_agent::ActionRegistry& registry) {
    std::vector<pwb::closure_agent::AlgorithmToolInfo> tools;
    for (const ProcessingToolInfo& info : paleo_processing_tool_infos()) {
        tools.push_back({info.id, info.display, info.group});
    }
    std::size_t registered = 0;
    for (pwb::closure_agent::ActionSpec& spec :
         pwb::closure_agent::processing_algorithm_specs(tools)) {
        registry.register_spec(spec, /*replace=*/true);
        ++registered;
    }
    return registered;
}
#endif

}  // namespace pwb::app
