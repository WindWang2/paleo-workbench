// cpp-close-01 — the CONCRETE catalog service closure acceptance.
//
// Drives the real composition layer (closure_catalog_service +
// closure_catalog_install over the CONV-31b deep core) through the full
// production chain and the failure matrix the line owns:
//   * open → query/filter → import registration → working copy → commit →
//     close/reopen (durability + revision consistency)
//   * failed transaction → no half product (rollback incl. payload unlink,
//     CAS revision conflict surfaces as ConflictBaseVersion + stale_write,
//     never auto-overwritten)
//   * read-only store/dir → honest refusal or manifest rebuild, no fake
//     success; corrupt store → isolate + manifest rebuild; truncated
//     manifest (short write) → .bak ladder
//   * concurrent adapters on one store (WAL) — the second writer's stale
//     session is refused
//   * asset change subscription — post-commit events only, identity +
//     revision carried, failed ops publish nothing
//   * Transaction error channel (the #1398 leftover): a failed BEGIN
//     surfaces through commit() and no longer commits the OUTER scope
//   * production binding: ProjectControllerCore driven with the REAL
//     runtime bag + REAL ProjectManager save (Qt-free, no fakes)
#include "pwb_test.hpp"

#include "closure_catalog_install.hpp"
#include "closure_catalog_service.hpp"

#include <pwb/catalog/repository.hpp>
#include <pwb/catalog/sqlite.hpp>
#include <pwb/project/document.hpp>
#include <pwb/project/manager.hpp>
#include <pwb/ui_controllers/job_runner.hpp>
#include <pwb/ui_controllers/project_controller.hpp>
#include <pwb/ui_controllers/project_save.hpp>

#include <unistd.h>

#include <atomic>
#include <fstream>
#include <system_error>

namespace fs = std::filesystem;
using pwb::app::closure_catalog::CatalogClosureAdapter;
using pwb::app::closure_catalog::CatalogChangeEvent;
using pwb::app::closure_catalog::CatalogProjectIdentity;
using pwb::app::closure_catalog::InstalledCatalogClosure;
using pwb::domain::ErrorCode;

namespace {

// The #1220 in-transaction CAS channel: ConflictBaseVersion + the
// stale_write detail flag (apply_changes.hpp).
bool catalog_stale_write_(const pwb::domain::DataError& error) {
    return pwb::catalog::is_stale_write(error);
}

void write_file_(const fs::path& file, const std::string& bytes) {
    std::ofstream stream(file, std::ios::binary);
    stream << bytes;
}

std::int64_t count_files_(const fs::path& dir) {
    std::int64_t count = 0;
    std::error_code ec;
    fs::recursive_directory_iterator it(dir, ec), end;
    if (ec) return -1;
    for (; it != end; it.increment(ec)) {
        if (ec) return count;
        if (it->is_regular_file(ec)) ++count;
    }
    return count;
}

fs::path raw_stage_dir_(const fs::path& project_file) {
    return project_file.parent_path() /
           (project_file.stem().string() + ".artifacts") / "raw";
}

CatalogProjectIdentity identity_for_(const fs::path& project_file,
                                     const std::string& id) {
    CatalogProjectIdentity identity;
    identity.project_path = project_file;
    identity.project_id = id;
    identity.project_name = project_file.stem().string();
    return identity;
}

// The project fixture: a real .paleo.json written through the production
// ProjectManager, plus two importable source files.
struct Fixture {
    fs::path root;
    fs::path incoming;
    fs::path project_file;
    fs::path second_file;

