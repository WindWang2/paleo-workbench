#include "pwb/catalog/tags.hpp"
#include "pwb/catalog/entity_view.hpp"

#include <algorithm>

namespace pwb::catalog {

namespace {
domain::DataError catalog_error(const std::string& message) {
    return domain::DataError(domain::ErrorCode::InvalidArgument, message);
}
}  // namespace

// The #1182 lazy rollback journal, over the vector-of-pairs association
// representation: prior slices restored in place, removed tags re-inserted
// at their recorded positions, created tags un-appended.
class TagStore::Journal {
public:
    explicit Journal(CatalogDocument* document) : document_(document) {}

    void record_association(char side, const std::string& owner) {
        auto key = std::make_pair(side, owner);
        if (captured_.count(key)) return;  // first capture wins
        std::vector<std::pair<std::string, std::string>>& rows =
            side == 'a' ? document_->asset_tags : document_->version_tags;
        captured_.emplace(key, rows);  // full prior slice (Python: prior list)
    }

    void record_tag_field(const Tag* tag, bool display) {
        field_history_.push_back({const_cast<Tag*>(tag), display, display ? tag->display_name : std::optional<std::string>(), tag->name});
    }

    void record_tag_removed(const Tag* tag) {
        // Record the position the tag occupies in the ORIGINAL tags vector
        // at this removal (Python captured document.tags.index(tag) live).
        int index = 0;
        for (const auto& candidate : document_->tags) {
            if (&candidate == tag) break;
            ++index;
        }
        removed_.push_back({index, *tag});
    }

    void record_tag_created(const Tag* tag) { created_.push_back(tag); }

    void drop_empty_keys() {
        // Vector representation never keeps empty owner blocks — no-op
        // (recorded for journal parity only).
    }

    void rollback() {
        for (auto it = field_history_.rbegin(); it != field_history_.rend(); ++it) {
            if (it->display) it->tag->display_name = it->prior_display;
            else it->tag->name = it->prior_name;
        }
        for (auto it = removed_.rbegin(); it != removed_.rend(); ++it) {
            if (static_cast<int>(document_->tags.size()) <= it->first) {
                document_->tags.push_back(it->second);
            } else {
                document_->tags.insert(document_->tags.begin() + it->first,
                                       it->second);
            }
        }
        for (auto it = created_.rbegin(); it != created_.rend(); ++it) {
            for (auto candidate = document_->tags.begin();
                 candidate != document_->tags.end(); ++candidate) {
                if (&*candidate == *it) {
                    document_->tags.erase(candidate);
                    break;
                }
            }
        }
        for (const auto& [key, prior] : slices_) {
            auto& rows = key.first == 'a' ? document_->asset_tags
                                          : document_->version_tags;
            rows = prior;
        }
    }

