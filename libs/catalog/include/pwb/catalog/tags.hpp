// Tag collaborator (conv-31; catalog/tags.py parity).
//
// Every mutator holds the document across the change and the save hook so
// a failed canonical write can never leave a half-applied association in
// memory while disk holds the old state — the #1182 lazy journal
// discipline: only the touched entries are recorded and rollback replays
// them to the exact pre-call state (association lists restored in place,
// removed tags re-inserted at their original positions, created tags
// un-appended). Association order follows the per-owner list semantics of
// the Python dict-of-lists: removals keep relative order, an appended
// association lands at the end of its owner's block.
#pragma once

#include "pwb/catalog/document_index.hpp"
#include "pwb/catalog/models.hpp"
#include "pwb/catalog/refs.hpp"
#include "pwb/domain/errors.hpp"

#include <functional>
#include <map>
#include <optional>
#include <string>
#include <vector>

namespace pwb::catalog {

// The single-transaction save seam (stands in for service._save(DirtySet)):
// return a non-ok DataError to trigger the journaled rollback.
using TagSaveHook = std::function<domain::DataError()>;

class TagStore {
public:
    TagStore(CatalogDocument* document, TagSaveHook save)
        : document_(document), save_(std::move(save)) {}

    // add_tag parity: get-or-create + associate; idempotent. Requires
    // asset_id or version_id to exist.
    domain::Result<Tag> add_tag(const std::string& name,
                                const std::optional<std::string>& asset_id,
                                const std::optional<std::string>& version_id);

    // remove_tag parity: unknown name is a no-op.
    domain::DataError remove_tag(const std::string& name,
                                 const std::optional<std::string>& asset_id,
                                 const std::optional<std::string>& version_id);

    // rename_tag parity: on normalized collision the default merges into
    // the existing tag; on_collision="error" refuses instead.
    domain::Result<Tag> rename_tag(const std::string& old_name,
                                   const std::string& new_name,
                                   const std::string& on_collision = "merge");

    domain::Result<Tag> merge_tags(const std::string& source_name,
                                   const std::string& target_name);

    // create_tag parity: entity-only create (no association), idempotent
    // on the normalized name (display refreshed like Python — actually
    // Python returns the existing tag unchanged; parity kept).
    domain::Result<Tag> create_tag(const std::string& name);

    domain::Result<Tag> bulk_add_tag(
        const std::string& name, const std::vector<std::string>& asset_ids,
        const std::vector<std::string>& version_ids);
    domain::DataError bulk_remove_tag(
        const std::string& name, const std::vector<std::string>& asset_ids,
        const std::vector<std::string>& version_ids);

    // tag_usage parity: per tag id → {name, display_name, assets, versions}.
    std::map<std::string, domain::Json> tag_usage() const;

    // search_tags parity: substring over normalized names/display names.
    std::vector<Tag> search_tags(const std::string& text,
                                 std::optional<std::size_t> limit = std::nullopt) const;

    domain::Result<Tag> delete_unused_tag(const std::string& name);
    std::vector<Tag> prune_unused_tags();

private:
    class Journal;
    const Tag* tag_by_name(const std::string& normalized) const;
    Tag* tag_by_name_mut(const std::string& normalized);
    static std::string display_of(const std::string& raw);
    domain::DataError save_or_rollback(Journal& journal);

    CatalogDocument* document_;
    TagSaveHook save_;
};

}  // namespace pwb::catalog
