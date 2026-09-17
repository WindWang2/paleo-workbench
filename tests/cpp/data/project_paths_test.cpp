// data.project_paths — relativize/resolve/escape/Unicode path semantics
// plus read-only open performs zero writes (test-plan.md §2, row 4).
#include "pwb_test.hpp"

#include "pwb/data/facade.hpp"
#include "pwb/project/paths.hpp"

#include <fstream>
#include <sstream>

namespace {

namespace fs = std::filesystem;

fs::path scratch_root() {
    const fs::path root =
        fs::temp_directory_path() / "pwb_data_paths_test";
    std::error_code ec;
    fs::remove_all(root, ec);
    fs::create_directories(root, ec);
    return root;
}

std::string read_all(const fs::path& file) {
    std::ifstream stream(file, std::ios::binary);
    std::ostringstream buffer;
    buffer << stream.rdbuf();
    return buffer.str();
}

}  // namespace

PWB_TEST(relativize_internal_vs_external) {
    // Real absolute paths: the semantics under test (inside → relative,
    // outside → external) are platform-neutral; Windows-literal strings
    // would be bare filenames on POSIX.
    const fs::path root = scratch_root();
    const fs::path project = root / "demo.paleo.json";
    const auto inside =
        pwb::project::relativize_path(root / "a.csv", project);
    PWB_CHECK(!inside.external);
    PWB_CHECK(inside.stored == "a.csv");
    const auto outside = pwb::project::relativize_path(
        fs::temp_directory_path() / "pwb_data_paths_outside" / "b.csv",
        project);
    PWB_CHECK(outside.external);
}

PWB_TEST(resolve_roundtrip_and_escape) {
    const fs::path root = scratch_root();
    const fs::path project = root / "demo.paleo.json";
    auto ok = pwb::project::resolve_project_path("a.csv", project);
    PWB_CHECK(ok.is_ok());
    auto escape = pwb::project::resolve_project_path("../evil.csv", project);
    PWB_CHECK(!escape.is_ok());
    PWB_CHECK(escape.error().code == pwb::domain::ErrorCode::PathEscape);
    auto empty = pwb::project::resolve_project_path("", project);
    PWB_CHECK(!empty.is_ok());
}

PWB_TEST(utf8_path_bridge_roundtrip) {
    // Narrow literal: this TU compiles with /utf-8, so it IS UTF-8 bytes.
    const std::string utf8 = "工区/井位_甲.csv";
    const fs::path path = pwb::project::path_from_u8(utf8);
    PWB_CHECK(pwb::project::path_to_u8(path) == utf8);
}

PWB_TEST(readonly_open_writes_nothing) {
    const fs::path root = scratch_root();
    const fs::path copy = root / "minimal.paleo.json";
    {
        std::error_code ec;
        fs::copy_file(fs::path(PWB_DATA_FIXTURE_DIR) / "minimal" /
                          "minimal.paleo.json",
                      copy, ec);
        PWB_CHECK(!ec);
    }
    const std::string before = read_all(copy);
    const auto mtime_before = fs::last_write_time(copy);
    pwb::data::DataFacade facade(copy);
    auto snapshot = facade.open_snapshot();
    PWB_CHECK(snapshot.is_ok());
    PWB_CHECK(read_all(copy) == before);
    PWB_CHECK(fs::last_write_time(copy) == mtime_before);
    std::error_code ec;
    fs::remove_all(root, ec);
}