    explicit Fixture(const std::string& name) {
        root = fs::temp_directory_path() /
               ("pwb_catalog_closure_" + name);
        std::error_code ec;
        fs::remove_all(root, ec);
        fs::create_directories(root / "incoming", ec);
        incoming = root / "incoming";
        project_file = root / (name + ".paleo.json");
        second_file = root / (name + "_b.paleo.json");
        write_file_(incoming / "Well-A.las", "las-bytes-" + name + "\n");
        write_file_(incoming / "tops.csv", "formation,top\nF1,10\n");

        pwb::project::ProjectManager manager(project_file);
        auto document = pwb::project::ProjectDocument::create_new(name, "");
        auto saved = manager.save(document);
        if (!saved.is_ok()) {
            std::cerr << "fixture save failed: " << saved.error().message
                      << "\n";
        }

        pwb::project::ProjectManager second(second_file);
        auto doc_b =
            pwb::project::ProjectDocument::create_new(name + "_b", "");
        auto saved_b = second.save(doc_b);
        if (!saved_b.is_ok()) {
            std::cerr << "fixture b save failed: " << saved_b.error().message
                      << "\n";
        }
    }

    ~Fixture() {
        // Best-effort chmod cleanup so remove_all works after read-only
        // failure-injection cases.
        std::error_code ec;
        for (fs::recursive_directory_iterator it(root, ec), end; it != end;
             it.increment(ec)) {
            if (ec) break;
            fs::permissions(it->path(), fs::perms::owner_all,
                            fs::perm_options::replace, ec);
        }
        fs::permissions(root, fs::perms::owner_all, fs::perm_options::replace,
                        ec);
        fs::remove_all(root, ec);
    }
};

}  // namespace

// ---------------------------------------------------------------------------
// Transaction error channel (#1398 leftover) — a failed BEGIN must surface
// through commit() and must NOT commit the surrounding scope; clean commit /
// rollback / destructor rollback stay correct.
// ---------------------------------------------------------------------------
PWB_TEST(closure_transaction_error_channel) {
    Fixture fx("txn");
    auto db_result = pwb::catalog::Database::open(
        fx.project_file.parent_path() / "txn_probe.sqlite",
        pwb::catalog::SqliteOpenMode::Create);
    PWB_CHECK(db_result.is_ok());
    auto db = std::move(db_result.value());
    PWB_CHECK(db.execute("CREATE TABLE t (v TEXT)").ok());

    // (a) clean commit persists.
    {
        pwb::catalog::Transaction transaction(db);
        db.prepare("INSERT INTO t (v) VALUES ('committed')")
            .step_done();
        auto error = transaction.commit();
        PWB_CHECK(error.ok());
    }
    // (b) destructor rollback discards.
    {
        pwb::catalog::Transaction transaction(db);
        db.prepare("INSERT INTO t (v) VALUES ('rolled-back')").step_done();
    }
    // (c) explicit rollback discards.
    {
        pwb::catalog::Transaction transaction(db);
        db.prepare("INSERT INTO t (v) VALUES ('rolled-back-2')")
            .step_done();
        PWB_CHECK(transaction.rollback().ok());
    }
    // (d) the #1398 regression: a NESTED BEGIN fails inside the outer
    // transaction; before the fix the nested commit() swallowed the error,
    // marked itself committed and PREMATURELY COMMITTED the outer scope.
    {
        pwb::catalog::Transaction outer(db);
        db.prepare("INSERT INTO t (v) VALUES ('outer-pending')")
            .step_done();
        std::string nested_error;
        {
            pwb::catalog::Transaction nested(db);  // BEGIN fails here
            nested_error = nested.commit().message;
        }
        PWB_CHECK(!nested_error.empty());
        // The outer transaction is still open: its row is not yet visible
        // to a SECOND connection (same-connection reads see uncommitted
        // rows — sqlite semantics), and its own commit now succeeds.
        {
            auto peer = pwb::catalog::Database::open(
                fx.project_file.parent_path() / "txn_probe.sqlite",
                pwb::catalog::SqliteOpenMode::ReadOnly);
            PWB_CHECK(peer.is_ok());
            auto seen = peer.value().scalar_i64(
                "SELECT COUNT(*) FROM t WHERE v = 'outer-pending'");
            PWB_CHECK(seen.is_ok() && seen.value() == 0);
        }
        PWB_CHECK(outer.commit().ok());
        auto landed = db.scalar_i64(
            "SELECT COUNT(*) FROM t WHERE v = 'outer-pending'");
        PWB_CHECK(landed.is_ok() && landed.value() == 1);
    }
    // Final state: exactly the committed rows.
    auto total = db.scalar_i64("SELECT COUNT(*) FROM t");
    PWB_CHECK(total.is_ok() && total.value() == 2);
}

