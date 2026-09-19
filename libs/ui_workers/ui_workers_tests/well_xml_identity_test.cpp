// 05 线 — XML 井曲线数据核 + 共享井身份测试（Qt-free、无 WLE）。
//
// Oracle：fixtures/expected/well_xml_oracle.json（冻结 Python 语义，
// 模式 A 实测 / 模式 B 逐条转录——见 tools/oracle/generate_well_xml_fixtures.py）。
// 含负面自检：比较器对故意错值必须判假（防恒真），篡改输入必须改变输出
//（防硬编码）。

#include <cstdio>
#include <cstdlib>
#include <cmath>
#include <fstream>
#include <sstream>
#include <string>

#include <pwb/domain/json.hpp>
#include <pwb/ui_workers/well_identity.hpp>
#include <pwb/ui_workers/well_log_xml_data.hpp>

#ifndef PWB_UI_WORKERS_XML_FIXTURE_DIR
#define PWB_UI_WORKERS_XML_FIXTURE_DIR "."
#endif

namespace {

int failures = 0;

#define CHECK(cond)                                                    \
    do {                                                               \
        if (!(cond)) {                                                 \
            std::fprintf(stderr, "CHECK 失败 %s:%d: %s\n", __FILE__,   \
                         __LINE__, #cond);                             \
            ++failures;                                                \
        }                                                              \
    } while (false)

std::string read_file(const std::string& path) {
    std::ifstream in(path, std::ios::binary);
    if (!in) {
        std::fprintf(stderr, "无法打开 %s\n", path.c_str());
        std::exit(2);
    }
    std::ostringstream buffer;
    buffer << in.rdbuf();
    return buffer.str();
}

bool close_enough(double a, double b, double tolerance) {
    if (std::isnan(a) && std::isnan(b)) return true;
    return std::fabs(a - b) <= tolerance;
}

bool same_sample_list(const pwb::domain::Json& expected,
                      const std::vector<double>& actual, double tolerance) {
    if (!expected.is_array()) return false;
    if (expected.size() != actual.size()) return false;
    for (std::size_t i = 0; i < actual.size(); ++i) {
        const auto& item = expected.at(i);
        if (item.is_string()) {
            if (item.get<std::string>() != "nan") return false;
            if (!std::isnan(actual[i])) return false;
        } else if (item.is_number()) {
            if (!close_enough(item.get<double>(), actual[i], tolerance)) {
                return false;
            }
        } else {
            return false;
        }
    }
    return true;
}

bool same_interval_list(const pwb::domain::Json& expected,
                        const std::vector<pwb::ui_workers::WellLogXmlInterval>&
                            actual,
                        double tolerance) {
    if (expected.size() != actual.size()) return false;
    for (std::size_t i = 0; i < actual.size(); ++i) {
        const auto& item = expected.at(i);
        if (!close_enough(item.at("top").get<double>(), actual[i].top,
                          tolerance) ||
            !close_enough(item.at("bottom").get<double>(), actual[i].bottom,
                          tolerance) ||
            item.at("label").get<std::string>() != actual[i].label) {
            return false;
        }
    }
    return true;
}

bool case_matches(const pwb::domain::Json& expected,
                  const pwb::ui_workers::WellLogXmlData& data,
                  double tolerance, std::string* why) {
    auto fail = [&](const std::string& reason) {
        *why = reason;
        return false;
    };
    if (expected.at("well_name").get<std::string>() != data.well_name) {
        return fail("well_name");
    }
    if (expected.contains("total_rows") &&
        expected.at("total_rows").is_number() &&
        expected.at("total_rows").get<long>() !=
            static_cast<long>(data.total_rows)) {
        return fail("total_rows");
    }
    if (!close_enough(expected.at("top_depth").get<double>(), data.top_depth,
                      tolerance) ||
        !close_enough(expected.at("bottom_depth").get<double>(),
                      data.bottom_depth, tolerance)) {
        return fail("depth envelope");
    }
    const auto& curves = expected.at("curves");
    if (curves.size() != data.curves.size()) return fail("curve count");
    for (std::size_t c = 0; c < data.curves.size(); ++c) {
        const auto& want = curves.at(c);
        const auto& got = data.curves[c];
        if (want.at("name").get<std::string>() != got.name) {
            return fail("curve name " + got.name);
        }
        if (want.at("unit").get<std::string>() != got.unit) {
            return fail("curve unit " + got.name);
        }
        if (!same_sample_list(want.at("depth"), *got.depth, tolerance) ||
            !same_sample_list(want.at("values"), *got.values, tolerance)) {
            return fail("curve samples " + got.name);
        }
    }
    if (!same_interval_list(expected.at("lithology"), data.lithology,
                            tolerance) ||
        !same_interval_list(expected.at("facies"), data.facies, tolerance) ||
        !same_interval_list(expected.at("formation"), data.formation,
                            tolerance) ||
        !same_interval_list(expected.at("text_desc"), data.text_desc,
                            tolerance) ||
        !same_interval_list(expected.at("horizons"), data.horizons,
                            tolerance)) {
        return fail("intervals");
    }
    return true;
}

}  // namespace

int main() {
    const std::string dir = PWB_UI_WORKERS_XML_FIXTURE_DIR;
    const pwb::domain::Json oracle = pwb::domain::Json::parse(
        read_file(dir + "/expected/well_xml_oracle.json"));
    CHECK(oracle.at("cases").is_object());
    const double tolerance = oracle.at("tolerance").get<double>();

    // 1) 识别 + 解析逐案例对账。
    for (const auto& [name, expected] : oracle.at("cases").items()) {
        const std::string bytes = read_file(dir + "/xml/" + name);
        const bool recognized = pwb::ui_workers::is_well_log_xml_bytes(bytes);
        CHECK(recognized == expected.at("recognized").get<bool>());
        if (!recognized) continue;
        auto data = pwb::ui_workers::parse_well_log_xml(bytes, name);
        std::string why;
        if (!case_matches(expected, data, tolerance, &why)) {
            std::fprintf(stderr, "案例 %s 不一致：%s\n", name.c_str(),
                         why.c_str());
            ++failures;
        }
    }

    // 2) 负面自检 A（比较器不恒真）：把 GR 首样期望改成错值后必须判假。
    {
        auto tampered = oracle.at("cases").at("witsml_basic.xml");
        tampered.at("curves")[0]["values"][0] = 42.3 + 1.0;
        auto data = pwb::ui_workers::parse_well_log_xml(
            read_file(dir + "/xml/witsml_basic.xml"), "witsml_basic.xml");
        std::string why;
        CHECK(!case_matches(tampered, data, tolerance, &why));
    }

    // 3) 负面自检 B（防硬编码）：篡改输入字节必须改变解析输出。
    {
        const std::string bytes =
            read_file(dir + "/xml/witsml_missing_cells.xml");
        auto data = pwb::ui_workers::parse_well_log_xml(bytes, "x.xml");
        CHECK(data.curves.size() == 2);
        std::string tampered = bytes;
        const auto pos = tampered.find("31.5");
        CHECK(pos != std::string::npos);
        tampered.replace(pos, 4, "39.5");
        auto changed = pwb::ui_workers::parse_well_log_xml(tampered, "x.xml");
        CHECK(changed.curves.size() == data.curves.size());
        CHECK((*changed.curves[0].values)[1] != (*data.curves[0].values)[1]);
    }

    // 4) 数据语义错误：全坏深度 → ValueError 语义（std::invalid_argument）。
    {
        const std::string bad =
            "<?xml version=\"1.0\"?><logs><log>"
            "<logCurveInfo><mnemonic>DEPT</mnemonic></logCurveInfo>"
            "<logCurveInfo><mnemonic>GR</mnemonic></logCurveInfo>"
            "<logData><data>bad, worse</data></logData>"
            "</log></logs>";
        CHECK(pwb::ui_workers::is_well_log_xml_bytes(bad));
        bool threw = false;
        try {
            (void)pwb::ui_workers::parse_well_log_xml(bad, "bad.xml");
        } catch (const std::invalid_argument&) {
            threw = true;
        }
        CHECK(threw);
    }

    // 5) 共享井身份：规范化、确定性 id、first-wins、空名拒绝。
    {
        using pwb::ui_workers::WellIdentityRegistry;
        using pwb::ui_workers::well_identity_id;
        using pwb::ui_workers::well_identity_key;
        auto& registry = WellIdentityRegistry::instance();
        registry.clear_for_tests();

        CHECK(well_identity_key("  W-1  ") == "w-1");
        CHECK(well_identity_key("W\t 1") == "w 1");
        CHECK(well_identity_key("井 A") == "井 a");
        CHECK(well_identity_key("   ") == "");
        // 确定性：同键任意次求值同 id；跨键不同 id。
        const std::string id1 = well_identity_id("w-1");
        CHECK(id1 == well_identity_id("w-1"));
        CHECK(id1 != well_identity_id("w-2"));
        CHECK(id1.rfind("wi-", 0) == 0);
        CHECK(id1.size() == 3 + 32);

        auto first = registry.register_well("  W-1  ", "well_log_page");
        CHECK(first.has_value());
        CHECK(first->key == "w-1");
        CHECK(first->name == "  W-1  ");
        CHECK(first->origin == "well_log_page");
        CHECK(first->well_id == id1);
        // 同键幂等：第二个注册者拿不到所有权（first-wins），id 一致。
        auto second = registry.register_well("w-1", "cross_well");
        CHECK(second.has_value());
        CHECK(second->well_id == first->well_id);
        CHECK(second->origin == "well_log_page");
        // 查询面（04/06 消费口）。
        CHECK(registry.find("w-1").has_value());
        CHECK(registry.find_by_name("W-1").has_value());
        CHECK(!registry.find("w-none").has_value());
        CHECK(!registry.register_well("   ", "x").has_value());
        CHECK(registry.snapshot().size() == 1);
        registry.clear_for_tests();
    }

    if (failures != 0) {
        std::fprintf(stderr, "ui_workers.well_xml：%d 处失败\n", failures);
        return 1;
    }
    std::printf("ui_workers.well_xml：全部通过\n");
    return 0;
}
