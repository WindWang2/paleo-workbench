// data.crash_recovery — a child process TRULY TERMINATES (std::_Exit, no
// unwinding) right after a durable persistence checkpoint; a NEW process
// (this parent, which never touched the child's handles) then reopens and
// recovers. This proves recovery does not depend on exception-stack
// unwinding — only on the durable journal + SQLite state on disk.
//
// Child mode: data_crash_recovery --child <phase> <project> <staged-file>
#include "pwb_test.hpp"

#include "pwb/catalog/repository.hpp"
#include "pwb/data/commit_coordinator.hpp"
#include "pwb/data/facade.hpp"
#include "pwb/domain/sha256.hpp"
#include "pwb/project/manager.hpp"

#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <string>

#if defined(_WIN32)
#include <process.h>
#else
#ifndef _WIN32
#include <sys/wait.h>
#endif  // sys/wait.h is POSIX-only (WIFEXITED); the Windows path uses _pclose directly
#include <unistd.h>
#endif

namespace {

namespace fs = std::filesystem;

constexpr const char* kClock = "2026-09-16T08:00:00.000000+00:00";
constexpr int kCrashExit = 86;

struct Scratch {
    fs::path root;
    fs::path project;

    ~Scratch() {
        std::error_code ec;
        fs::remove_all(root, ec);
    }
};

Scratch fresh_typical(const char* tag) {
    Scratch scratch;
    scratch.root =
        fs::temp_directory_path() / ("pwb_crash_" + std::string(tag));
    std::error_code ec;
    fs::remove_all(scratch.root, ec);
    const fs::path source = fs::path(PWB_DATA_FIXTURE_DIR) / "typical";
    fs::copy(source, scratch.root,
             fs::copy_options::recursive | fs::copy_options::overwrite_existing,
             ec);
    scratch.project = scratch.root / "typical.paleo.json";
    return scratch;
}

fs::path write_staged(const fs::path& root, const std::string& bytes) {
    const fs::path file = root / "staged.bin";
    std::ofstream out(file, std::ios::binary | std::ios::trunc);
    out.write(bytes.data(), static_cast<std::streamsize>(bytes.size()));
    return file;
}

pwb::domain::VersionId first_current_version(const fs::path& project) {
    pwb::catalog::CatalogRepository repository(
        pwb::project::catalog_sqlite_for(project));
    auto document = repository.open_read_only();
    if (!document.is_ok()) return {};
    for (const auto& version : document.value().versions) {
        for (const auto& asset : document.value().assets) {
            if (asset.id == version.asset_id &&
                asset.current_version_id.has_value() &&
                *asset.current_version_id == version.id) {
                return version.id;
            }
        }
    }
    return {};
}

// Spawn a REAL child process; the parent never opens the project before
// the child died. POSIX: fork/exec/waitpid; Windows: _spawnl/_cwait.
int spawn_child(const std::string& exe, const char* phase,
                const fs::path& project, const fs::path& staged) {
#if defined(_WIN32)
    return _spawnl(_P_WAIT, exe.c_str(), exe.c_str(), "--child", phase,
                   project.string().c_str(), staged.string().c_str(),
                   static_cast<char*>(nullptr));
#else
    const pid_t pid = ::fork();
    if (pid < 0) return -1;
    if (pid == 0) {
        ::execl(exe.c_str(), exe.c_str(), "--child", phase,
                project.string().c_str(), staged.string().c_str(),
                static_cast<char*>(nullptr));
        ::_exit(127);  // exec failed
    }
    int status = 0;
    if (::waitpid(pid, &status, 0) < 0) return -1;
    if (WIFEXITED(status)) return WEXITSTATUS(status);
    if (WIFSIGNALED(status)) return 128 + WTERMSIG(status);
    return -1;
#endif
}

// Child: run the publish/commit up to the phase, then hard-exit.
int child_main(const std::string& phase_name, const fs::path& project,
               const fs::path& staged) {
    pwb::data::JournalPhase phase = pwb::data::JournalPhase::Invalid;
    for (int probe = static_cast<int>(pwb::data::JournalPhase::Written);
         probe <= static_cast<int>(pwb::data::JournalPhase::RunCompleted);
         ++probe) {
        if (to_string(static_cast<pwb::data::JournalPhase>(probe)) ==
            phase_name) {
            phase = static_cast<pwb::data::JournalPhase>(probe);
        }
    }
    if (phase == pwb::data::JournalPhase::Invalid) return 2;

    pwb::project::ProjectManager manager(project);
    manager.set_clock_for_tests(kClock);
    pwb::catalog::CatalogRepository repository(
        pwb::project::catalog_sqlite_for(project));
    pwb::data::CommitCoordinator coordinator(
        manager, repository, pwb::data::DataFacade::journal_dir_for(project));
    auto loaded = manager.load();
    if (!loaded.is_ok()) return 3;

    const pwb::domain::VersionId base = first_current_version(project);
    pwb::data::RunRegistrationV1 registration;
    registration.run_id = pwb::domain::RunId(pwb::domain::make_id("run_"));
    registration.operation = "crash.probe";
    registration.generator = "crash-probe@1";
    registration.input_version_ids = {base};
    if (!coordinator.register_run(registration).is_ok()) return 4;

    coordinator.set_fault_hook(
        [phase](pwb::data::JournalPhase reached)
            -> std::optional<pwb::domain::DataError> {
            if (reached != phase) return std::nullopt;
            // TRUE termination at the checkpoint: flush C streams only,
            // no destructors, no journal rollback, no exception unwind.
            std::fflush(stdout);
            std::fflush(stderr);
            std::_Exit(kCrashExit);
        });

    pwb::data::PublishRequestV1 request;
    request.operation_id =
        pwb::domain::OperationId(pwb::domain::make_id("op_"));
    request.run_id = registration.run_id;
    request.new_asset_name = "crash result";
    pwb::data::StagedAssetV1 product;
    product.source_path = staged;
    product.sha256 = pwb::domain::Sha256::of_file(staged);
    product.format = "f32";
    request.products.push_back(product);
    auto receipt = coordinator.publish_run_result(request,
                                                  loaded.value().document);
    // Reaching here means the hook never fired — wrong phase wiring.
    std::cerr << "child: publish returned "
              << to_string(receipt.value().status) << " without crashing\n";
    return 99;
}

}  // namespace

