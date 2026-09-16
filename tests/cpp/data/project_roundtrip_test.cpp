// data.project_roundtrip — every corpus .paleo.json loads, saves and
// reloads; the writer is idempotent under a fixed clock (test-plan §2).
#include "compare_json.hpp"
#include "pwb_test.hpp"

#include "pwb/domain/json.hpp"
#include "pwb/project/manager.hpp"

#include <fstream>
#include <sstream>

namespace {

namespace fs = std::filesystem;

constexpr const char* kClock = "2026-09-16T08:00:00.000000+00:00";

fs::path fixture_project(const char* dir, const char* file) {
    return fs::path(PWB_DATA_FIXTURE_DIR) / dir / file;
}

std::string read_all(const fs::path& file) {
    std::ifstream stream(file, std::ios::binary);
    std::ostringstream buffer;
    buffer << stream.rdbuf();
    return buffer.str();
}

fs::path scratch_copy(const char* tag, const fs::path& source) {
    const fs::path root =
        fs::temp_directory_path() / ("pwb_roundtrip_" + std::string(tag));
    std::error_code ec;
    fs::remove_all(root, ec);
    fs::create_directories(root, ec);
    const fs::path copy = root / source.filename();
    fs::copy_file(source, copy, ec);
    return copy;
}

void roundtrip_case(const char* dir, const char* file) {
    const fs::path copy = scratch_copy(file, fixture_project(dir, file));
    pwb::project::ProjectManager first(copy);
    first.set_clock_for_tests(kClock);
    auto loaded = first.load();
    PWB_CHECK(loaded.is_ok());
    auto saved = first.save(loaded.value().document);
    PWB_CHECK(saved.is_ok());
    const std::string pass1 = read_all(copy);
    // Second session, same clock: byte-identical output (stable writer).
    pwb::project::ProjectManager second(copy);
    second.set_clock_for_tests(kClock);
    auto reloaded = second.load();
    PWB_CHECK(reloaded.is_ok());
    auto saved2 = second.save(reloaded.value().document);
    PWB_CHECK(saved2.is_ok());
    PWB_CHECK(read_all(copy) == pass1);
    // Saved text re-parses to the live tree (no silent loss).
    const pwb::domain::Json tree =
        pwb::domain::Json::parse(read_all(copy));
    const auto diff = pwb_test::json_compare(
        tree, reloaded.value().document.root());
    PWB_CHECK(!diff.has_value());
    std::error_code ec;
    fs::remove_all(copy.parent_path(), ec);
}

}  // namespace

PWB_TEST(roundtrip_minimal) {
    roundtrip_case("minimal", "minimal.paleo.json");
}
PWB_TEST(roundtrip_typical) {
    roundtrip_case("typical", "typical.paleo.json");
}
PWB_TEST(roundtrip_unicode_paths) {
    roundtrip_case("unicode_paths", "unicode_paths.paleo.json");
}
PWB_TEST(roundtrip_legacy_abs_paths) {
    roundtrip_case("legacy_abs_paths", "legacy_abs_paths.paleo.json");
}
PWB_TEST(roundtrip_missing_resource) {
    roundtrip_case("missing_resource", "typical.paleo.json");
}
PWB_TEST(future_schema_save_refused) {
    const fs::path copy =
        scratch_copy("future", fixture_project("future_schema",
                                                "typical.paleo.json"));
    pwb::project::ProjectManager manager(copy);
    auto loaded = manager.load();
    PWB_CHECK(loaded.is_ok());
    PWB_CHECK(loaded.value().document.read_only());
    auto saved = manager.save(loaded.value().document);
    PWB_CHECK(!saved.is_ok());
    PWB_CHECK(saved.error().code ==
              pwb::domain::ErrorCode::FutureSchema);
    std::error_code ec;
    fs::remove_all(copy.parent_path(), ec);
}
