// interchange.delivery — line-10 port of delivery.py: the five built-in
// profiles, get_profile refusal message, package build per profile, the QA
// report (JSON key facts + markdown rendering), CRS collection from the
// project document and catalog metadata, the zip container, and honest
// UNVERIFIED/FAILED reporting when verification is off or the package is
// tampered with (negative self-check).

#include <cstdio>
#include <fstream>
#include <string>
#include <vector>

#include <pwb/interchange/delivery.hpp>
#include <pwb/interchange/zip_archive.hpp>

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

template <typename Fn>
std::string expect_throw(Fn&& fn) {
    try {
        fn();
    } catch (const std::exception& exc) {
        return exc.what();
    }
    return "<no throw>";
}

std::string g_dir;

void write_file(const std::string& name, const std::string& content) {
    const std::filesystem::path path = std::filesystem::path(g_dir) / name;
    std::filesystem::create_directories(path.parent_path());
    std::ofstream stream(path, std::ios::binary | std::ios::trunc);
    stream << content;
}

std::optional<std::string> find_in_dir(const std::filesystem::path& dir,
                                       const std::string& filename) {
    for (auto it = std::filesystem::recursive_directory_iterator(dir);
         it != std::filesystem::recursive_directory_iterator(); ++it) {
        if (it->is_regular_file() && it->path().filename() == filename) {
            return it->path().string();
        }
    }
    return std::nullopt;
}

std::string read_text(const std::filesystem::path& path) {
    std::ifstream stream(path);
    return std::string((std::istreambuf_iterator<char>(stream)),
                       std::istreambuf_iterator<char>());
}

class FakeCatalog final : public pi::ILinkableCatalog {
public:
    std::vector<pi::CatalogAssetRef> list_assets() override {
        return {{"a1", "demo-asset", "raw"}};
    }
    std::vector<pi::CatalogVersionRef> list_versions(const std::string&) override {
        pi::CatalogVersionRef version;
        version.id = "v1";
        version.asset_id = "a1";
        version.stage = "input";
        version.managed = true;
        version.format = "las";
        version.path = "payload/demo.las";
        version.size_bytes =
            static_cast<long long>(std::filesystem::file_size(payload));
        version.sha256 = *pi::sha256_file(payload);
        Json metadata = Json::object();
        metadata["crs"] = "EPSG:4269";
        version.metadata = std::move(metadata);
        return {version};
    }
    std::filesystem::path resolve_path(const pi::CatalogVersionRef&) override {
        return payload;
    }
    pi::ILinkableCatalog::LinkResult link_external(const std::filesystem::path&,
                                                   const std::string&,
                                                   Json) override {
        return {"", ""};
    }

    std::filesystem::path payload;
};

