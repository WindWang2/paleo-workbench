#include <pwb/ui_pages_preview/url_filter.hpp>

namespace pwb::ui_pages_preview {

bool local_scheme_allowed(const std::string& scheme) {
    return scheme == "file" || scheme == "data" || scheme == "about" ||
           scheme == "blob";
}

bool resource_scheme_allowed(const std::string& scheme) {
    return scheme.empty() || scheme == "file";
}

}  // namespace pwb::ui_pages_preview
