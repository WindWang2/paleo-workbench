// Save-As artifact relocation (conv-26) — see relocation.hpp. Mirrors
// paleo_workbench/project/paths.py branch-for-branch.
#include "pwb/project/relocation.hpp"

#include "pwb/project/paths.hpp"

#include <cstring>
#include <system_error>

namespace pwb::project {

namespace {

std::error_code remove_readonly_and_retry(const fs::path& path) {
    std::error_code ec;
    fs::remove_all(path, ec);
    if (ec) {
        // Clear read-only flags where possible and retry once (#1190: a
        // swallowed failure here reported success while entries remained).
        std::error_code perm;
        fs::permissions(path, fs::perms::owner_write,
                        fs::perm_options::add, perm);
        fs::remove_all(path, ec);
    }
    return ec;
}

}  // namespace

bool safe_rmtree(const fs::path& path) {
    std::error_code ec;
    if (!fs::exists(path, ec) && !fs::is_symlink(path, ec)) return true;
    std::error_code first = remove_readonly_and_retry(path);
    if (first) {
        // Second, unconditional attempt: report "gone", not "probably".
        fs::remove_all(path, ec);
    }
    return !fs::exists(path, ec) && !fs::is_symlink(path, ec);
}

StagedArtifactRelocation::StagedArtifactRelocation(fs::path source,
                                                   fs::path target)
    : source_(std::move(source)), target_(std::move(target)) {}

bool StagedArtifactRelocation::staged() const {
    return moved_root_ || copied_root_ || preserved_source_ ||
           !moved_children_.empty();
}

bool StagedArtifactRelocation::commit() {
    if (!(copied_root_ || preserved_source_)) return true;
    return safe_rmtree(source_);
}

bool StagedArtifactRelocation::rollback() {
    bool ok = true;
    if (moved_root_) {
        std::error_code ec;
        if (fs::exists(target_, ec) && !fs::exists(source_, ec)) {
            fs::rename(target_, source_, ec);
            if (ec) ok = false;
        }
    } else if ((copied_root_ || preserved_source_) && fs::exists(target_)) {
        if (!safe_rmtree(target_)) ok = false;
    }
    for (auto it = moved_children_.rbegin(); it != moved_children_.rend();
         ++it) {
        std::error_code ec;
        if (fs::exists(it->second, ec) && !fs::exists(it->first, ec)) {
            fs::rename(it->second, it->first, ec);
            if (ec) ok = false;
        }
    }
    if (!moved_children_.empty()) {
        std::error_code ec;
        fs::remove(target_, ec);  // only succeeds when emptied by the moves
    }
    return ok;
}

domain::Result<StagedArtifactRelocation> StagedArtifactRelocation::stage(
    const fs::path& old_project_path, const fs::path& new_project_path) {
    fs::path source = artifact_dir_for(old_project_path);
    fs::path target = artifact_dir_for(new_project_path);
    StagedArtifactRelocation staged(source, target);
    std::error_code ec;
    if (source == target || !fs::is_directory(source, ec) || ec) {
        return domain::Result<StagedArtifactRelocation>(std::move(staged));
    }
    if (!fs::exists(target, ec)) {
        std::error_code copy_ec;
        // shutil.copytree parity: the target's parents come along.
        fs::create_directories(target.parent_path(), copy_ec);
        if (!copy_ec) {
            fs::copy(source, target, fs::copy_options::recursive, copy_ec);
        }
        if (copy_ec) {
            fs::path target_check = target;
            if (fs::exists(target_check, ec) &&
                !safe_rmtree(target_check)) {
                // cleanup failed — surface alongside the original error
            }
            return domain::DataError(domain::ErrorCode::IoError,
                                     "staged relocation copy failed: " +
                                         copy_ec.message());
        }
        staged.preserved_source_ = true;
        return domain::Result<StagedArtifactRelocation>(std::move(staged));
    }
    // Existing target root: merge only the direct children it lacks;
    // conflicting children are left untouched (both sides hold data that
    // must not be overwritten).
    for (const auto& child : fs::directory_iterator(source, ec)) {
        fs::path destination = target / child.path().filename();
        std::error_code exists_ec;
        if (fs::exists(destination, exists_ec) || exists_ec) continue;
        std::error_code rename_ec;
        fs::rename(child.path(), destination, rename_ec);
        if (rename_ec) {
            staged.rollback();
            return domain::DataError(domain::ErrorCode::IoError,
                                     "staged relocation merge failed: " +
                                         rename_ec.message());
        }
        staged.moved_children_.emplace_back(child.path(), destination);
    }
    if (ec) {
        staged.rollback();
        return domain::DataError(domain::ErrorCode::IoError,
                                 "staged relocation scan failed: " +
                                     ec.message());
    }
    return domain::Result<StagedArtifactRelocation>(std::move(staged));
}

bool relocate_artifacts(const fs::path& old_project_path,
                        const fs::path& new_project_path) {
    auto staged = StagedArtifactRelocation::stage(old_project_path,
                                                  new_project_path);
    if (!staged.is_ok()) return false;
    staged.value().commit();
    return staged.value().staged();
}

std::optional<std::string> rebase_owned_artifact_path(
    const std::string& raw, const fs::path& old_root, const fs::path& new_root,
    const std::optional<fs::path>& project_dir) {
    if (raw.empty()) return std::nullopt;
    std::vector<fs::path> candidates{fs::path(raw)};
    std::error_code ec;
    if (project_dir.has_value() && !fs::path(raw).is_absolute()) {
        candidates.push_back(*project_dir / fs::path(raw));
    }
    for (const fs::path& candidate : candidates) {
        fs::path resolved = fs::weakly_canonical(candidate, ec);
        if (ec || resolved.empty()) continue;
        if (is_within_directory(resolved, old_root)) {
            std::error_code rel_ec;
            const fs::path relative = fs::relative(resolved, old_root, rel_ec);
            if (rel_ec || relative.empty() ||
                (*relative.begin()) == "..") {
                continue;
            }
            return (new_root / relative).generic_string();
        }
    }
    const std::string posix = fs::path(raw).generic_string();
    const std::string old_name = old_root.filename().string();
    const std::string new_name = new_root.filename().string();
    const std::string prefix = old_name + "/";
    const std::string artifacts_suffix = ".artifacts";
    if (posix.rfind(prefix, 0) == 0 &&
        old_name.size() > artifacts_suffix.size() &&
        old_name.substr(old_name.size() - artifacts_suffix.size()) ==
            artifacts_suffix) {
        return new_name + "/" + posix.substr(prefix.size());
    }
    return std::nullopt;
}

int rebase_project_artifact_paths(domain::Json& document_root,
                                  const fs::path& old_project_path,
                                  const fs::path& new_project_path) {
    std::error_code ec;
    const fs::path old_root = fs::weakly_canonical(
        artifact_dir_for(old_project_path), ec);
    const fs::path new_root = artifact_dir_for(new_project_path);
    const fs::path old_dir = fs::weakly_canonical(
        old_project_path.parent_path(), ec);
    int rebased = 0;
    auto rebase_section = [&](const char* key, const char* field) {
        auto section = document_root.find(key);
        if (section == document_root.end() || !section->is_array()) return;
        for (auto& node : *section) {
            if (!node.is_object()) continue;
            auto raw = node.find(field);
            if (raw == node.end() || !raw->is_string()) continue;
            const std::string value = raw->get<std::string>();
            if (value.empty()) continue;
            if (auto rewritten = rebase_owned_artifact_path(
                    value, old_root, new_root, old_dir)) {
                if (*rewritten != value) {
                    node[field] = *rewritten;
                    ++rebased;
                }
            }
        }
    };
    rebase_section("factor_map_tasks", "grid_artifact_path");
    rebase_section("horizon_interpretations", "artifact_path");
    rebase_section("correlation_interpretations", "artifact_path");
    rebase_section("fault_interpretations", "artifact_path");
    return rebased;
}

}  // namespace pwb::project