// ---------------------------------------------------------------------------
// The full production chain on the real adapter.
// ---------------------------------------------------------------------------
PWB_TEST(closure_chain_query_import_commit_reopen) {
    Fixture fx("chain");
    std::vector<CatalogChangeEvent> events;

    auto opened = CatalogClosureAdapter::open(
        fx.project_file, identity_for_(fx.project_file, "proj-chain-01"));
    PWB_CHECK(opened.is_ok());
    auto adapter = std::move(opened.value());
    auto sub = adapter->change_feed().subscribe(
        [&](const CatalogChangeEvent& event) { events.push_back(event); });

    // ---- 查询/筛选 on the empty catalog --------------------------------
    PWB_CHECK(adapter->list_assets(/*include_trashed=*/true).empty());
    pwb::catalog::AssetSearchQuery query;
    query.text = "Well";
    PWB_CHECK(adapter->search_assets(query).empty());

    // ---- 导入结果注册（import_raw） --------------------------------------
    auto imported = adapter->import_raw(
        fx.incoming / "Well-A.las", std::string("Well-A"),
        std::string("well"), std::string("las"),
        pwb::domain::Json::object(), std::string("legacy-well-a"));
    PWB_CHECK(imported.is_ok());
    const auto& version = imported.value();
    PWB_CHECK(version.version_number == 1);
    PWB_CHECK(version.managed);
    PWB_CHECK(version.sha256.has_value() && !version.sha256->empty());

    // The legacy bridge answers resolve_legacy_resource (CatalogPortApi).
    auto ref = adapter->resolve_legacy_resource("legacy-well-a");
    PWB_CHECK(ref.has_value() && ref->version_id == version.id.str());

    // 查询 now finds it (by text and by stage filter).
    PWB_CHECK(adapter->search_assets(query).size() == 1);
    pwb::catalog::AssetSearchQuery stage_query;
    stage_query.stage = pwb::domain::DataStage::Raw;
    PWB_CHECK(adapter->search_assets(stage_query).size() == 1);
    PWB_CHECK(adapter->asset_exists(version.asset_id.str()));

    // Read-service face (04 enrichers): document / row overview feed.
    const auto* asset = adapter->get_asset(version.asset_id.str());
    PWB_CHECK(asset != nullptr && asset->name == "Well-A");
    PWB_CHECK(adapter->list_versions(version.asset_id.str()).size() == 1);
    PWB_CHECK(fs::is_regular_file(adapter->resolve_path(version)));

    // Review face (09): lineage hop + audit + missing sources over REAL data.
    auto hop = adapter->review_api().get_lineage(version.id.str());
    PWB_CHECK(hop.has_value() && hop->parents.empty());
    auto audit = adapter->review_api().audit(/*deep=*/false, nullptr);
    PWB_CHECK(audit.issues.empty());
    auto missing = adapter->review_api().find_missing_sources(nullptr);
    PWB_CHECK(missing.entries.empty());

    // ---- working copy → 提交版本 ----------------------------------------
    auto working = adapter->create_working_copy(version.id.str());
    PWB_CHECK(fs::is_regular_file(working));
    // The raising seam returns the committed version directly; failures
    // throw domain::DataException.
    auto committed = adapter->commit_working_copy(
        working, version.asset_id.str(), std::string("Well-A-edit"),
        pwb::domain::DataStage::Derived, std::nullopt);
    PWB_CHECK(committed.version_number == 2);
    PWB_CHECK(committed.stage == pwb::domain::DataStage::Derived);
    // The working copy was consumed and its registry row dropped.
    PWB_CHECK(!fs::exists(working));

    // Promote (review mutation parity) lands version 3 in the Output stage.
    auto promoted = adapter->promote_version(
        committed.id.str(), pwb::domain::DataStage::Output,
        std::string("reviewer"), std::nullopt);
    PWB_CHECK(promoted.version_number == 3);
    PWB_CHECK(adapter->verify_integrity(promoted.id.str()) == "verified");

    const auto revision_before = adapter->document_revision();

    // ---- 关闭重开：durability + identity --------------------------------
    const auto identity = adapter->identity();
    adapter->close();
    PWB_CHECK(adapter->is_closed());

    auto reopened = CatalogClosureAdapter::open(
        fx.project_file, identity_for_(fx.project_file, "proj-chain-01"));
    PWB_CHECK(reopened.is_ok());
    auto adapter2 = std::move(reopened.value());
    PWB_CHECK(adapter2->document_revision() == revision_before);
    PWB_CHECK(adapter2->list_versions(version.asset_id.str()).size() == 3);
    PWB_CHECK(adapter2->get_trashed_assets().empty());
    // 工程身份保留：same path/id survive the round trip.
    PWB_CHECK(adapter2->identity().project_id == identity.project_id);
    PWB_CHECK(adapter2->resolve_legacy_resource("legacy-well-a").has_value());

    // Change feed: exactly the post-commit events, all carrying identity.
    PWB_CHECK(events.size() >= 3);
    for (const auto& event : events) {
        PWB_CHECK(event.identity.project_id == "proj-chain-01");
        PWB_CHECK(event.identity.project_path == fx.project_file);
    }
}