    // Commit the journal: promote captured slices to rollback-able state.
    void commit() {
        for (const auto& [key, prior] : captured_) {
            slices_.emplace_back(key, prior);
        }
        captured_.clear();
    }

private:
    struct FieldChange {
        Tag* tag;
        bool display;
        std::optional<std::string> prior_display;
        std::string prior_name;
    };
    CatalogDocument* document_;
    std::map<std::pair<char, std::string>,
             std::vector<std::pair<std::string, std::string>>>
        captured_;
    std::vector<std::pair<std::pair<char, std::string>,
                          std::vector<std::pair<std::string, std::string>>>>
        slices_;
    std::vector<std::pair<int, Tag>> removed_;
    std::vector<const Tag*> created_;
    std::vector<FieldChange> field_history_;
};

const Tag* TagStore::tag_by_name(const std::string& normalized) const {
    for (const auto& tag : document_->tags) {
        if (tag.name == normalized) return &tag;
    }
    return nullptr;
}

Tag* TagStore::tag_by_name_mut(const std::string& normalized) {
    for (auto& tag : document_->tags) {
        if (tag.name == normalized) return &tag;
    }
    return nullptr;
}

std::string TagStore::display_of(const std::string& raw) {
    // Python " ".join(str(name).split()).
    std::string out;
    bool pending = false;
    for (char c : raw) {
        if (std::isspace(static_cast<unsigned char>(c))) {
            pending = !out.empty();
        } else {
            if (pending) out.push_back(' ');
            pending = false;
            out.push_back(c);
        }
    }
    return out;
}

domain::DataError TagStore::save_or_rollback(Journal& journal) {
    journal.commit();
    domain::DataError error = save_ ? save_() : domain::DataError(domain::ErrorCode::Ok, "");
    if (!error.ok()) journal.rollback();
    return error;
}

domain::Result<Tag> TagStore::add_tag(const std::string& name,
                                      const std::optional<std::string>& asset_id,
                                      const std::optional<std::string>& version_id) {
    if (!asset_id.has_value() && !version_id.has_value()) {
        return catalog_error("add_tag requires asset_id or version_id");
    }
    const std::string normalized = normalize_tag_name(name);
    if (normalized.empty()) {
        return catalog_error("Empty tag name");
    }
    if (asset_id.has_value() && document_->find_asset(domain::AssetId(*asset_id)) == nullptr) {
        return catalog_error("Unknown asset: " + *asset_id);
    }
    if (version_id.has_value() &&
        document_->find_version(domain::VersionId(*version_id)) == nullptr) {
        return catalog_error("Unknown version: " + *version_id);
    }
    bool created = false;
    Tag* tag = tag_by_name_mut(normalized);
    if (tag == nullptr) {
        document_->tags.push_back(Tag{new_ref_id("tag"), normalized,
                                      display_of(name), domain::Json::object()});
        tag = &document_->tags.back();
        created = true;
    }
    Journal journal(document_);
    if (created) journal.record_tag_created(tag);
    bool changed = false;
    auto associate = [&](std::vector<std::pair<std::string, std::string>>& rows,
                         const std::optional<std::string>& owner, char side) {
        if (!owner.has_value()) return;
        for (const auto& [key, tag_id] : rows) {
            if (key == *owner && tag_id == tag->id) return;  // present
        }
        journal.record_association(side, *owner);
        rows.emplace_back(*owner, tag->id);
        changed = true;
    };
    associate(document_->asset_tags, asset_id, 'a');
    associate(document_->version_tags, version_id, 'v');
    if (created || changed) {
        domain::DataError error = save_or_rollback(journal);
        if (!error.ok()) return error;
    }
    return *tag;
}

domain::DataError TagStore::remove_tag(const std::string& name,
                                       const std::optional<std::string>& asset_id,
                                       const std::optional<std::string>& version_id) {
    const std::string normalized = normalize_tag_name(name);
    const Tag* tag = tag_by_name(normalized);
    if (tag == nullptr) return domain::DataError(domain::ErrorCode::Ok, "");
    Journal journal(document_);
    bool changed = false;
    auto disassociate = [&](std::vector<std::pair<std::string, std::string>>& rows,
                            const std::optional<std::string>& owner) {
        if (!owner.has_value()) return;
        journal.record_association(rows == document_->asset_tags ? 'a' : 'v', *owner);
        auto kept = std::remove_if(rows.begin(), rows.end(),
                                   [&](const std::pair<std::string, std::string>& row) {
                                       return row.first == *owner &&
                                              row.second == tag->id;
                                   });
        if (kept != rows.end()) {
            rows.erase(kept, rows.end());
            changed = true;
        }
    };
    disassociate(document_->asset_tags, asset_id);
    disassociate(document_->version_tags, version_id);
    if (changed) {
        journal.drop_empty_keys();
        return save_or_rollback(journal);
    }
    return domain::DataError(domain::ErrorCode::Ok, "");
}

domain::Result<Tag> TagStore::rename_tag(const std::string& old_name,
                                         const std::string& new_name,
                                         const std::string& on_collision) {
    const std::string normalized_old = normalize_tag_name(old_name);
    Tag* tag = tag_by_name_mut(normalized_old);
    if (tag == nullptr) {
        return catalog_error("Unknown tag: " + old_name);
    }
    const std::string normalized_new = normalize_tag_name(new_name);
    if (normalized_new.empty()) {
        return catalog_error("Empty tag name");
    }
    Tag* existing = tag_by_name_mut(normalized_new);
    if (existing != nullptr && existing == tag) {
        // Same tag: display-name refresh only.
        Journal journal(document_);
        journal.record_tag_field(tag, /*display=*/true);
        tag->display_name = display_of(new_name);
        domain::DataError error = save_or_rollback(journal);
        if (!error.ok()) return error;
        return *tag;
    }
    if (existing != nullptr) {
        if (on_collision == "error") {
            return catalog_error("Tag '" + normalized_new +
                                 "' already exists; rename would merge");
        }
        return merge_tags(old_name, new_name);
    }
    Journal journal(document_);
    journal.record_tag_field(tag, /*display=*/true);
    journal.record_tag_field(tag, /*display=*/false);
    tag->name = normalized_new;
    tag->display_name = display_of(new_name);
    domain::DataError error = save_or_rollback(journal);
    if (!error.ok()) return error;
    return *tag;
}

domain::Result<Tag> TagStore::merge_tags(const std::string& source_name,
                                         const std::string& target_name) {
    const std::string normalized_source = normalize_tag_name(source_name);
    Tag* source = tag_by_name_mut(normalized_source);
    if (source == nullptr) {
        return catalog_error("Unknown tag: " + source_name);
    }
    const std::string normalized_target = normalize_tag_name(target_name);
    Tag* target = tag_by_name_mut(normalized_target);
    if (target == nullptr) {
        return catalog_error("Unknown tag: " + target_name);
    }
    if (source == target) return *target;

    Journal journal(document_);
    auto re_point = [&](std::vector<std::pair<std::string, std::string>>& rows,
                        char side) {
        // Per-owner semantics: drop source associations, append target at
        // the end of the owner's block when not already present.
        std::vector<std::string> touched_owners;
        for (const auto& [owner, tag_id] : rows) {
            if (tag_id == source->id) touched_owners.push_back(owner);
        }
        for (const auto& owner : touched_owners) {
            journal.record_association(side, owner);
        }
        if (touched_owners.empty()) return;
        auto kept = std::remove_if(rows.begin(), rows.end(),
                                   [&](const std::pair<std::string, std::string>& row) {
                                       return row.second == source->id;
                                   });
        rows.erase(kept, rows.end());
        for (const auto& owner : touched_owners) {
            bool has_target = false;
            for (const auto& [key, tag_id] : rows) {
                if (key == owner && tag_id == target->id) has_target = true;
            }
            if (!has_target) {
                // Insert at the end of the owner's remaining block (or the
                // end of the vector when the block vanished).
                std::size_t insert_at = rows.size();
                for (std::size_t i = 0; i < rows.size(); ++i) {
                    if (rows[i].first == owner) insert_at = i + 1;
                }
                rows.insert(rows.begin() + static_cast<std::ptrdiff_t>(insert_at),
                            {owner, target->id});
            }
        }
    };
    re_point(document_->asset_tags, 'a');
    re_point(document_->version_tags, 'v');
    for (auto it = document_->tags.begin(); it != document_->tags.end(); ++it) {
        if (&*it == source) {
            journal.record_tag_removed(source);
            document_->tags.erase(it);
            break;
        }
    }
    journal.drop_empty_keys();
    domain::DataError error = save_or_rollback(journal);
    if (!error.ok()) return error;
    return *target;
}

domain::Result<Tag> TagStore::create_tag(const std::string& name) {
    const std::string normalized = normalize_tag_name(name);
    if (normalized.empty()) {
        return catalog_error("Empty tag name");
    }
    Tag* existing = tag_by_name_mut(normalized);
    if (existing != nullptr) return *existing;
    document_->tags.push_back(Tag{new_ref_id("tag"), normalized,
                                  display_of(name), domain::Json::object()});
    Tag* tag = &document_->tags.back();
    Journal journal(document_);
    journal.record_tag_created(tag);
    domain::DataError error = save_or_rollback(journal);
    if (!error.ok()) return error;
    return *tag;
}

domain::Result<Tag> TagStore::bulk_add_tag(
    const std::string& name, const std::vector<std::string>& asset_ids,
    const std::vector<std::string>& version_ids) {
    if (asset_ids.empty() && version_ids.empty()) {
        return catalog_error("bulk_add_tag requires asset_ids or version_ids");
    }
    const std::string normalized = normalize_tag_name(name);
    if (normalized.empty()) {
        return catalog_error("Empty tag name");
    }
    for (const auto& asset_id : asset_ids) {
        if (document_->find_asset(domain::AssetId(asset_id)) == nullptr) {
            return catalog_error("Unknown asset: " + asset_id);
        }
    }
    for (const auto& version_id : version_ids) {
        if (document_->find_version(domain::VersionId(version_id)) == nullptr) {
            return catalog_error("Unknown version: " + version_id);
        }
    }
    Journal journal(document_);
    bool created = false;
    Tag* tag = tag_by_name_mut(normalized);
    if (tag == nullptr) {
        document_->tags.push_back(Tag{new_ref_id("tag"), normalized,
                                      display_of(name), domain::Json::object()});
        tag = &document_->tags.back();
        journal.record_tag_created(tag);
        created = true;
    }
    bool changed = created;
    auto associate = [&](std::vector<std::pair<std::string, std::string>>& rows,
                         const std::vector<std::string>& owners, char side) {
        for (const auto& owner : owners) {
            bool present = false;
            for (const auto& [key, tag_id] : rows) {
                if (key == owner && tag_id == tag->id) present = true;
            }
            if (present) continue;
            journal.record_association(side, owner);
            rows.emplace_back(owner, tag->id);
            changed = true;
        }
    };
    associate(document_->asset_tags, asset_ids, 'a');
    associate(document_->version_tags, version_ids, 'v');
    if (changed) {
        domain::DataError error = save_or_rollback(journal);
        if (!error.ok()) return error;
    }
    return *tag;
}

domain::DataError TagStore::bulk_remove_tag(
    const std::string& name, const std::vector<std::string>& asset_ids,
    const std::vector<std::string>& version_ids) {
    if (asset_ids.empty() && version_ids.empty()) {
        return catalog_error("bulk_remove_tag requires asset_ids or version_ids");
    }
    const std::string normalized = normalize_tag_name(name);
    const Tag* tag = tag_by_name(normalized);
    if (tag == nullptr) return domain::DataError(domain::ErrorCode::Ok, "");
    Journal journal(document_);
    bool changed = false;
    auto disassociate = [&](std::vector<std::pair<std::string, std::string>>& rows,
                            const std::vector<std::string>& owners, char side) {
        for (const auto& owner : owners) {
            journal.record_association(side, owner);
            auto kept = std::remove_if(
                rows.begin(), rows.end(),
                [&](const std::pair<std::string, std::string>& row) {
                    return row.first == owner && row.second == tag->id;
                });
            if (kept != rows.end()) {
                rows.erase(kept, rows.end());
                changed = true;
            }
        }
    };
    disassociate(document_->asset_tags, asset_ids, 'a');
    disassociate(document_->version_tags, version_ids, 'v');
    if (changed) {
        journal.drop_empty_keys();
        return save_or_rollback(journal);
    }
    return domain::DataError(domain::ErrorCode::Ok, "");
}

std::map<std::string, domain::Json> TagStore::tag_usage() const {
    std::map<std::string, domain::Json> counts;
    for (const auto& tag : document_->tags) {
        domain::Json entry = domain::Json::object();
        entry["name"] = tag.name;
        entry["display_name"] = tag.display_name.value_or(tag.name);
        entry["assets"] = 0;
        entry["versions"] = 0;
        counts[tag.id] = std::move(entry);
    }
    for (const auto& [owner, tag_id] : document_->asset_tags) {
        (void)owner;
        auto it = counts.find(tag_id);
        if (it != counts.end()) it->second["assets"] =
            it->second["assets"].get<int>() + 1;
    }
    for (const auto& [owner, tag_id] : document_->version_tags) {
        (void)owner;
        auto it = counts.find(tag_id);
        if (it != counts.end()) it->second["versions"] =
            it->second["versions"].get<int>() + 1;
    }
    return counts;
}

std::vector<Tag> TagStore::search_tags(const std::string& text,
                                       std::optional<std::size_t> limit) const {
    const std::string needle = normalize_tag_name(text);
    std::vector<Tag> matches;
    for (const auto& tag : document_->tags) {
        bool hit = needle.empty();
        if (!hit && tag.name.find(needle) != std::string::npos) hit = true;
        if (!hit && tag.display_name.has_value() &&
            normalize_tag_name(*tag.display_name).find(needle) !=
                std::string::npos) {
            hit = true;
        }
        if (hit) matches.push_back(tag);
    }
    if (limit.has_value() && matches.size() > *limit) {
        matches.resize(*limit);
    }
    return matches;
}

domain::Result<Tag> TagStore::delete_unused_tag(const std::string& name) {
    const std::string normalized = normalize_tag_name(name);
    Tag* tag = tag_by_name_mut(normalized);
    if (tag == nullptr) {
        return catalog_error("Unknown tag: " + name);
    }
    auto usage = tag_usage();
    auto it = usage.find(tag->id);
    const int assets = it != usage.end() ? it->second["assets"].get<int>() : 0;
    const int versions = it != usage.end() ? it->second["versions"].get<int>() : 0;
    if (assets != 0 || versions != 0) {
        return catalog_error("Tag '" + tag->name + "' is still in use (" +
                             std::to_string(assets) + " assets, " +
                             std::to_string(versions) + " versions)");
    }
    Journal journal(document_);
    Tag removed = *tag;
    journal.record_tag_removed(tag);
    for (auto it2 = document_->tags.begin(); it2 != document_->tags.end(); ++it2) {
        if (&*it2 == tag) {
            document_->tags.erase(it2);
            break;
        }
    }
    domain::DataError error = save_or_rollback(journal);
    if (!error.ok()) return error;
    return removed;
}

std::vector<Tag> TagStore::prune_unused_tags() {
    auto usage = tag_usage();
    std::vector<Tag> unused;
    for (const auto& tag : document_->tags) {
        auto it = usage.find(tag.id);
        const int assets = it != usage.end() ? it->second["assets"].get<int>() : 0;
        const int versions = it != usage.end() ? it->second["versions"].get<int>() : 0;
        if (assets == 0 && versions == 0) unused.push_back(tag);
    }
    if (unused.empty()) return {};
    Journal journal(document_);
    for (const auto& tag : unused) {
        for (auto it = document_->tags.begin(); it != document_->tags.end(); ++it) {
            if (it->id == tag.id && it->name == tag.name) {
                journal.record_tag_removed(&*it);
                document_->tags.erase(it);
                break;
            }
        }
    }
    domain::DataError error = save_or_rollback(journal);
    if (!error.ok()) return {};
    return unused;
}

}  // namespace pwb::catalog
