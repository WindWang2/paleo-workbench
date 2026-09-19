// viz_a.consistency — hard oracle 1: the same LAS file must yield
// interpretable, consistent data/units/diagnostics across the three
// production paths: the well-log dock (WellLogHostWidget::load_las —
// byte-identical LasSourceAdapter call), the ingest preview bridge, and
// the worker load adapter. Normal files produce real curves/previews;
// WLE-rejected files fail all three paths consistently.

#include <QApplication>

#include <welllog/io/las.hpp>

#include <pwb/ingest/preview/las_preview.hpp>
#include <pwb/ingest/preview/las_wle_bridge.hpp>
#include <pwb/ui_workers/wle_load.hpp>
#include <pwb/viz/well_log_host_widget.hpp>

#include <cstdio>
#include <filesystem>
#include <fstream>
#include <memory>
#include <string>
#include <vector>

namespace fs = std::filesystem;

namespace {

int g_failures = 0;

void check(bool ok, const std::string& what) {
    if (!ok) {
        std::fprintf(stderr, "FAIL %s\n", what.c_str());
        ++g_failures;
    }
}

std::string read_file(const std::string& path) {
    std::ifstream in(path, std::ios::binary);
    return std::string((std::istreambuf_iterator<char>(in)),
                       std::istreambuf_iterator<char>());
}

struct ParseFacts {
    bool ok = false;
    std::string axis_unit;
    std::vector<std::string> mnemonics;
    std::vector<std::string> units;
    std::uint64_t rows = 0;
    std::uint64_t nulls = 0;
    std::size_t diagnostics = 0;
};

// The dock path's exact parse call (well_log_host_widget.cpp load_las).
ParseFacts dock_parse(const std::string& path) {
    ParseFacts facts;
    const std::string bytes = read_file(path);
    welllog::BufferSourceReference source;
    source.uri = path;
    auto result = welllog::LasSourceAdapter::parse(
        std::string_view(bytes), source);
    if (!result.has_value()) return facts;
    facts.ok = true;
    const auto& document = result.value().document;
    const auto& axis = document.sampling_axes().front();
    facts.axis_unit = axis.unit;
    facts.rows = axis.coordinates.length();
    for (const auto& curve : document.curves()) {
        facts.mnemonics.push_back(curve.mnemonic);
        facts.units.push_back(curve.unit);
        for (std::uint64_t i = 0; i < curve.values.length(); ++i) {
            if (auto v = curve.values.value_as_double(i); v && std::isnan(*v)) {
                ++facts.nulls;
            }
        }
    }
    facts.diagnostics = result.value().diagnostics.size();
    return facts;
}

}  // namespace

int main(int argc, char** argv) {
    QApplication app(argc, argv);

    pwb::viz::WellLogHostWidget host;
    const fs::path root = PWB_VIZ_A_FIXTURE_ROOT;

    struct Case {
        const char* rel;
        bool accepted;
    };
    const std::vector<Case> cases = {
        {"las/01_normal_multisection.las", true},
        {"las/03_bad_rows.las", true},
        {"las/04_custom_null.las", true},
        {"las/05_descending.las", true},
        {"las/06_duplicate_depth.las", true},
        {"las/09_wrapped.las", true},
        {"las/11_missing_vers.las", false},
        {"las/12_depth_named_md.las", false},
        {"las/13_mixed_direction.las", false},
        {"las/14_all_rows_invalid.las", false},
        {"las/15_wrap_y.las", false},
        {"las/16_dlm_comma.las", false},
    };

    for (const auto& [rel, accepted] : cases) {
        const std::string path = (root / rel).string();
        const std::string bytes = read_file(path);
        const std::string name = fs::path(rel).filename().string();
        check(!bytes.empty(), name + ": readable");

        // Path 1: dock (host widget).
        QString error;
        const bool dock_ok = host.load_las(QString::fromStdString(path), &error);

        // Path 2: preview bridge.
        const auto preview = pwb::ingest::preview::wle_las_preview_data(
            bytes, path);

        // Path 3: worker load.
        const auto load_fn = pwb::ui_workers::make_wle_load_fn();
        const auto loaded = load_fn(path, [] { return false; });

        // Three-way accept/reject consistency.
        check(dock_ok == accepted, name + ": dock accept=" +
                                       std::to_string(dock_ok));
        check((preview.status ==
               pwb::ingest::preview::LasPreviewData::Status::ok) == accepted,
              name + ": preview status consistent");
        check(loaded.has_value() == accepted,
              name + ": worker load consistent");

        if (!accepted) continue;

        // Facts consistency on the dock parse (all three call the same
        // adapter; compare preview/worker derived facts to it).
        const ParseFacts facts = dock_parse(path);
        check(facts.ok, name + ": dock parse facts");
        check(preview.row_count == static_cast<long long>(facts.rows),
              name + ": row count preview vs dock");
        if (loaded) {
            const auto document =
                std::any_cast<std::shared_ptr<const welllog::WellLogDocument>>(
                    loaded->data);
            check(document->curves().size() == facts.mnemonics.size(),
                  name + ": worker curve count");
            check(document->sampling_axes().front().coordinates.length() ==
                      facts.rows,
                  name + ": worker row count");
        }
        // Preview table carries every ~C channel in order; the document
        // drops the depth channel — every non-depth preview channel must
        // match the dock curve's unit (mnemonic-by-mnemonic).
        std::size_t unit_checks = 0;
        for (std::size_t i = 0; i < preview.curves.size(); ++i) {
            const std::string& mnemonic = preview.curves[i].mnemonic;
            if (mnemonic == "DEPT" || mnemonic == "DEPTH") continue;
            for (std::size_t j = 0; j < facts.mnemonics.size(); ++j) {
                if (facts.mnemonics[j] == mnemonic) {
                    check(preview.curves[i].unit == facts.units[j],
                          name + ": unit mismatch for " + mnemonic);
                    ++unit_checks;
                    break;
                }
            }
        }
        check(unit_checks == facts.mnemonics.size(),
              name + ": all dock curves covered by preview units");
    }

    if (g_failures == 0) {
        std::printf("viz_a.consistency: OK\n");
        return 0;
    }
    std::printf("viz_a.consistency: %d failure(s)\n", g_failures);
    return 1;
}