// ---------------------------------------------------------------------------
// Concurrent revision conflict + failure rollback (no half product, no
// auto-overwrite).
// ---------------------------------------------------------------------------
PWB_TEST(closure_conflict_rollback_no_half_product) {
    Fixture fx("conflict");
    auto a = CatalogClosureAdapter::open(
        fx.project_file, identity_for_(fx.project_file, "proj-a"));
    auto b = CatalogClosureAdapter::open(
        fx.project_file, identity_for_(fx.project_file, "proj-b"));
    PWB_CHECK(a.is_ok() && b.is_ok());
    auto adapter_a = std::move(a.value());
    auto adapter_b = std::move(b.value());

    // A registers an import (revision 0 → 1).
    auto first = adapter_a->import_raw(
        fx.incoming / "Well-A.las", std::string("Well-A"), std::nullopt,
        std::nullopt, pwb::domain::Json::object());
    PWB_CHECK(first.is_ok());

    PWB_CHECK(adapter_b->list_assets(/*include_trashed=*/true).empty());
    // B's session is stale (loaded revision 0). Its import must be REFUSED
    // with the CAS channel — never auto-overwrite A's submission — and the
    // failed transaction must leave NO half product in B's memory or on
    // B's behalf in the store.
    const std::int64_t raw_files_before =
        count_files_(raw_stage_dir_(fx.project_file));
    bool refused = false;
    try {
        (void)adapter_b->import_raw(
            fx.incoming / "tops.csv", std::string("Tops"), std::nullopt,
            std::nullopt, pwb::domain::Json::object());
    } catch (const pwb::domain::DataException& error) {
        refused = true;
        PWB_CHECK(catalog_stale_write_(error.error()));
    }
    PWB_CHECK(refused);
    // B's in-memory document rolled back to its (stale) clean state —
    // still ZERO assets from B's pre-A snapshot (A's committed asset must
    // NOT have leaked into B's memory un-refreshed).
    PWB_CHECK(adapter_b->list_assets(/*include_trashed=*/true).empty());
    // No raw-stage payload left behind by B's rolled-back import (blobs are
    // shared on purpose and excluded from this check).
    const std::int64_t raw_files_after =
        count_files_(raw_stage_dir_(fx.project_file));
    PWB_CHECK(raw_files_before == raw_files_after);

    // A's committed data is untouched; B reopens and sees it.
    PWB_CHECK(adapter_a->list_assets(/*include_trashed=*/true).size() == 1);
    adapter_b->close();
    auto b2 = CatalogClosureAdapter::open(
        fx.project_file, identity_for_(fx.project_file, "proj-b"));
    PWB_CHECK(b2.is_ok());
    auto adapter_b2 = std::move(b2.value());
    PWB_CHECK(adapter_b2->list_assets(/*include_trashed=*/true).size() == 1);
    PWB_CHECK(adapter_b2->document_revision() ==
              adapter_a->document_revision());
}

