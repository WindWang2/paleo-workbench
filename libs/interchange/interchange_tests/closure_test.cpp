// interchange.closure — the line-10 composition acceptance: 导入探测 →
// 配置校验 → native 执行 → 输出登记 → 可移植包导入导出. Covers the export
// round trip through the guarded pipeline (plan → execute → verify →
// register, FLAC3D/Abaqus), the batch orchestration (deterministic naming,
// collision suffixes, failure isolation), the package build→import round
// trip through the registration sink, and the reproducible failure
// behaviors (traversal container, missing path, unknown format).

#include <cstdio>
#include <fstream>
#include <memory>
#include <string>
#include <vector>

#include <pwb/interchange/closure.hpp>
#include <pwb/interchange/zip_archive.hpp>

namespace pic = pwb::interchange::closure;
namespace pi = pwb::interchange;
using pwb::domain::Json;

int g_failures = 0;
int g_checks = 0;

void check(bool ok, const std::string& what) {
    ++g_checks;
    if (!ok) {
        std::fprintf(stderr, "FAIL %s\n", what.c_str());
        ++g_failures;
    }
}

std::string g_dir;

void write_file(const std::string& name, const std::string& content) {
    const std::string path = g_dir + "/" + name;
    const std::size_t slash = path.rfind('/');
    std::filesystem::create_directories(path.substr(0, slash));
    std::ofstream stream(path, std::ios::binary | std::ios::trunc);
    stream << content;
}

// Registration sink capturing every call (stands in for the line-01
// catalog-backed surface).
class RecordingSink final : public pic::IRegistrationSink {
public:
    std::string register_import(const pi::ImportPlan& plan,
                                const std::filesystem::path& materialized) override {
        imports.push_back({plan.format_id, plan.action, materialized.string()});
        return "reg-import-" + std::to_string(imports.size());
    }
    std::string register_export(const pi::ExportPlan& plan,
                                const std::filesystem::path& output,
                                const pi::ExportVerification& verification) override {
        exports.push_back({plan.format_id,
                           std::string(pwb::interchange::to_string(verification.state)),
                           output.string()});
        return "reg-export-" + std::to_string(exports.size());
    }

    struct Entry {
        std::string format_id;
        std::string action_or_state;
        std::string path;
    };
    std::vector<Entry> imports;
    std::vector<Entry> exports;
};