PWB_TEST(child_crash_after_catalog_commit_recovers_in_new_process) {
    Scratch scratch = fresh_typical("cc");
    const fs::path staged = write_staged(scratch.root, "crash-volume");

    const int code = spawn_child(pwb_test::g_argv[0], "catalog_committed",
                                 scratch.project, staged);
    PWB_CHECK(code == kCrashExit);  // the child truly died at the checkpoint

    // Durable evidence exists before recovery.
    std::error_code ec;
    bool journal_found = false;
    const fs::path journal_dir =
        pwb::data::DataFacade::journal_dir_for(scratch.project);
    for (fs::directory_iterator it(journal_dir, ec), end; it != end;
         it.increment(ec)) {
        if (it->path().extension() == ".json") journal_found = true;
    }
    PWB_CHECK(journal_found);

    // NEW process recovers: this test process never opened the project
    // before this point.
    pwb::project::ProjectManager manager(scratch.project);
    manager.set_clock_for_tests(kClock);
    pwb::catalog::CatalogRepository repository(
        pwb::project::catalog_sqlite_for(scratch.project));
    pwb::data::CommitCoordinator coordinator(
        manager, repository, journal_dir);
    auto loaded = manager.load();
    PWB_CHECK(loaded.is_ok());
    auto report = coordinator.recover(loaded.value().document);
    PWB_CHECK(report.continued.size() == 1);
    PWB_CHECK(report.pending.empty());

    auto document = repository.open_read_only();
    PWB_CHECK(document.is_ok());
    PWB_CHECK(document.value().versions.size() == 6);
    PWB_CHECK(document.value().assets.size() == 3);
    bool complete_run = false;
    for (const auto& run : document.value().runs) {
        if (run.operation == "crash.probe" &&
            run.status == pwb::data::kRunStatusComplete &&
            run.output_version_ids.size() == 1) {
            complete_run = true;
        }
    }
    PWB_CHECK(complete_run);
}

PWB_TEST(child_crash_after_payload_staged_rolls_back_in_new_process) {
    Scratch scratch = fresh_typical("ps");
    const fs::path staged = write_staged(scratch.root, "crash-volume");

    const int code = spawn_child(pwb_test::g_argv[0], "payload_staged",
                                 scratch.project, staged);
    PWB_CHECK(code == kCrashExit);

    pwb::project::ProjectManager manager(scratch.project);
    manager.set_clock_for_tests(kClock);
    pwb::catalog::CatalogRepository repository(
        pwb::project::catalog_sqlite_for(scratch.project));
    pwb::data::CommitCoordinator coordinator(
        manager, repository,
        pwb::data::DataFacade::journal_dir_for(scratch.project));
    auto loaded = manager.load();
    PWB_CHECK(loaded.is_ok());
    auto report = coordinator.recover(loaded.value().document);
    PWB_CHECK(report.continued.size() == 1);  // catalog tx completes the op

    auto document = repository.open_read_only();
    PWB_CHECK(document.is_ok());
    PWB_CHECK(document.value().versions.size() == 6);
    for (const auto& run : document.value().runs) {
        if (run.operation == "crash.probe") {
            PWB_CHECK(run.status == pwb::data::kRunStatusComplete);
        }
    }
}

int main(int argc, char** argv) {
    setvbuf(stdout, nullptr, _IONBF, 0);
    if (argc == 5 && std::string(argv[1]) == "--child") {
        return child_main(argv[2], fs::path(argv[3]), fs::path(argv[4]));
    }
    ::pwb_test::set_args(argc, argv);
    return ::pwb_test::run_all();
}