// ---------------------------------------------------------------------------
// Corrupt store / truncated manifest / read-only refusal.
// ---------------------------------------------------------------------------
PWB_TEST(closure_corrupt_shortwrite_readonly) {
    // (1) Corrupt canonical store → isolate + manifest rebuild.
    {
        Fixture fx("corrupt");
        auto adapter = CatalogClosureAdapter::open(
            fx.project_file, identity_for_(fx.project_file, "proj-corrupt"));
        PWB_CHECK(adapter.is_ok());
        auto imported = adapter.value()->import_raw(
            fx.incoming / "Well-A.las", std::nullopt, std::nullopt,
            std::nullopt, pwb::domain::Json::object());
        PWB_CHECK(imported.is_ok());
        adapter.value()->close();

        // Deterministic damage: destroy the sqlite file header so the
        // store cannot open — the isolate + manifest-rebuild ladder is
        // then guaranteed to run.
        const fs::path store = pwb::project::catalog_sqlite_for(
            fx.project_file);
        {
            std::ofstream out(store, std::ios::binary | std::ios::in);
            out.seekp(0);
            out << "CORRUPTED-HEADER!!";
        }
        auto rebuilt = CatalogClosureAdapter::open(
            fx.project_file, identity_for_(fx.project_file, "proj-corrupt"));
        PWB_CHECK(rebuilt.is_ok());
        auto adapter2 = std::move(rebuilt.value());
        // The manifest (kept current by close()) restored the committed
        // data; the damaged bytes were isolated, not silently deleted.
        PWB_CHECK(adapter2->list_assets(/*include_trashed=*/true).size() == 1);
        bool isolated_found = false;
        for (const auto& entry : fs::directory_iterator(store.parent_path())) {
            if (entry.path().string().find(".corrupt-") !=
                std::string::npos) {
                isolated_found = true;
            }
        }
        PWB_CHECK(isolated_found);
        adapter2->close();
    }

    // (2) Short-write (truncated) manifest with a valid .bak → backup ladder.
    {
        Fixture fx("shortwrite");
        auto adapter = CatalogClosureAdapter::open(
            fx.project_file, identity_for_(fx.project_file, "proj-sw"));
        PWB_CHECK(adapter.is_ok());
        auto imported = adapter.value()->import_raw(
            fx.incoming / "Well-A.las", std::nullopt, std::nullopt,
            std::nullopt, pwb::domain::Json::object());
        PWB_CHECK(imported.is_ok());
        adapter.value()->close();

        const fs::path manifest = pwb::catalog::catalog_manifest_file(
            fx.project_file);
        const fs::path backup = pwb::catalog::catalog_manifest_bak_file(
            fx.project_file);
        // Seed the .bak with the current bytes, then simulate a short
        // write (crash mid-checkpoint): the live manifest is truncated.
        fs::copy_file(manifest, backup, fs::copy_options::overwrite_existing);
        {
            auto size = fs::file_size(manifest);
            std::error_code ec;
            fs::resize_file(manifest, size / 3, ec);
            PWB_CHECK(!ec);
        }
        auto recovered = CatalogClosureAdapter::open(
            fx.project_file, identity_for_(fx.project_file, "proj-sw"));
        PWB_CHECK(recovered.is_ok());
        auto adapter2 = std::move(recovered.value());
        PWB_CHECK(adapter2->list_assets(/*include_trashed=*/true).size() == 1);
        adapter2->close();
    }

    // (3) Read-only project dir + canonical store → honest refusal, no
    // fake success, no silent overwrite of anything.
    {
        Fixture fx("readonly");
        auto adapter = CatalogClosureAdapter::open(
            fx.project_file, identity_for_(fx.project_file, "proj-ro"));
        PWB_CHECK(adapter.is_ok());
        auto imported = adapter.value()->import_raw(
            fx.incoming / "Well-A.las", std::nullopt, std::nullopt,
            std::nullopt, pwb::domain::Json::object());
        PWB_CHECK(imported.is_ok());
        adapter.value()->close();

        if (geteuid() == 0) {
            std::cout << "  SKIP read-only refusal (running as root: "
                         "chmod does not bind root)\n";
        } else {
            std::error_code ec;
            // Close EVERY write rung at once: files read-only (defeats
            // Database::open(ReadWrite)) AND every directory read-only
            // (defeats WAL/-journal creation, isolate-rename, reset-unlink
            // and the manifest-rebuild store creation — a single missed
            // directory leaves the designed recovery ladder a legal open
            // path). Open must then refuse honestly.
            const auto walk = [&](fs::perms file_perms, fs::perms dir_perms) {
                for (fs::recursive_directory_iterator it(
                         fx.project_file.parent_path(), ec),
                     end;
                     it != end; it.increment(ec)) {
                    if (ec) return;
                    std::error_code sec;
                    if (it->is_directory(sec)) {
                        fs::permissions(it->path(), dir_perms,
                                        fs::perm_options::replace, sec);
                    } else {
                        fs::permissions(it->path(), file_perms,
                                        fs::perm_options::replace, sec);
                    }
                }
                fs::permissions(fx.project_file.parent_path(), dir_perms,
                                fs::perm_options::replace, ec);
            };
            walk(fs::perms::owner_read,
                 fs::perms::owner_read | fs::perms::owner_exec);
            auto refused = CatalogClosureAdapter::open(
                fx.project_file,
                identity_for_(fx.project_file, "proj-ro"));
            // Honest refusal (no fake success): the store exists but
            // cannot be opened for write and the manifest rebuild cannot
            // run either. The exact code follows the sqlite error mapping;
            // the message must be present for the user.
            PWB_CHECK(!refused.is_ok());
            PWB_CHECK(!refused.error().message.empty());
            // Restore before the fixture destructor cleans up.
            walk(fs::perms::owner_all, fs::perms::owner_all);
            PWB_CHECK(!ec);
        }
    }
}