int main() {
    g_dir = (std::filesystem::temp_directory_path() / "pwb_interchange_delivery_test")
                .string();
    std::filesystem::remove_all(g_dir);
    std::filesystem::create_directories(g_dir + "/project");
    write_file("project/demo.paleo.json",
               R"({"coordinate": {"project_crs": "EPSG:4326"},
"resources": [{"name": "r1", "crs": "EPSG:3857"}]})");
    // Managed payloads live under <project>.artifacts/<dir>/ — the builder
    // copies that tree, exactly like the Python builder.
    write_file("project/demo.artifacts/raw/payload/demo.las", "~V\nVERS. 2.0\n~A\n");

    FakeCatalog catalog;
    catalog.payload =
        g_dir + "/project/demo.artifacts/raw/payload/demo.las";

    // --- profiles ------------------------------------------------------------
    check(pi::builtin_profiles().size() == 5, "five built-in profiles");
    check(pi::get_profile("reviewer-package").include_outputs_only,
          "reviewer package is outputs-only");
    check(pi::get_profile("modeling-handoff").include_formats.has_value() &&
              (*pi::get_profile("modeling-handoff").include_formats)[0] == "f3grid",
          "modeling handoff formats");
    const std::string unknown =
        expect_throw([&] { pi::get_profile("nope"); });
    check(unknown.find("未知交付配置: nope") != std::string::npos,
          "unknown profile message: " + unknown);
    check(unknown.find("gis-exchange") != std::string::npos &&
              unknown.find("reviewer-package") != std::string::npos,
          "unknown profile lists sorted options: " + unknown);
    check(pi::DeliveryProfile::from_json(
              pi::get_profile("paper-figure-package").to_json())
                  .profile_id == "paper-figure-package",
          "profile json round trip");

    // --- full delivery build with catalog ------------------------------------
    const pi::DeliveryService service(g_dir + "/project/demo.paleo.json", &catalog,
                                      "0.2.17a0");
    const std::string out_dir = g_dir + "/deliveries";
    const pi::DeliveryResult result =
        service.build(pi::get_profile("internal-archive"), out_dir);
    check(result.package_dir.has_value() &&
              std::filesystem::is_directory(*result.package_dir),
          "package directory built");
    check(result.verify_ok, "delivery verified");
    check(std::filesystem::exists(*result.package_dir / "manifest.json"),
          "manifest shipped");
    check(std::filesystem::exists(*result.package_dir / "demo.paleo.json"),
          "project document shipped");
    check(find_in_dir(*result.package_dir, "demo.las").has_value(),
          "managed payload shipped");

    // Report files live inside the package.
    check(result.report_path.has_value() &&
              std::filesystem::exists(*result.report_path),
          "json report in package");
    check(result.report_markdown_path.has_value() &&
              std::filesystem::exists(*result.report_markdown_path),
          "markdown report in package");
    Json report = Json::parse(read_text(*result.report_path));
    check(!report.is_discarded(), "json report parses");
    check(report.value("kind", "") == "paleo-delivery-report", "report kind");
    check(report["application"].value("version", "") == "0.2.17a0",
          "application version injected");
    check(report["package"].value("verified", false) == true,
          "report records verified");
    check(report["package"].value("verify_state", "") == "VERIFIED",
          "verify state VERIFIED");
    bool found_crs_4269 = false;
    bool found_crs_4326 = false;
    bool found_crs_3857 = false;
    for (const auto& crs : report["crs"]) {
        found_crs_4269 |= crs == "EPSG:4269";  // catalog version metadata
        found_crs_4326 |= crs == "EPSG:4326";  // project_crs
        found_crs_3857 |= crs == "EPSG:3857";  // resource crs
    }
    check(found_crs_4269 && found_crs_4326 && found_crs_3857,
          "CRS collected from project + catalog + resources");
    check(report["dependencies"].value("total", 0) == 1,
          "dependency audit embedded in report");
    check(report["dependencies"]["records"][0].value("status", "") == "valid",
          "payload dependency audited valid");

    std::ifstream md_stream(*result.report_markdown_path);
    const std::string markdown((std::istreambuf_iterator<char>(md_stream)),
                               std::istreambuf_iterator<char>());
    check(markdown.find("# 交付 QA 报告") != std::string::npos,
          "markdown header");
    check(markdown.find("**VERIFIED**") != std::string::npos,
          "markdown verify state");
    check(markdown.find("内部工程归档") != std::string::npos,
          "markdown profile display name");

    // --- zip container ---------------------------------------------------------
    const std::string zip_out = g_dir + "/deliveries-zip";
    pi::DeliveryProfile zip_profile = pi::get_profile("internal-archive");
    zip_profile.container = "zip";
    const pi::DeliveryResult zip_result =
        service.build(zip_profile, zip_out);
    check(zip_result.container_path.has_value() &&
              std::filesystem::exists(*zip_result.container_path),
          "zip container produced");
    check(zip_result.container_path->filename().string() == "demo.paleopkg.zip",
          "container named <project>.paleopkg.zip: " +
              zip_result.container_path->filename().string());
    const pi::PackageVerifyReport zip_verify =
        pi::verify_package(*zip_result.container_path);
    check(zip_verify.ok(), "zip container verifies");

    // --- tamper → FAILED reaches the report (negative self-check) --------------
    const std::optional<std::string> payload_path =
        find_in_dir(*result.package_dir, "demo.las");
    check(payload_path.has_value(), "payload located for tamper");
    if (payload_path.has_value()) {
        std::ofstream payload(*payload_path, std::ios::binary | std::ios::trunc);
        payload << "TAMPERED-NOT-A-LAS-AT-ALL";
    }
    pi::DeliveryReportBuilder builder(g_dir + "/project/demo.paleo.json", nullptr,
                                      "0.2.17a0");
    const Json tampered_report =
        builder.build(pi::get_profile("internal-archive"), *result.package_dir,
                      {});
    check(tampered_report["package"].value("verified", true) == false,
          "tampered package fails verification");
    check(tampered_report["package"].value("verify_state", "") == "FAILED",
          "tampered verify state FAILED");
    check(!pi::render_report_markdown(tampered_report).empty(),
          "markdown renders FAILED state too");

    // --- UNVERIFIED when verify skipped ----------------------------------------
    pi::DeliveryProfile no_verify = pi::get_profile("internal-archive");
    no_verify.verify_package = false;
    const Json unverified_report =
        builder.build(no_verify, std::nullopt, {});
    check(unverified_report["package"].value("verify_state", "") == "UNVERIFIED",
          "skipped verification reports UNVERIFIED honestly");

    // --- report format subset ---------------------------------------------------
    pi::DeliveryProfile json_only = pi::get_profile("internal-archive");
    json_only.report_formats = {"json"};
    const pi::DeliveryResult json_result = service.build(json_only, g_dir + "/deliveries-json");
    check(json_result.report_path.has_value(), "json report written");
    check(!json_result.report_markdown_path.has_value(),
          "markdown skipped per profile");

    std::filesystem::remove_all(g_dir);
    if (g_failures == 0) {
        std::printf("interchange.delivery: %d checks passed\n", g_checks);
        return 0;
    }
    std::fprintf(stderr, "interchange.delivery: %d/%d checks FAILED\n",
                 g_failures, g_checks);
    return 1;
}
