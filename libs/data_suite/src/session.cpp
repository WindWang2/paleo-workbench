// WritableSession::open — deliberate write entry (v3-contracts.md §4).
#include "pwb/data/session.hpp"

namespace pwb::data {

domain::Result<WritableSession> WritableSession::open(
    const fs::path& project_file) {
    project::ProjectManager manager(project_file);
    auto loaded = manager.load();
    if (!loaded.is_ok()) {
        return domain::DataError(loaded.error().code, loaded.error().message);
    }
    if (loaded.value().document.read_only()) {
        return domain::DataError(
            domain::ErrorCode::FutureSchema,
            "project is read-only (future schema) — a writable session "
            "refuses to open it");
    }
    catalog::CatalogRepository repository(
        pwb::project::catalog_sqlite_for(project_file));
    auto writable = repository.open_read_write();
    if (!writable.is_ok()) return writable.error();
    auto impl = std::make_unique<Impl>(std::move(manager),
                                       std::move(repository),
                                       std::move(loaded.value().document));
    return WritableSession(std::move(impl));
}

}  // namespace pwb::data