// ---------------------------------------------------------------------------
// Interrupted working-copy recovery (user-facing report).
// ---------------------------------------------------------------------------
PWB_TEST(closure_interrupt_recovery_report) {
    Fixture fx("recover");
    auto opened = CatalogClosureAdapter::open(
        fx.project_file, identity_for_(fx.project_file, "proj-rec"));
    PWB_CHECK(opened.is_ok());
    auto adapter = std::move(opened.value());
    auto imported = adapter->import_raw(
        fx.incoming / "Well-A.las", std::nullopt, std::nullopt, std::nullopt,
        pwb::domain::Json::object());
    PWB_CHECK(imported.is_ok());
    auto working = adapter->create_working_copy(imported.value().id.str());
    PWB_CHECK(!working.empty());

    const std::string identity_id = adapter->identity().project_id;
    adapter->close();

    // Simulate the crash-left state through the REGISTRY (sqlite truth):
    // the copy's file is gone and the row was left mid-flight. This runs
    // while NO adapter holds the store (direct BEGIN IMMEDIATE would clash
    // with the live WAL handle otherwise).
    {
        pwb::catalog::CatalogRepository repo(pwb::project::catalog_sqlite_for(
            fx.project_file));
        repo.open_read_write();
        auto rows = repo.list_working_copies({});
        PWB_CHECK(rows.size() == 1);
        PWB_CHECK(repo.set_working_copy_state(rows[0].working_id,
                                              "committing")
                      .ok());
    }
    std::error_code ec;
    fs::remove(working, ec);

    auto reopened = CatalogClosureAdapter::open(
        fx.project_file, identity_for_(fx.project_file, identity_id));
    PWB_CHECK(reopened.is_ok());
    auto adapter2 = std::move(reopened.value());
    adapter2->recover_working_copies();
    const auto& report = adapter2->last_recovery_report();
    PWB_CHECK(report.ran);
    // missing-file judgment runs BEFORE the committing branch (deep-core
    // contract): the vanished copy is reported as dropped.
    PWB_CHECK(report.working_copies.missing_dropped == 1);
    PWB_CHECK(!report.user_notes.empty());
    adapter2->close();
}

