#include <pwb/ui_wellseis/resource_sources.hpp>

#include <algorithm>
#include <cctype>

namespace pwb::ui_wellseis {

namespace {

std::string ascii_lower(std::string value) {
    for (char& c : value) {
        c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    }
    return value;
}

std::string ascii_upper(std::string value) {
    for (char& c : value) {
        c = static_cast<char>(std::toupper(static_cast<unsigned char>(c)));
    }
    return value;
}

bool ends_with(const std::string& text, const std::string& suffix) {
    return text.size() >= suffix.size() &&
           text.compare(text.size() - suffix.size(), suffix.size(), suffix) ==
               0;
}

}  // namespace

bool is_segy_resource(const ResourceSlice& resource) {
    if (resource.type != "seismic") {
        return false;
    }
    const std::string format = ascii_lower(resource.format);
    const std::string path = ascii_lower(resource.path);
    return format == "sgy" || format == "segy" ||
           ends_with(path, ".sgy") || ends_with(path, ".segy");
}

bool is_well_log_resource(const ResourceSlice& resource) {
    return resource.type == "well_log";
}

std::string resource_combo_label(const ResourceSlice& resource,
                                 const std::string& unnamed_fallback) {
    const std::string name =
        resource.name.empty() ? unnamed_fallback : resource.name;
    const std::string format = ascii_upper(resource.format);
    if (format.empty()) {
        return name;
    }
    return name + " · " + format;
}

std::vector<SourceComboEntry> source_combo_entries(
    const std::vector<ResourceSlice>& resources,
    const std::string& unnamed_fallback,
    const std::string& placeholder_when_empty) {
    std::vector<SourceComboEntry> entries;
    entries.reserve(resources.size() + 1);
    for (const ResourceSlice& resource : resources) {
        entries.push_back(
            {resource_combo_label(resource, unnamed_fallback), resource.id});
    }
    if (entries.empty() && !placeholder_when_empty.empty()) {
        entries.push_back({placeholder_when_empty, ""});
    }
    return entries;
}

int resolved_source_index(const std::vector<ResourceSlice>& resources,
                          const std::string& previous_resource_id) {
    if (previous_resource_id.empty()) {
        return -1;
    }
    for (std::size_t i = 0; i < resources.size(); ++i) {
        if (resources[i].id == previous_resource_id) {
            return static_cast<int>(i);
        }
    }
    return -1;
}

SourceSignature source_signature(
    const std::vector<SourceComboEntry>& entries) {
    SourceSignature signature;
    signature.reserve(entries.size());
    for (const SourceComboEntry& entry : entries) {
        signature.emplace_back(entry.label, entry.resource_id);
    }
    return signature;
}

const ResourceSlice* find_resource(
    const std::vector<ResourceSlice>& resources,
    const std::string& resource_id) {
    if (resource_id.empty()) {
        return nullptr;
    }
    for (const ResourceSlice& resource : resources) {
        if (resource.id == resource_id) {
            return &resource;
        }
    }
    return nullptr;
}

const ResourceSlice* primary_resource(
    const std::map<std::string, std::vector<std::string>>& input_refs,
    const std::string& key,
    const std::vector<ResourceSlice>& resources) {
    const auto it = input_refs.find(key);
    if (it == input_refs.end() || it->second.empty()) {
        return nullptr;
    }
    return find_resource(resources, it->second.front());
}

}  // namespace pwb::ui_wellseis