int main() {
    g_dir = (std::filesystem::temp_directory_path() / "pwb_interchange_closure_test")
                .string();
    std::filesystem::remove_all(g_dir);
    std::filesystem::create_directories(g_dir);
    write_file("project/demo.paleo.json",
               R"({"name": "demo", "coordinate": {"project_crs": "EPSG:4326"}})");

    RecordingSink sink;
    pic::InterchangeClosureConfig config;
    config.workspace_root = g_dir + "/workspace";
    config.project_path = g_dir + "/project/demo.paleo.json";
    config.application_version = "0.2.17a0";
    std::filesystem::create_directories(config.workspace_root);
    auto closure = pic::closure_interchange_install(config, &sink);

    // --- 能力报告：格式与交付配置（04/09/12 消费面） ---------------------------
    {
        const Json report = pic::closure_interchange_capability_report(*closure);
        bool has_flac3d = false;
        bool has_abaqus = false;
        for (const auto& format : report["formats"]) {
            has_flac3d |= format == "flac3d_f3grid";
            has_abaqus |= format == "abaqus_inp";
        }
        check(has_flac3d && has_abaqus, "capability report lists model formats");
        check(report["delivery_profiles"].size() == 5, "five delivery profiles");
        check(report["package_runtime"].value("container_zip", false),
              "zip container capability declared");
    }

    // --- 导出闭环：plan → native 执行 → verify（复读 round-trip） → 登记 ------
    {
        const auto outcome = closure->export_as(
            g_dir + "/workspace/model.f3grid", "flac3d_f3grid",
            g_dir + "/workspace/model.f3grid",
            Json{{"nx", 4}, {"ny", 3}, {"nz", 2}});
        check(outcome.ok, "flac3d export verified");
        check(outcome.verification.state == pi::VerificationState::VERIFIED,
              "round-trip re-parse VERIFIED");
        check(!outcome.registration_id.empty(), "export registered");
        check(sink.exports.size() == 1 &&
                  sink.exports.back().format_id == "flac3d_f3grid",
          "sink captured the export");
        check(sink.exports.back().action_or_state == "VERIFIED",
              "sink saw VERIFIED state");

        // Same target through the abaqus adapter.
        const auto abq = closure->export_as(
            g_dir + "/workspace/model.inp", "abaqus_inp", g_dir + "/workspace/model.inp",
            Json{{"nx", 2}, {"ny", 2}, {"nz", 2}});
        check(abq.ok && abq.verification.state == pi::VerificationState::VERIFIED,
              "abaqus export verified");

        // 未知格式：typed 拒绝。
        std::string error;
        try {
            closure->export_as("x", "las", "x.csv", Json::object());
        } catch (const std::exception& exc) {
            error = exc.what();
        }
        check(!error.empty(), "unknown format refused");

        // 负面自检：篡改导出物 → 复读校验 FAILED。
        {
            std::ofstream stream(g_dir + "/workspace/model.f3grid",
                                 std::ios::binary | std::ios::trunc);
            stream << "G 1 0 0 0\ncorrupted\n";
        }
        const auto tampered = closure->interchange().verify_output(
            g_dir + "/workspace/model.f3grid",
            closure->interchange().plan_export(
                "flac3d_f3grid", g_dir + "/workspace/model.f3grid",
                g_dir + "/workspace/model.f3grid",
                Json{{"nx", 4}, {"ny", 3}, {"nz", 2}}));
        check(tampered.state == pi::VerificationState::FAILED,
              "tampered export fails re-verification");
    }

    // --- 批量转换：确定性命名、冲突后缀、失败隔离 ------------------------------
    {
        std::vector<pi::ConversionJob> jobs;
        pi::ConversionJob first;
        first.source = g_dir + "/workspace/a.f3grid";
        first.target_format = "abaqus_inp";
        first.target_name = "same.inp";
        first.options = Json{{"nx", 2}, {"ny", 2}, {"nz", 2}};
        jobs.push_back(first);
        pi::ConversionJob second = first;
        second.source = g_dir + "/workspace/b.f3grid";
        jobs.push_back(second);
        pi::ConversionJob unknown;
        unknown.source = g_dir + "/workspace/a.f3grid";
        unknown.target_format = "xlsx";  // no export capability natively
        unknown.options = Json::object();
        jobs.push_back(unknown);
        pi::ConversionJob bad_options;
        bad_options.source = g_dir + "/workspace/a.f3grid";
        bad_options.target_format = "abaqus_inp";
        bad_options.options = Json::object();  // 缺少 nx/ny/nz → 拒绝
        jobs.push_back(bad_options);

        const auto [estimated, warnings] = closure->batch().estimate(jobs, g_dir + "/batch");
        check(estimated > 0, "estimate covers exportable jobs");
        check(warnings.size() == 2,
              "estimate warns for unknown format and invalid options");

        const pi::BatchResult result =
            closure->batch().convert(jobs, g_dir + "/batch");
        check(result.results.size() == 4, "one result per job");
        int converted = 0;
        int skipped = 0;
        int failed = 0;
        for (const auto& item : result.results) {
            converted += item.status == "converted";
            skipped += item.status == "skipped";
            failed += item.status == "failed";
        }
        check(converted == 2, "both real jobs converted");
        check(skipped == 1, "unknown format skipped");
        check(failed == 1, "invalid-options job failed in isolation");
        // Deterministic collision suffix -2 (casefold).
        bool saw_suffix = false;
        for (const auto& item : result.results) {
            saw_suffix |= item.target.find("same-2.inp") != std::string::npos;
        }
        check(saw_suffix, "target collision suffixed -2");
        check(!sink.exports.empty(), "batch exports registered via the sink");
    }

    // --- 可移植包 round trip：build → import → 登记 ----------------------------
    {
        const pi::DeliveryResult delivered = closure->build_delivery(
            "internal-archive", g_dir + "/delivery-out");
        check(delivered.verify_ok, "delivery verified");
        check(!delivered.report_path->empty(), "report written into package");

        // Re-import the package directory through the closure.
        const auto imported = closure->import_path(*delivered.package_dir,
                                                   g_dir + "/import-dir");
        check(imported.ok && imported.kind == "package", "package re-imported");
        check(imported.verify_report.ok(), "import verify report ok");
        check(!imported.registration_id.empty(), "import registered");
        check(sink.imports.size() == 1 &&
                  sink.imports.back().action_or_state == "managed_copy",
              "sink captured managed_copy import");

        // Zip container import.
        pi::DeliveryProfile zip_profile = pi::get_profile("internal-archive");
        zip_profile.container = "zip";
        const pi::DeliveryResult zipped = closure->build_delivery_profile(
            zip_profile, g_dir + "/delivery-zip");
        check(zipped.container_path.has_value() &&
                  std::filesystem::exists(*zipped.container_path),
              "zip container built");
        if (zipped.container_path.has_value()) {
            const auto from_zip = closure->import_path(*zipped.container_path,
                                                       g_dir + "/import-zip");
            check(from_zip.ok && from_zip.kind == "package",
                  "zip package imported");
            check(sink.imports.size() == 2, "both imports registered");
        }

        // 失败行为：路径穿越容器 fail-closed（先全校验后写盘）。
        {
            const std::filesystem::path evil_zip =
                std::filesystem::path(g_dir) / "evil.zip";
            {
                pwb::interchange::ZipWriter writer(evil_zip);
                writer.add_bytes("manifest.json",
                                 "{\"kind\": \"paleo-package\", \"schema_version\": 2}");
                writer.add_bytes("../escape.txt", "payload");
                writer.finish();
            }
            std::string error;
            const auto evil = closure->import_path(evil_zip, g_dir + "/import-evil");
            check(!evil.ok, "traversal container rejected");
            check(!evil.warnings.empty(), "traversal container explains why");
            error = evil.warnings.empty() ? "" : evil.warnings.front();
            check(error.find("escape") != std::string::npos ||
                      error.find("穿越") != std::string::npos ||
                      error.find("unsafe") != std::string::npos,
                  "traversal reason surfaces: " + error);
            check(!std::filesystem::exists(std::filesystem::path(g_dir) /
                                           "escape.txt"),
                  "nothing escaped the destination");
        }

        // 失败行为：缺失路径 → 结构化 missing，不抛异常。
        const auto missing = closure->import_path(g_dir + "/nowhere",
                                                  g_dir + "/import-nowhere");
        check(!missing.ok && missing.kind == "missing", "missing path structured");
    }

    std::filesystem::remove_all(g_dir);
    if (g_failures == 0) {
        std::printf("interchange.closure: %d checks passed\n", g_checks);
        return 0;
    }
    std::fprintf(stderr, "interchange.closure: %d/%d checks FAILED\n", g_failures,
                 g_checks);
    return 1;
}
