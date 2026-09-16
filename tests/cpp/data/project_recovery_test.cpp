// data.project_recovery — .bak decision table: interrupted save and
// corrupt main recover; double corruption fails honestly (test-plan §2).
#include "pwb_test.hpp"

#include "pwb/project/manager.hpp"

#include <fstream>

namespace {

namespace fs = std::filesystem;

constexpr const char* kClock = "2026-09-16T08:00:00.000000+00:00";

fs::path fresh_minimal(const char* tag) {
    const fs::path root =
        fs::temp_directory_path() / ("pwb_recovery_" + std::string(tag));
    std::error_code ec;
    fs::remove_all(root, ec);
    fs::create_directories(root, ec);
    const fs::path copy = root / "minimal.paleo.json";
    fs::copy_file(fs::path(PWB_DATA_FIXTURE_DIR) / "minimal" /
                      "minimal.paleo.json",
                  copy, ec);
    return copy;
}

void truncate(const fs::path& file, std::size_t keep) {
    std::fstream stream(file,
                        std::ios::binary | std::ios::in | std::ios::out);
    stream.seekp(static_cast<std::streamoff>(keep));
    // Truncation via resize: close, reopen-truncate, rewrite prefix.
    stream.close();
    std::ifstream in(file, std::ios::binary);
    std::string prefix(keep, '\0');
    in.read(prefix.data(), static_cast<std::streamsize>(keep));
    in.close();
    std::ofstream out(file, std::ios::binary | std::ios::trunc);
    out.write(prefix.data(), static_cast<std::streamsize>(keep));
}

}  // namespace

PWB_TEST(corrupt_main_recovers_from_backup) {
    const fs::path copy = fresh_minimal("corrupt");
    pwb::project::ProjectManager setup(copy);
    setup.set_clock_for_tests(kClock);
    auto first = setup.load();
    PWB_CHECK(first.is_ok());
    PWB_CHECK(setup.save(first.value().document).is_ok());
    // Second save materializes the .bak of a good revision.
    auto second = setup.load();
    PWB_CHECK(second.is_ok());
    PWB_CHECK(setup.save(second.value().document).is_ok());
    PWB_CHECK(fs::is_regular_file(
        pwb::project::project_backup_path(copy)));

    truncate(copy, 40);  // corrupt the main file
    pwb::project::ProjectManager recovery(copy);
    auto loaded = recovery.load();
    PWB_CHECK(loaded.is_ok());
    PWB_CHECK(loaded.value().recovered);
    PWB_CHECK(!loaded.value().recovery_source.empty());
    PWB_CHECK(loaded.value().quarantine.has_value());
    PWB_CHECK(loaded.value().document.meta().has_value());
    std::error_code ec;
    fs::remove_all(copy.parent_path(), ec);
}

PWB_TEST(double_corruption_fails_honestly) {
    const fs::path copy = fresh_minimal("double");
    pwb::project::ProjectManager setup(copy);
    setup.set_clock_for_tests(kClock);
    auto first = setup.load();
    PWB_CHECK(first.is_ok());
    PWB_CHECK(setup.save(first.value().document).is_ok());
    auto second = setup.load();
    PWB_CHECK(setup.save(second.value().document).is_ok());
    truncate(copy, 40);
    truncate(pwb::project::project_backup_path(copy), 40);
    pwb::project::ProjectManager recovery(copy);
    auto loaded = recovery.load();
    PWB_CHECK(!loaded.is_ok());
    std::error_code ec;
    fs::remove_all(copy.parent_path(), ec);
}