// ---------------------------------------------------------------------------
// Change feed: real add/remove/change notification consumed by a subscriber.
// ---------------------------------------------------------------------------
PWB_TEST(closure_change_feed_subscription) {
    Fixture fx("feed");
    auto opened = CatalogClosureAdapter::open(
        fx.project_file, identity_for_(fx.project_file, "proj-feed"));
    PWB_CHECK(opened.is_ok());
    auto adapter = std::move(opened.value());

    std::vector<CatalogChangeEvent::Kind> kinds;
    std::vector<std::vector<std::string>> seen_versions;
    auto sub = adapter->change_feed().subscribe(
        [&](const CatalogChangeEvent& event) {
            kinds.push_back(event.kind);
            seen_versions.push_back(event.version_ids);
        });

    auto imported = adapter->import_raw(
        fx.incoming / "Well-A.las", std::nullopt, std::nullopt, std::nullopt,
        pwb::domain::Json::object());
    PWB_CHECK(imported.is_ok());
    PWB_CHECK(kinds.size() == 1);
    PWB_CHECK(kinds.back() == CatalogChangeEvent::Kind::VersionsChanged);
    PWB_CHECK(seen_versions.back().size() == 1);
    PWB_CHECK(seen_versions.back()[0] == imported.value().id.str());

    // A failed operation publishes NOTHING (post-commit events only).
    bool refused = false;
    try {
        (void)adapter->import_raw(
            fx.incoming / "missing-file.las", std::nullopt, std::nullopt,
            std::nullopt, pwb::domain::Json::object());
    } catch (const pwb::domain::DataException&) {
        refused = true;
    }
    PWB_CHECK(refused);
    PWB_CHECK(kinds.size() == 1);

    // Trash/restore notify as asset-level changes.
    adapter->trash_asset(imported.value().asset_id.str(), "test");
    PWB_CHECK(kinds.back() == CatalogChangeEvent::Kind::AssetsChanged);
    adapter->restore_asset(imported.value().asset_id.str());
    PWB_CHECK(kinds.size() == 3);

    // Cancel stops delivery.
    sub.cancel();
    auto second = adapter->import_raw(
        fx.incoming / "tops.csv", std::nullopt, std::nullopt, std::nullopt,
        pwb::domain::Json::object());
    PWB_CHECK(second.is_ok());
    PWB_CHECK(kinds.size() == 3);
    adapter->close();
}

