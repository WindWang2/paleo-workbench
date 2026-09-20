// Plugin-side error-envelope storage (see plugin_module.hpp). Kept as a
// standalone translation unit linked into plugin MODULEs on its own
// (pwb_plugin_glue): the glue needs only Pwb::Domain, so a third-party
// module never has to link the mapping kernels the built-in providers drag
// in — a shared object linking non-PIC static archives fails to link.
#include <pwb/providers/plugin_module.hpp>

namespace pwb::providers::plugin {

using pwb::domain::Json;

// Error-envelope storage shared with plugin_module.hpp (plugin side).
// Thread-local: the host reads the buffer on the same thread execute() ran
// in, and each module gets its own copy of this storage.
std::string& module_error_buffer() {
    static thread_local std::string buffer;
    return buffer;
}

void set_plugin_error(const std::string& kind, const std::string& message) {
    module_error_buffer() = "{\"kind\": \"" + kind + "\", \"message\": " +
                            Json(message).dump() + "}";
}

}  // namespace pwb::providers::plugin
