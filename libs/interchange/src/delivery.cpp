// Implementation of delivery.hpp — branch-for-branch port of
// paleo_workbench/interchange/delivery.py. Message strings and JSON key
// order match the Python source (house convention for ports).
#include <pwb/interchange/delivery.hpp>

#include <algorithm>
#include <fstream>
#include <stdexcept>

#include <pwb/interchange/atomic_file.hpp>
#include <pwb/domain/diagnostics.hpp>

namespace pwb::interchange {

Json DeliveryProfile::to_json() const {
    Json out = Json::object();
    out["profile_id"] = profile_id;
    out["display_name"] = display_name;
    out["description"] = description;
    out["external_policy"] = std::string(to_string(external_policy));
    out["include_outputs_only"] = include_outputs_only;
    out["include_formats"] =
        include_formats.has_value() ? Json(*include_formats) : Json(nullptr);
    out["include_provenance"] = include_provenance;
    out["container"] = container;
    out["verify_package"] = verify_package;
    out["report_formats"] = report_formats;
    return out;
}

DeliveryProfile DeliveryProfile::from_json(const Json& data) {
    DeliveryProfile profile;
    profile.profile_id = data.value("profile_id", "");
    profile.display_name = data.value("display_name", profile.profile_id);
    profile.description = data.value("description", std::string());
    const std::string policy = data.value("external_policy", "keep");
    if (policy == "keep") profile.external_policy = ExternalPolicy::KEEP;
    else if (policy == "vendor") profile.external_policy = ExternalPolicy::VENDOR;
    else if (policy == "exclude") profile.external_policy = ExternalPolicy::EXCLUDE;
    else {
        // Python ExternalPolicy(...) raises ValueError on unknown values.
        throw std::invalid_argument("无效外部策略: '" + policy + "'");
    }
    profile.include_outputs_only = data.value("include_outputs_only", false);
    if (data.contains("include_formats") && data["include_formats"].is_array() &&
        !data["include_formats"].empty()) {
        std::vector<std::string> formats;
        for (const auto& value : data["include_formats"]) {
            formats.push_back(value.get<std::string>());
        }
        profile.include_formats = std::move(formats);
    }
    profile.include_provenance = data.value("include_provenance", true);
    profile.container = data.value("container", std::string("directory"));
    profile.verify_package = data.value("verify_package", true);
    if (data.contains("report_formats") && data["report_formats"].is_array()) {
        // Python keeps an explicit empty tuple (writes no reports at all);
        // only the absent key defaults to {"json", "md"}.
        profile.report_formats.clear();
        for (const auto& value : data["report_formats"]) {
            profile.report_formats.push_back(value.get<std::string>());
        }
    }
    return profile;
}

const std::vector<DeliveryProfile>& builtin_profiles() {
    static const std::vector<DeliveryProfile> profiles = [] {
        DeliveryProfile internal;
        internal.profile_id = "internal-archive";
        internal.display_name = "内部工程归档";
        internal.description = "完整工程：全部受管数据 + provenance + 依赖审计；外部引用保持引用";
        DeliveryProfile reviewer;
        reviewer.profile_id = "reviewer-package";
        reviewer.display_name = "评审包";
        reviewer.description = "面向评审：成果输出（OUTPUT）+ 工程描述，不含中间数据";
        reviewer.include_outputs_only = true;
        DeliveryProfile paper;
        paper.profile_id = "paper-figure-package";
        paper.display_name = "论文图件包";
        paper.description = "图件交付：图/导出件（PNG/SVG/PDF/GeoJSON）";
        paper.include_formats = std::vector<std::string>{"png", "svg", "pdf", "geojson"};
        paper.include_provenance = false;
        DeliveryProfile gis;
        gis.profile_id = "gis-exchange";
        gis.display_name = "GIS 交换包";
        gis.description = "GIS 互操作：矢量/栅格交付格式";
        gis.include_formats =
            std::vector<std::string>{"geojson", "shp_bundle", "tif", "tiff"};
        gis.include_provenance = false;
        DeliveryProfile modeling;
        modeling.profile_id = "modeling-handoff";
        modeling.display_name = "建模交接包";
        modeling.description = "数值建模交接：FLAC3D/Abaqus 网格与因子网格";
        modeling.include_formats =
            std::vector<std::string>{"f3grid", "inp", "factor_grid"};
        modeling.include_provenance = false;
        return std::vector<DeliveryProfile>{
            std::move(internal), std::move(reviewer), std::move(paper),
            std::move(gis), std::move(modeling)};
    }();
    return profiles;
}

DeliveryProfile get_profile(const std::string& profile_id) {
    for (const auto& profile : builtin_profiles()) {
        if (profile.profile_id == profile_id) return profile;
    }
    std::vector<std::string> sorted;
    for (const auto& profile : builtin_profiles()) {
        sorted.push_back(profile.profile_id);
    }
    std::sort(sorted.begin(), sorted.end());
    std::string joined;
    for (const auto& id : sorted) {
        if (!joined.empty()) joined += ", ";
        joined += "'" + id + "'";
    }
    throw UnknownDeliveryProfileError("未知交付配置: " + profile_id +
                                      "（可用: [" + joined + "]）");
}

Json DeliveryReportBuilder::build(
    const DeliveryProfile& profile,
    const std::optional<std::filesystem::path>& package_dir,
    const Json& plan_summary,
    const std::optional<DependencyAuditReport>& audit) {
    Json report = Json::object();
    report["kind"] = "paleo-delivery-report";
    report["generated_at"] = pwb::domain::now_iso8601();
    Json application = Json::object();
    application["name"] = "paleo-workbench";
    application["version"] = application_version_;
    report["application"] = std::move(application);
    Json project = Json::object();
    project["name"] = project_path_.filename().string();
    project["path"] = project_path_.filename().string();
    report["project"] = std::move(project);
    report["profile"] = profile.to_json();
    Json package = Json::object();
    package["plan"] = plan_summary;
    report["package"] = std::move(package);
    report["assets"] = asset_inventory();
    report["crs"] = collect_crs();
    report["warnings"] = Json::array();
    if (audit.has_value()) {
        report["dependencies"] = audit->to_json();
        // Python parity: all missing-dependency warnings first, then all
        // content-change warnings (two passes, not interleaved).
        for (const auto& record : audit->records) {
            if (record.status == DependencyStatus::MISSING) {
                report["warnings"].push_back("缺失依赖: " + record.asset_name +
                                             " (" + record.path + ")");
            }
        }
        for (const auto& record : audit->records) {
            if (record.status == DependencyStatus::CHANGED) {
                report["warnings"].push_back("内容变化: " + record.asset_name +
                                             " (" + record.detail + ")");
            }
        }
    }
    if (package_dir.has_value()) {
        const PackageVerifyReport verify = verify_package(*package_dir);
        report["package"]["verified"] = verify.ok();
        report["package"]["verify_state"] =
            verify.ok() ? std::string("VERIFIED") : std::string("FAILED");
        report["package"]["checked_entries"] = verify.checked_entries;
        report["package"]["total_size_bytes"] = verify.total_size_bytes;
        report["package"]["issues"] = Json::array();
        for (const auto& issue : verify.issues) {
            report["package"]["issues"].push_back(issue.to_dict());
        }
        if (!verify.ok()) {
            report["warnings"].push_back("包校验失败：详见 package.issues");
        }
    } else {
        report["package"]["verified"] = false;
        report["package"]["verify_state"] = "UNVERIFIED";
    }
    return report;
}

Json DeliveryReportBuilder::asset_inventory() const {
    if (catalog_ == nullptr) {
        Json out = Json::object();
        out["count"] = 0;
        out["by_type"] = Json::object();
        out["versions_by_stage"] = Json::object();
        return out;
    }
    Json by_type = Json::object();
    Json versions_by_stage = Json::object();
    std::vector<std::string> names;
    for (const auto& asset : catalog_->list_assets()) {
        by_type[asset.type] = by_type.value(asset.type, 0) + 1;
        names.push_back(asset.name);
        for (const auto& version : catalog_->list_versions(asset.id)) {
            versions_by_stage[version.stage] =
                versions_by_stage.value(version.stage, 0) + 1;
        }
    }
    std::sort(names.begin(), names.end());
    Json out = Json::object();
    out["count"] = static_cast<long long>(names.size());
    out["by_type"] = std::move(by_type);
    out["versions_by_stage"] = std::move(versions_by_stage);
    Json preview = Json::array();
    for (std::size_t i = 0; i < names.size() && i < 200; ++i) {
        preview.push_back(names[i]);
    }
    out["names_preview"] = std::move(preview);
    return out;
}

std::vector<std::string> DeliveryReportBuilder::collect_crs() const {
    std::vector<std::string> crs;
    auto add = [&crs](const std::string& value) {
        if (value.empty()) return;
        if (std::find(crs.begin(), crs.end(), value) == crs.end()) {
            crs.push_back(value);
        }
    };
    if (catalog_ != nullptr) {
        for (const auto& asset : catalog_->list_assets()) {
            for (const auto& version : catalog_->list_versions(asset.id)) {
                if (version.metadata.contains("crs") &&
                    version.metadata["crs"].is_string()) {
                    add(version.metadata["crs"].get<std::string>());
                }
            }
        }
    }
    std::error_code ec;
    if (std::filesystem::is_regular_file(project_path_, ec)) {
        std::ifstream stream(project_path_);
        if (stream) {
            std::string text((std::istreambuf_iterator<char>(stream)),
                             std::istreambuf_iterator<char>());
            const Json document = Json::parse(text, nullptr, false);
            if (!document.is_discarded() && document.is_object()) {
                if (document.contains("coordinate") &&
                    document["coordinate"].is_object()) {
                    const Json& coordinate = document["coordinate"];
                    for (const char* key :
                         {"project_crs", "target_crs", "display_crs"}) {
                        if (coordinate.contains(key) &&
                            coordinate[key].is_string()) {
                            add(coordinate[key].get<std::string>());
                        }
                    }
                }
                if (document.contains("resources") &&
                    document["resources"].is_array()) {
                    for (const auto& resource : document["resources"]) {
                        if (resource.is_object() && resource.contains("crs") &&
                            resource["crs"].is_string()) {
                            add(resource["crs"].get<std::string>());
                        }
                    }
                }
            }
        }
    }
    std::sort(crs.begin(), crs.end());
    return crs;
}

// Python str(dict) rendering for small JSON objects in the markdown report:
// {'EPSG:4326': 1, 'las': 2} — single quotes, insertion order, str() on
// string values.
std::string python_dict_repr(const Json& node) {
    if (!node.is_object()) return node.dump();
    std::string out = "{";
    bool first = true;
    for (auto it = node.begin(); it != node.end(); ++it) {
        if (!first) out += ", ";
        first = false;
        out += "'" + it.key() + "': ";
        if (it.value().is_string()) {
            out += "'" + it.value().get<std::string>() + "'";
        } else if (it.value().is_object()) {
            out += python_dict_repr(it.value());
        } else {
            out += it.value().dump();
        }
    }
    return out + "}";
}

std::string render_report_markdown(const Json& report) {
    std::vector<std::string> lines;
    const Json empty = Json::object();
    const Json& project = report.value("project", empty);
    const Json& app = report.value("application", empty);
    const Json& profile = report.value("profile", empty);
    const Json& package = report.value("package", empty);
    lines.emplace_back("# 交付 QA 报告");
    lines.emplace_back("");
    lines.push_back("- 工程: " + project.value("name", std::string("?")));
    lines.push_back("- 生成时间: " + report.value("generated_at", std::string("?")));
    lines.push_back("- 软件版本: " + app.value("name", std::string("?")) + " " +
                    app.value("version", std::string("?")));
    lines.push_back("- 交付配置: " + profile.value("display_name", std::string("?")) +
                    " (" + profile.value("profile_id", std::string("?")) + ")");
    lines.push_back("- 包校验状态: **" +
                    package.value("verify_state", std::string("UNVERIFIED")) +
                    "**");
    lines.push_back("- 包大小: " +
                    std::to_string(package.value("total_size_bytes", 0LL)) +
                    " 字节 / " +
                    std::to_string(package.value("checked_entries", 0LL)) +
                    " 条目");
    lines.emplace_back("");
    const Json& assets = report.value("assets", empty);
    lines.emplace_back("## 资产");
    lines.push_back("- 资产数量: " + std::to_string(assets.value("count", 0)));
    lines.push_back("- 类型分布: " + python_dict_repr(assets.value("by_type", Json::object())));
    lines.push_back("- 版本阶段分布: " +
                    python_dict_repr(assets.value("versions_by_stage", Json::object())));
    if (report.contains("crs") && report["crs"].is_array() &&
        !report["crs"].empty()) {
        lines.emplace_back("");
        lines.emplace_back("## 坐标系");
        for (const auto& crs : report["crs"]) {
            lines.push_back("- " + crs.get<std::string>());
        }
    }
    if (report.contains("dependencies")) {
        lines.emplace_back("");
        lines.emplace_back("## 依赖审计");
        const Json& dependencies = report["dependencies"];
        lines.push_back("- 汇总: " +
                        python_dict_repr(dependencies.value("counts", Json::object())));
        if (dependencies.contains("records") && dependencies["records"].is_array()) {
            for (const auto& record : dependencies["records"]) {
                const std::string status = record.value("status", std::string());
                if (status != "valid" && status != "unknown") {
                    lines.push_back("- ⚠ " + status + ": " +
                                    record.value("asset", std::string()) + " — " +
                                    record.value("path", std::string()));
                }
            }
        }
    }
    if (report.contains("warnings") && report["warnings"].is_array() &&
        !report["warnings"].empty()) {
        lines.emplace_back("");
        lines.emplace_back("## 警告");
        for (const auto& warning : report["warnings"]) {
            lines.push_back("- " + warning.get<std::string>());
        }
    }
    lines.emplace_back("");
    std::string out;
    for (std::size_t i = 0; i < lines.size(); ++i) {
        if (i != 0) out += "\n";
        out += lines[i];
    }
    return out;
}

DeliveryResult DeliveryService::build(const DeliveryProfile& profile,
                                      const std::filesystem::path& output_dir,
                                      const CancelToken& cancel,
                                      ProgressCallback progress) const {
    DeliveryResult result;
    result.profile_id = profile.profile_id;
    PackageBuilder builder(
        project_path_, catalog_,
        PackageOptions{profile.external_policy, profile.include_outputs_only,
                       profile.include_formats, profile.include_provenance},
        application_version_);
    const PackagePlan plan = builder.plan();
    result.plan_summary = plan.summary();
    // Directory first: reports are written INTO the package so even the zip
    // container ships with its QA report.
    const BuildResult build = builder.build(output_dir, cancel, progress);
    result.package_dir = build.package_dir;

    std::optional<DependencyAuditReport> audit;
    if (catalog_ != nullptr) {
        audit = ExternalDependencyAuditor(catalog_).audit(cancel);
    }
    DeliveryReportBuilder report_builder(project_path_, catalog_,
                                         application_version_);
    Json report = report_builder.build(
        profile,
        profile.verify_package ? result.package_dir : std::nullopt,
        result.plan_summary, audit);
    result.report = report;
    result.verify_ok = report["package"].value("verified", false);

    // _write_reports: atomically publish the report files into the package.
    if (result.package_dir.has_value() && !profile.report_formats.empty()) {
        if (std::find(profile.report_formats.begin(), profile.report_formats.end(),
                      "json") != profile.report_formats.end()) {
            const std::filesystem::path json_path = *result.package_dir / "delivery-report.json";
            const std::filesystem::path tmp = *result.package_dir / ".delivery-report.json.tmp";
            std::ofstream stream(tmp, std::ios::binary | std::ios::trunc);
            if (!stream) {
                throw std::runtime_error("无法写入报告临时文件: " + tmp.string());
            }
            stream << report.dump(1);
            stream.close();
            os_replace_atomic(tmp, json_path);
            result.report_path = json_path;
        }
        if (std::find(profile.report_formats.begin(), profile.report_formats.end(),
                      "md") != profile.report_formats.end()) {
            const std::filesystem::path md_path = *result.package_dir / "delivery-report.md";
            const std::filesystem::path tmp = *result.package_dir / ".delivery-report.md.tmp";
            std::ofstream stream(tmp, std::ios::binary | std::ios::trunc);
            if (!stream) {
                throw std::runtime_error("无法写入报告临时文件: " + tmp.string());
            }
            stream << render_report_markdown(report);
            stream.close();
            os_replace_atomic(tmp, md_path);
            result.report_markdown_path = md_path;
        }
    }
    if (profile.container == "zip") {
        result.container_path =
            zip_package_dir(*result.package_dir,
                            output_dir / (builder.project_name() + ".paleopkg.zip"),
                            cancel);
    }
    return result;
}

}  // namespace pwb::interchange