// ---------------------------------------------------------------------------
// Production binding: ProjectControllerCore with the REAL runtime bag, the
// REAL ProjectManager save path, and a project switch — no fakes.
// ---------------------------------------------------------------------------
PWB_TEST(closure_production_controller_chain) {
    Fixture fx("controller");
    pwb::project::ProjectDocument doc =
        pwb::project::ProjectDocument::create_new("controller", "");
    auto* doc_ptr = &doc;
    std::optional<fs::path> path;
    std::vector<std::string> errors;

    pwb::ui_controllers::ProjectHostApi host;
    host.document = [&] { return doc_ptr; };
    host.replace_document = [&](pwb::project::ProjectDocument&& next) {
        doc = std::move(next);
        doc_ptr = &doc;
    };
    host.project_path = [&] { return path; };
    host.set_project_path = [&](const std::optional<fs::path>& p) {
        path = p;
    };
    host.refresh_shell = [&](bool) {};
    host.show_error = [&](const std::string& title, const std::string& msg) {
        errors.push_back(title + ":" + msg);
    };

    pwb::ui_controllers::ProjectServiceApi services;
    services.load_project = [](const fs::path& target) {
        pwb::project::ProjectManager manager(target);
        return manager.load();
    };
    pwb::ui_controllers::ProjectSaveApiFactory factory =
        [](const fs::path& target) {
            return std::make_unique<
                pwb::ui_controllers::ManagerProjectSaveApi>(target);
        };
    pwb::ui_controllers::InlineJobRunner runner;

    auto installed = InstalledCatalogClosure::install(
        fx.project_file, identity_for_(fx.project_file, "proj-ctl"));
    PWB_CHECK(installed.is_ok());
    auto closure = std::move(installed.value());
    auto runtime = closure.make_runtime();

    pwb::ui_controllers::ProjectControllerCore core(host, runtime, services,
                                                    factory, &runner);
    PWB_CHECK(core.open_project_path(fx.project_file));
    PWB_CHECK(core.last_open_error().empty());
    PWB_CHECK(path.has_value() && *path == fx.project_file);

    // The controller resolved the LIVE adapter through the bag.
    auto* service = runtime.get_catalog_service();
    PWB_CHECK(service != nullptr);
    PWB_CHECK(service->project_path() == fx.project_file);

    // Data-page funnel: a legacy resource row registers through the real
    // import path; a change subscription on the adapter observes it.
    std::atomic<int> feed_count{0};
    auto* feed = closure.change_feed();
    PWB_CHECK(feed != nullptr);
    auto sub = feed->subscribe(
        [&](const CatalogChangeEvent&) { ++feed_count; });
    pwb::domain::Json row = pwb::domain::Json::object();
    row["id"] = "legacy-res-1";
    row["name"] = "Well-A";
    row["path"] = (fx.incoming / "Well-A.las").generic_string();
    row["type"] = "well";
    row["format"] = "las";
    auto ref = runtime.register_resource_input(row);
    PWB_CHECK(ref.has_value());
    PWB_CHECK(feed_count.load() >= 1);

    // Real save through the controller (ManagerProjectSaveApi), then a
    // session close + reopen: the imported input survives (catalog side) —
    // the closed manifest checkpoint + reopen decision table.
    auto saved = core.save_project();
    PWB_CHECK(saved.has_value());
    PWB_CHECK(core.drain_save_job());

    // ---- 工程切换 ---------------------------------------------------------
    const int generation_a = core.session_generation();
    PWB_CHECK(core.open_project_path(fx.second_file));
    PWB_CHECK(core.session_generation() > generation_a);
    auto* service_b = runtime.get_catalog_service();
    PWB_CHECK(service_b != nullptr);
    PWB_CHECK(service_b->project_path() == fx.second_file);

    // Back to A: a fresh adapter over A's store sees the registered input.
    PWB_CHECK(core.open_project_path(fx.project_file));
    auto* service_a2 = runtime.get_catalog_service();
    PWB_CHECK(service_a2 != nullptr);
    PWB_CHECK(service_a2->project_path() == fx.project_file);
    const std::string legacy_asset = ref->asset_id;
    PWB_CHECK(service_a2->asset_exists(legacy_asset));
    PWB_CHECK(service_a2->list_versions(legacy_asset).size() == 1);
}
