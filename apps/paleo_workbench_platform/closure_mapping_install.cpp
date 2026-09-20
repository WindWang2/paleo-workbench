// 08-line closure — install implementation. See closure_mapping_install.hpp
// for the contract. Registry subset data is a faithful port of
// paleo_workbench/mapping/composer/registry.py (labels, defaults, property
// schemas, series-shape descriptions); the panel kernel deliberately does
// not ship registry data (CONV-02 D-10) — hosts do.

#include "closure_mapping_install.hpp"

#include <QMainWindow>

#include <QBuffer>
#include <QGuiApplication>
#include <QIODevice>
#include <QSize>

#include "app_shell.hpp"

#include <pwb/ui_map/mapping_page.hpp>

#include <QMetaObject>
#include <QObject>
#include <QPushButton>
#include <QVariant>
#include <QVBoxLayout>
#include <QWidget>

#include <algorithm>
#include <any>
#include <atomic>
#include <chrono>
#include <filesystem>
#include <map>
#include <memory>
#include <set>
#include <thread>
#include <utility>

#include "closure_mapping_document.hpp"

#include <pwb/application/adapters/data_store.hpp>
#include <pwb/cartography/color_ramps.hpp>
#include <pwb/domain/json.hpp>
#include <pwb/job_runtime/job_contract.hpp>
#include <pwb/layout_export/layout_export.hpp>
#include <pwb/mapping_document/composition.hpp>
#include <pwb/mapping_document/composition_session.hpp>
#include <pwb/mapping_document/composer_export.hpp>
#include <pwb/mapping_document/composer_renderer.hpp>
#include <pwb/mapping_document/composer_templates.hpp>
#include <pwb/mapping_document/document_io.hpp>
#include <pwb/project/manager.hpp>
#include <pwb/ui_map/display_map_canvas.hpp>
#include <pwb/ui_pages_data/qt/preparation_page.hpp>
#include <pwb/ui_pages_mapedit/boundary_panel.hpp>
#include <pwb/ui_pages_mapedit/factor_preview_grid.hpp>
#include <pwb/ui_pages_mapedit/map_edit_scene.hpp>
#include <pwb/ui_pages_mapedit/map_edit_view.hpp>
#include <pwb/ui_pages_mapedit/map_reference_panel.hpp>
#include <pwb/ui_pages_mapedit/map_workbench_bottom.hpp>
#include <pwb/ui_seqviz/factor_state.hpp>
#include <pwb/ui_seqviz/qt/composition_panel.hpp>
#include <pwb/ui_seqviz/qt/composition_replay.hpp>
#include <pwb/ui_seqviz/qt/factor_panels.hpp>
#include <pwb/ui_workers/contour_draft.hpp>
#include <pwb/ui_workers/factor_prepare.hpp>
#include <pwb/ui_wellseis/qt/well_table_panel.hpp>
#include <pwb/ui_wellseis/slices.hpp>
#include <pwb/viz_charts/marching_squares.hpp>

namespace pwb::app::closure_mapping {
namespace {

using pwb::domain::Json;

QString qstr(const std::string& s) {
    return QString::fromUtf8(s.data(), static_cast<qsizetype>(s.size()));
}

}  // namespace

// ---------------------------------------------------------------------------
// Off-thread worker host — runs the injected worker body on one joinable
// std::thread and marshals terminal callbacks back to the GUI thread. The
// page's guards prevent overlapping runs; the host joins before a
// replacement run and on destruction (worker lifecycle ownership).
// ---------------------------------------------------------------------------
class WorkerHost : public QObject {
    Q_OBJECT
public:
    using Body = std::function<void()>;

    explicit WorkerHost(QObject* parent) : QObject(parent) {}

    // target mirrors Python OwnedWorkerJob.target: the page's guards
    // compare it against the bound project so stale completions drop.
    void run(void* target, Body body) {
        join();
        target_ = target;
        busy_.store(true);
        cancelled_.store(false);
        thread_ = std::thread([body = std::move(body)]() { body(); });
    }

    void cancel() { cancelled_.store(true); }
    bool cancelled() const { return cancelled_.load(); }

    bool busy() const { return busy_.load(); }
    void* target() const { return target_; }

    // OwnedWorkerJob.shutdown parity: request cancellation, then join.
    // A cooperative worker observes the flag; the join is unbounded (the
    // terminal callbacks are marshalled, never joined from the GUI thread).
    bool shutdown(int /*wait_ms*/) {
        if (!thread_.joinable()) return true;
        cancelled_.store(true);
        join();
        return !thread_.joinable();
    }

    // Marshal a terminal callback onto the GUI thread. The callback owns
    // its captures (heap/shared payloads, never references into the thread
    // body's stack).
    void marshal(std::function<void()> fn) {
        QMetaObject::invokeMethod(
            this, [fn = std::move(fn)] { fn(); }, Qt::QueuedConnection);
    }

    void join() {
        if (thread_.joinable()) {
            cancelled_.store(true);  // cooperative stop request
            thread_.join();
            busy_.store(false);
            target_ = nullptr;
        }
    }

    ~WorkerHost() override { join(); }

private:
    std::thread thread_;
    std::atomic<bool> cancelled_{false};
    std::atomic<bool> busy_{false};
    void* target_ = nullptr;
};

namespace {

// ---------------------------------------------------------------------------
// Composer registry subset (registry.py verbatim data).
// ---------------------------------------------------------------------------

struct RegistrySpec {
    const char* type;
    const char* label;
    const char* category;
    std::array<double, 4> geometry;
    Json defaults;
    Json schema;
};

const std::vector<RegistrySpec>& registry_specs() {
    static const std::vector<RegistrySpec> specs = {
        {"main_map", "主图", "basic", {15.0, 30.0, 180.0, 140.0},
         Json::parse("{\"title\":\"主图\"}"),
         Json::parse("[{\"name\":\"title\",\"label\":\"标题\",\"type\":\"str\"}]")},
        {"legend", "图例", "basic", {205.0, 30.0, 80.0, 60.0},
         Json::parse("{}"),
         Json::parse("[{\"name\":\"title\",\"label\":\"标题\",\"type\":\"str\"},{\"name\":\"items\",\"label\":\"图例项 (JSON)\",\"type\":\"list\"}]")},
        {"north_arrow", "指北针", "basic", {250.0, 15.0, 14.0, 18.0},
         Json::parse("{\"label\":\"N\"}"),
         Json::parse("[{\"name\":\"label\",\"label\":\"方位标签\",\"type\":\"str\"}]")},
        {"scale_bar", "比例尺", "basic", {20.0, 180.0, 50.0, 8.0},
         Json::parse("{\"length_km\":10,\"units\":\"km\"}"),
         Json::parse("[{\"name\":\"length_km\",\"label\":\"长度 (km)\",\"type\":\"number\",\"min\":0.1},{\"name\":\"units\",\"label\":\"单位\",\"type\":\"str\"}]")},
        {"grid", "坐标网格", "basic", {15.0, 30.0, 180.0, 140.0},
         Json::parse("{\"spacing_mm\":20.0,\"color\":\"#9aa4b2\",\"line_width_mm\":0.2}"),
         Json::parse("[{\"name\":\"spacing_mm\",\"label\":\"间距 (mm)\",\"type\":\"number\",\"min\":2.0,\"max\":200.0},{\"name\":\"color\",\"label\":\"颜色\",\"type\":\"str\"},{\"name\":\"line_width_mm\",\"label\":\"线宽 (mm)\",\"type\":\"number\",\"min\":0.05,\"max\":5.0}]")},
        {"title", "图名", "basic", {15.0, 8.0, 180.0, 14.0},
         Json::parse("{\"text\":\"图件标题\",\"font_size\":8,\"align\":\"center\"}"),
         Json::parse("[{\"name\":\"text\",\"label\":\"文本\",\"type\":\"text\"},{\"name\":\"font_size\",\"label\":\"字号\",\"type\":\"number\",\"min\":2.0,\"max\":72.0},{\"name\":\"align\",\"label\":\"对齐\",\"type\":\"choices\",\"choices\":[\"left\",\"center\",\"right\"]}]")},
        {"annotation", "注释", "basic", {60.0, 90.0, 45.0, 8.0},
         Json::parse("{\"text\":\"注释\",\"leader\":true,\"font_size\":3.5}"),
         Json::parse("[{\"name\":\"text\",\"label\":\"文本\",\"type\":\"text\"},{\"name\":\"leader\",\"label\":\"引线\",\"type\":\"bool\"},{\"name\":\"font_size\",\"label\":\"字号\",\"type\":\"number\",\"min\":1.0,\"max\":36.0}]")},
        {"text", "文本", "basic", {30.0, 160.0, 80.0, 8.0},
         Json::parse("{\"text\":\"文本\",\"font_size\":4,\"align\":\"left\",\"color\":\"#000000\"}"),
         Json::parse("[{\"name\":\"text\",\"label\":\"文本\",\"type\":\"text\"},{\"name\":\"font_size\",\"label\":\"字号\",\"type\":\"number\",\"min\":1.0,\"max\":72.0},{\"name\":\"align\",\"label\":\"对齐\",\"type\":\"choices\",\"choices\":[\"left\",\"center\",\"right\"]},{\"name\":\"color\",\"label\":\"颜色\",\"type\":\"str\"}]")},
        {"image", "图像", "basic", {200.0, 110.0, 70.0, 50.0},
         Json::parse("{\"image_path\":null,\"image_data_png_b64\":null,\"fit\":\"contain\"}"),
         Json::parse("[{\"name\":\"image_path\",\"label\":\"图像路径\",\"type\":\"str\"},{\"name\":\"fit\",\"label\":\"适配\",\"type\":\"choices\",\"choices\":[\"contain\",\"cover\",\"stretch\"]}]")},
        {"inset_map", "附图", "basic", {210.0, 140.0, 60.0, 50.0},
         Json::parse("{\"locator_scale\":4.0}"),
         Json::parse("[{\"name\":\"locator_scale\",\"label\":\"定位缩放\",\"type\":\"number\",\"min\":0.1,\"max\":50.0},{\"name\":\"locator_rect\",\"label\":\"定位框 (JSON)\",\"type\":\"list\"}]")},
        {"metadata", "责任表", "basic", {15.0, 188.0, 150.0, 16.0},
         Json::parse("{\"fields\":[[\"编制\",\"\"],[\"日期\",\"\"],[\"比例尺\",\"\"]],\"font_size\":3.0}"),
         Json::parse("[{\"name\":\"fields\",\"label\":\"字段 (JSON)\",\"type\":\"list\"},{\"name\":\"font_size\",\"label\":\"字号\",\"type\":\"number\",\"min\":1.0,\"max\":12.0}]")},
        {"colorbar", "色标", "basic", {200.0, 90.0, 12.0, 80.0},
         Json::parse("{\"title\":\"数值\",\"min\":0.0,\"max\":1.0,\"stops\":[[0.0,\"#053061\"],[0.5,\"#f7f7f7\"],[1.0,\"#67001f\"]],\"discrete\":false,\"data_binding\":{\"key\":\"factor.colorbar\"}}"),
         Json::parse("[{\"name\":\"title\",\"label\":\"标题\",\"type\":\"str\"},{\"name\":\"min\",\"label\":\"最小值\",\"type\":\"number\"},{\"name\":\"max\",\"label\":\"最大值\",\"type\":\"number\"},{\"name\":\"discrete\",\"label\":\"离散\",\"type\":\"bool\"},{\"name\":\"stops\",\"label\":\"色带停靠点 (JSON)\",\"type\":\"list\"},{\"name\":\"color_ramp\",\"label\":\"色带名\",\"type\":\"str\"}]")},
        {"neatline", "图廓", "basic", {12.0, 12.0, 273.0, 186.0},
         Json::parse("{\"line_width_mm\":0.8,\"color\":\"#000000\",\"double_line\":false,\"inner_gap_mm\":1.5}"),
         Json::parse("[{\"name\":\"line_width_mm\",\"label\":\"线宽 (mm)\",\"type\":\"number\",\"min\":0.1,\"max\":5.0},{\"name\":\"color\",\"label\":\"颜色\",\"type\":\"str\"},{\"name\":\"double_line\",\"label\":\"双线图廓\",\"type\":\"bool\"},{\"name\":\"inner_gap_mm\",\"label\":\"内线间距 (mm)\",\"type\":\"number\",\"min\":0.5,\"max\":10.0}]")},
        {"datasource", "数据来源", "basic", {15.0, 170.0, 120.0, 18.0},
         Json::parse("{\"title\":\"数据来源\",\"text\":\"数据来源：\\n编制方法：\",\"font_size\":2.8}"),
         Json::parse("[{\"name\":\"title\",\"label\":\"标题\",\"type\":\"str\"},{\"name\":\"text\",\"label\":\"说明文本\",\"type\":\"text\"},{\"name\":\"font_size\",\"label\":\"字号\",\"type\":\"number\",\"min\":1.0,\"max\":12.0}]")},
        {"time_credits", "制图责任", "basic", {230.0, 182.0, 55.0, 16.0},
         Json::parse("{\"text\":\"制图时间：\\n编制：\\n审核：\",\"font_size\":2.6}"),
         Json::parse("[{\"name\":\"text\",\"label\":\"责任文本\",\"type\":\"text\"},{\"name\":\"font_size\",\"label\":\"字号\",\"type\":\"number\",\"min\":1.0,\"max\":12.0}]")},
        {"timescale", "年代地层", "geological", {15.0, 175.0, 180.0, 12.0},
         Json::parse("{\"stages\":[]}"),
         Json::parse("[{\"name\":\"stages\",\"label\":\"阶段子句 (JSON)\",\"type\":\"list\"}]")},
        {"fault_symbols", "断层符号", "geological", {210.0, 100.0, 75.0, 40.0},
         Json::parse("{\"title\":\"断层符号\",\"items\":[{\"label\":\"正断层\",\"pattern\":\"solid\"},{\"label\":\"逆断层\",\"pattern\":\"dash\"},{\"label\":\"走滑断层\",\"pattern\":\"dashdot\"}]}"),
         Json::parse("[{\"name\":\"title\",\"label\":\"标题\",\"type\":\"str\"},{\"name\":\"items\",\"label\":\"符号项 (JSON)\",\"type\":\"list\"}]")},
        {"facies_legend", "沉积相图例", "geological", {210.0, 30.0, 78.0, 66.0},
         Json::parse("{\"title\":\"沉积相图例\",\"items\":[]}"),
         Json::parse("[{\"name\":\"title\",\"label\":\"标题\",\"type\":\"str\"},{\"name\":\"items\",\"label\":\"相图例项 (JSON)\",\"type\":\"list\"}]")},
        {"lithology_legend", "岩性图例", "geological", {210.0, 30.0, 78.0, 66.0},
         Json::parse("{\"title\":\"岩性图例\",\"items\":[{\"label\":\"砂岩\",\"color\":\"#f2d38a\",\"pattern\":\"dots\"},{\"label\":\"泥岩\",\"color\":\"#9aa7b5\",\"pattern\":\"lines\"},{\"label\":\"灰岩\",\"color\":\"#d3dbe0\",\"pattern\":\"crosshatch\"}]}"),
         Json::parse("[{\"name\":\"title\",\"label\":\"标题\",\"type\":\"str\"},{\"name\":\"items\",\"label\":\"岩性项 (JSON)\",\"type\":\"list\"}]")},
        {"strat_labels", "地层标注", "geological", {60.0, 90.0, 50.0, 20.0},
         Json::parse("{\"text\":\"地层：\\n  组\\n  段\",\"font_size\":3.2}"),
         Json::parse("[{\"name\":\"text\",\"label\":\"标注文本\",\"type\":\"text\"},{\"name\":\"font_size\",\"label\":\"字号\",\"type\":\"number\",\"min\":1.0,\"max\":24.0}]")},
        {"subtitle", "副标题", "basic", {60.0, 8.0, 120.0, 6.0},
         Json::parse("{\"text\":\"T1 层沉积相图\",\"font_size\":4.0,\"align\":\"center\",\"color\":\"#333333\"}"),
         Json::parse("[{\"name\":\"text\",\"label\":\"副标题文本\",\"type\":\"text\"},{\"name\":\"font_size\",\"label\":\"字号\",\"type\":\"number\",\"min\":1.0,\"max\":24.0},{\"name\":\"align\",\"label\":\"对齐\",\"type\":\"choices\",\"choices\":[\"left\",\"center\",\"right\"]},{\"name\":\"color\",\"label\":\"颜色\",\"type\":\"str\"}]")},
        {"well_legend", "测井图例", "geological", {210.0, 100.0, 70.0, 50.0},
         Json::parse("{\"title\":\"测井图例\",\"items\":[]}"),
         Json::parse("[{\"name\":\"title\",\"label\":\"标题\",\"type\":\"str\"},{\"name\":\"items\",\"label\":\"图例项 (JSON)\",\"type\":\"list\"}]")},
        {"profile", "剖面占位", "geological", {30.0, 168.0, 90.0, 30.0},
         Json::parse("{\"section_ref\":\"\",\"title\":\"剖面\"}"),
         Json::parse("[{\"name\":\"section_ref\",\"label\":\"剖面引用\",\"type\":\"str\"},{\"name\":\"title\",\"label\":\"标题\",\"type\":\"str\"}]")},
        {"stat_chart", "统计图", "chart", {210.0, 30.0, 75.0, 55.0},
         Json::parse("{\"chart_type\":\"bar\",\"title\":\"统计\",\"series\":[],\"hole_ratio\":0.55}"),
         Json::parse("[{\"name\":\"chart_type\",\"label\":\"图表类型\",\"type\":\"choices\",\"choices\":[\"bar\",\"hbar\",\"line\",\"scatter\",\"pie\",\"donut\",\"histogram\",\"rose\"]},{\"name\":\"title\",\"label\":\"标题\",\"type\":\"str\"},{\"name\":\"series\",\"label\":\"数据系列\",\"type\":\"list\"},{\"name\":\"units\",\"label\":\"单位\",\"type\":\"str\"},{\"name\":\"hole_ratio\",\"label\":\"内孔半径比 (donut)\",\"type\":\"number\",\"min\":0.0,\"max\":0.9},{\"name\":\"colors\",\"label\":\"色序列 (JSON)\",\"type\":\"list\"}]")},
    };
    return specs;
}

const RegistrySpec* find_spec(const std::string& type) {
    for (const auto& spec : registry_specs()) {
        if (type == spec.type) return &spec;
    }
    return nullptr;
}

const char* category_label(const std::string& category) {
    if (category == "basic") return "基础组件";
    if (category == "geological") return "地质组件";
    if (category == "chart") return "统计图表";
    return category.c_str();
}

std::map<std::string, std::string> chart_series_schemas_map() {
    // registry.py CHART_SERIES_SCHEMAS verbatim (shape descriptions the
    // series editor shows as tooltips).
    return {
        {"bar", "分类序列 [{\"label\": \"类目\", \"value\": 数值}, ...]"},
        {"hbar", "分类序列 [{\"label\": \"类目\", \"value\": 数值}, ...]（横向条）"},
        {"line",
         "数值序列 {\"x\": [数值...], \"y\": [数值...]} 或 "
         "[{\"x\": 数值, \"y\": 数值}, ...]（x 轴按值缩放）；"
         "也兼容分类式 [{\"label\": \"类目\", \"value\": 数值}, ...]（x 等距）"},
        {"scatter",
         "数值点对 {\"x\": [数值...], \"y\": [数值...]} 或 "
         "[{\"x\": 数值, \"y\": 数值}, ...]（x 轴按值缩放）；"
         "也兼容分类式 [{\"label\": \"类目\", \"value\": 数值}, ...]（x 等距）"},
        {"pie",
         "占比序列 [{\"label\": \"扇区\", \"value\": 正数}, ...]（按 value 占比分扇区，非正值跳过）"},
        {"donut",
         "占比序列 [{\"label\": \"扇区\", \"value\": 正数}, ...]（环形图，"
         "properties.hole_ratio 控制内孔半径比 0~0.9，缺省 0.55）"},
        {"histogram",
         "原始值直方 {\"values\": [数值...], \"bins\": 箱数}（values/bins 也可直挂 properties）"},
        {"rose",
         "方位序列 [{\"label\": \"方位\", \"angle_deg\": 罗盘方位角(0=北/顺时针), "
         "\"value\": 数值, \"angle_span\": 扇区角(可选)}, ...]（缺省等分 360°）"},
    };
}

// ---------------------------------------------------------------------------
// factor_map_tasks Json ↔ FactorTaskRecord (ui_seqviz shelf payload).
// ---------------------------------------------------------------------------

pwb::ui_seqviz::FactorTaskRecord record_from_json(const Json& entry) {
    pwb::ui_seqviz::FactorTaskRecord record;
    auto get = [&entry](const char* key) -> std::string {
        const auto it = entry.find(key);
        return it != entry.end() && it->is_string() ? it->get<std::string>()
                                                    : std::string{};
    };
    record.id = get("id");
    record.name = get("name");
    record.status = get("status");
    record.target_horizon = get("target_horizon");
    record.factor_type = get("factor_type");
    record.method = get("method");
    if (const auto it = entry.find("parameters");
        it != entry.end() && it->is_object()) {
        record.parameters = *it;
    }
    if (const auto it = entry.find("quality_metrics");
        it != entry.end() && it->is_object()) {
        record.quality_metrics = *it;
    }
    return record;
}

// ---------------------------------------------------------------------------
// Contour draft Json conversion (project.contour_drafts entries). Python
// shape: ContourDraft model — id / name / target_horizon / factor_type /
// linked_factor_task_id / levels / segments[{id, level, coordinates,
// closed, properties}] / source_grid_n / source_backend /
// source_value_range / status / generator_version / updated_at /
// linked_map_document_id.
// ---------------------------------------------------------------------------

Json draft_to_json(const pwb::ui_workers::ContourDraftSlice& draft) {
    Json out = Json::object();
    out["id"] = draft.id;
    out["name"] = draft.name;
    out["target_horizon"] = draft.target_horizon;
    out["factor_type"] = draft.factor_type;
    out["linked_factor_task_id"] = draft.linked_factor_task_id;
    out["levels"] = draft.levels;
    Json segments = Json::array();
    for (const auto& segment : draft.segments) {
        Json seg = Json::object();
        seg["id"] = segment.id;
        seg["level"] = segment.level;
        Json coords = Json::array();
        for (const auto& [x, y] : segment.coordinates) {
            coords.push_back(Json::array({x, y}));
        }
        seg["coordinates"] = coords;
        seg["closed"] = segment.closed;
        Json props = Json::object();
        for (const auto& [key, value] : segment.properties) {
            if (auto const* s = std::any_cast<std::string>(&value)) {
                props[key] = *s;
            } else if (auto const* d = std::any_cast<double>(&value)) {
                props[key] = *d;
            } else if (auto const* b = std::any_cast<bool>(&value)) {
                props[key] = *b;
            } else if (auto const* i = std::any_cast<int>(&value)) {
                props[key] = *i;
            }
            // Unrepresentable payload types are skipped (honest subset;
            // the compile path only stores string/double/bool/int).
        }
        seg["properties"] = props;
        segments.push_back(std::move(seg));
    }
    out["segments"] = segments;
    out["source_grid_n"] = draft.source_grid_n;
    out["source_backend"] = draft.source_backend;
    out["source_value_range"] = Json::array(
        {draft.source_value_range.first, draft.source_value_range.second});
    out["status"] = draft.status;
    out["generator_version"] = draft.generator_version;
    out["updated_at"] = draft.updated_at;
    out["linked_map_document_id"] = draft.linked_map_document_id;
    return out;
}

// ---------------------------------------------------------------------------
// PreparationPage panel shims — adapt the real panels to the page's seam
// interfaces (the page stays dependency-light; the real panels live in
// ui_seqviz / ui_wellseis / ui_pages_mapedit).
// ---------------------------------------------------------------------------

class TaskPanelShim final : public pwb::ui_pages_data::qt::FactorTaskPanelApi {
public:
    explicit TaskPanelShim(QWidget* parent = nullptr)
        : FactorTaskPanelApi(parent) {
        auto* layout = new QVBoxLayout(this);
        layout->setContentsMargins(0, 0, 0, 0);
        panel_ = new pwb::ui_seqviz::qt::FactorTaskPanel(this);
        layout->addWidget(panel_, 1);
        connect(panel_, &pwb::ui_seqviz::qt::FactorTaskPanel::generate_requested,
                this, &FactorTaskPanelApi::generate_requested);
        connect(panel_,
                &pwb::ui_seqviz::qt::FactorTaskPanel::contour_draft_requested,
                this, &FactorTaskPanelApi::contour_draft_requested);
    }

    QString selected_method() const override {
        return panel_->selected_method();
    }
    void update_state(const Json& tasks) override {
        std::vector<pwb::ui_seqviz::FactorTaskRecord> records;
        if (tasks.is_array()) {
            for (const auto& entry : tasks) {
                records.push_back(record_from_json(entry));
            }
        }
        panel_->update_state(records);
    }
    QPushButton* generate_btn() override { return panel_->generate_btn(); }
    QPushButton* contour_draft_btn() override {
        return panel_->contour_draft_btn();
    }
    QLabel* summary_label() override { return panel_->summary_label(); }

private:
    pwb::ui_seqviz::qt::FactorTaskPanel* panel_ = nullptr;
};

// The C++ WellTablePanel (UI-09) has no QC button; the shim carries the
// page's QC row so the Python toolbar contract survives without touching
// ui_wellseis.
class WellTableShim final : public pwb::ui_pages_data::qt::WellTablePanelApi {
public:
    explicit WellTableShim(QWidget* parent = nullptr)
        : WellTablePanelApi(parent) {
        auto* layout = new QVBoxLayout(this);
        layout->setContentsMargins(0, 0, 0, 0);
        qc_btn_ = new QPushButton(QStringLiteral("运行井点 QC"), this);
        qc_btn_->setObjectName(QStringLiteral("run_qc_btn"));
        layout->addWidget(qc_btn_, 0);
        panel_ = new pwb::ui_wellseis::qt::WellTablePanel(this);
        layout->addWidget(panel_, 1);
    }

    QPushButton* run_qc_btn() override { return qc_btn_; }
    void update_from_well_table(void* table) override {
        const auto* slice =
            static_cast<const pwb::ui_wellseis::WellTableSlice*>(table);
        if (slice != nullptr) {
            panel_->update_from_well_table(*slice);
        } else {
            panel_->clear();
        }
    }

private:
    QPushButton* qc_btn_ = nullptr;
    pwb::ui_wellseis::qt::WellTablePanel* panel_ = nullptr;
};

class PreviewGridShim final
    : public pwb::ui_pages_data::qt::FactorPreviewGridApi {
public:
    explicit PreviewGridShim(QWidget* parent = nullptr)
        : FactorPreviewGridApi(parent) {
        auto* layout = new QVBoxLayout(this);
        layout->setContentsMargins(0, 0, 0, 0);
        panel_ = new pwb::ui_pages_mapedit::FactorPreviewGrid(this);
        layout->addWidget(panel_, 1);
    }

    void update_state(const Json& tasks) override {
        std::vector<Json> entries;
        if (tasks.is_array()) {
            for (const auto& entry : tasks) entries.push_back(entry);
        }
        panel_->update_state(entries);
    }

private:
    pwb::ui_pages_mapedit::FactorPreviewGrid* panel_ = nullptr;
};

// Factor task grid from the legacy `parameters` lists (grid_x/grid_y/
// grid_z) — the _grid_from_task legacy branch parity.
bool grid_from_task_parameters(const Json& task, std::vector<double>& grid_x,
                               std::vector<double>& grid_y,
                               pwb::ui_workers::Grid2D& grid_z) {
    const auto params = task.find("parameters");
    if (params == task.end() || !params->is_object()) return false;
    auto read = [params](const char* key,
                         std::vector<double>& out) {
        const auto it = params->find(key);
        if (it == params->end() || !it->is_array()) return false;
        out.clear();
        for (const auto& v : *it) {
            if (!v.is_number()) return false;
            out.push_back(v.get<double>());
        }
        return true;
    };
    if (!read("grid_x", grid_x) || !read("grid_y", grid_y)) return false;
    const auto z = params->find("grid_z");
    if (z == params->end() || !z->is_array() || grid_y.empty()) return false;
    grid_z.rows = z->size();
    grid_z.cols = grid_x.size();
    grid_z.data.clear();
    for (const auto& row : *z) {
        if (!row.is_array()) return false;
        for (const auto& v : row) {
            if (!v.is_number()) return false;
            grid_z.data.push_back(v.get<double>());
        }
    }
    if (grid_z.data.size() != grid_z.rows * grid_z.cols) return false;
    return true;
}

}  // namespace

// Per-window install state — lives as a QObject child of the window so
// notify_project_changed / save_documents can recover it by property.
class ClosureContext : public QObject {
    Q_OBJECT
public:
    explicit ClosureContext(QObject* parent) : QObject(parent) {}
    Install install;
    MapDocumentBank* bank = nullptr;
    pwb::ui_pages_data::qt::PreparationPage* preparation = nullptr;

    // BEGIN V14-COMPILATION-PUBLISH
    // Element ids the user explicitly bound to the live map document
    // (set_main_map); the preview seam honours them.
    std::set<std::string> bound_map_elements;
    // END V14-COMPILATION-PUBLISH
};

// BEGIN V14-COMPILATION-PUBLISH
namespace {

// ---------------------------------------------------------------------------
// Live-content seams for the native composer renderer (D-V14-01).
//
// The composition document is JSON; the live map document of the mapping
// page is not. These bridges let the renderer show the REAL map content
// (the canvas frame + its layer snapshot) inside MAIN_MAP / INSET_MAP
// frames and build the legend from the live layer order. When the canvas
// has no content the seam reports "not bound" and the renderer falls back
// to the dict-layer vector path or an honest placeholder — never a
// fabricated map.
// ---------------------------------------------------------------------------

// A short-lived frame cache: composition interactions (element drags,
// property edits) refresh the preview far more often than the canvas
// content changes, so the grabbed frame is reused for 300ms. The cache is
// keyed by the canvas widget and invalidated on size change; a canvas
// repaint (pan/zoom) picks up within the TTL.
constexpr auto kFrameCacheTtl = std::chrono::milliseconds(300);

struct FrameCacheEntry {
    std::chrono::steady_clock::time_point at{};
    QSize size;
    std::string png_b64;
};

std::string grab_canvas_frame_b64(const QWidget* canvas) {
    if (canvas == nullptr) return "";
    auto* mutable_canvas = const_cast<QWidget*>(canvas);
    static std::map<const QWidget*, FrameCacheEntry> cache;
    const QSize current = mutable_canvas->size();
    FrameCacheEntry& entry = cache[mutable_canvas];
    const auto now = std::chrono::steady_clock::now();
    if (!entry.png_b64.empty() && entry.size == current &&
        now - entry.at < kFrameCacheTtl) {
        return entry.png_b64;
    }
    const QPixmap pixmap = mutable_canvas->grab();
    if (pixmap.isNull()) return "";
    QBuffer buffer;
    buffer.open(QIODevice::WriteOnly);
    if (!pixmap.toImage().save(&buffer, "PNG")) return "";
    entry.at = now;
    entry.size = current;
    entry.png_b64 = buffer.data().toBase64().toStdString();
    return entry.png_b64;
}

// Canvas layer snapshot → legend entries (the snapshot order IS the canvas
// draw order — the host's canonical layer order, Prompt3's authority).
std::vector<pwb::mapping_document::ComposerLegendEntry> canvas_legend_entries(
    const QWidget* canvas) {
    std::vector<pwb::mapping_document::ComposerLegendEntry> entries;
    auto* display = canvas == nullptr
                        ? nullptr
                        : canvas->findChild<pwb::ui_map::DisplayMapCanvas*>();
    if (display == nullptr) return entries;
    const Json& snapshot = display->snapshot();
    if (!snapshot.is_object() || !snapshot.contains("layers") ||
        !snapshot["layers"].is_array()) {
        return entries;
    }
    for (const Json& layer : snapshot["layers"]) {
        if (!layer.is_object()) continue;
        if (layer.contains("visible") && !layer["visible"].is_boolean()) continue;
        if (layer.contains("visible") && !layer["visible"].get<bool>()) continue;
        pwb::mapping_document::ComposerLegendEntry entry;
        entry.label = layer.value("name", std::string());
        const Json style = layer.value("style", Json::object());
        const std::string fill = style.is_object() ? style.value("fill", std::string())
                                                   : std::string();
        const std::string stroke =
            style.is_object() ? style.value("stroke", std::string()) : std::string();
        entry.color = !fill.empty() ? fill : (!stroke.empty() ? stroke : "#6c8ebf");
        const std::string layer_type = layer.value("layer_type", std::string());
        entry.symbol_type = layer_type == "well" || layer_type == "well_point" ? "point"
                            : layer_type == "contour"                  ? "line"
                                                                        : "polygon";
        entry.stroke_color = !stroke.empty() ? stroke : "#333333";
        entries.push_back(std::move(entry));
    }
    return entries;
}

bool canvas_has_content(const QWidget* canvas) {
    if (canvas == nullptr) return false;
    auto* display = canvas->findChild<pwb::ui_map::DisplayMapCanvas*>();
    if (display == nullptr) return false;
    const Json& snapshot = display->snapshot();
    return snapshot.is_object() && snapshot.contains("layers") &&
           snapshot["layers"].is_array() && !snapshot["layers"].empty();
}

pwb::mapping_document::ComposerRenderSeams make_render_seams(const QWidget* canvas) {
    pwb::mapping_document::ComposerRenderSeams seams;
    if (canvas != nullptr) {
        seams.frame_content =
            [canvas](const pwb::mapping_document::ComposerElement& frame)
            -> pwb::mapping_document::ComposerRenderSeams::FrameContent {
            pwb::mapping_document::ComposerRenderSeams::FrameContent content;
            // Only map frames take live content; every other element type
            // renders from its own JSON properties.
            const std::string& type = frame.element_type;
            const bool is_map_frame =
                type == "main_map" || type == "inset_map" || type == "profile";
            if (!is_map_frame || !canvas_has_content(canvas)) return content;
            content.bound = true;
            content.png_b64 = grab_canvas_frame_b64(canvas);
            return content;
        };
        seams.legend_entries =
            [canvas](const pwb::mapping_document::ComposerElement&)
            -> std::vector<pwb::mapping_document::ComposerLegendEntry> {
            return canvas_legend_entries(canvas);
        };
    }
    // Colour-ramp resolution through the cartography authority (Python
    // composer registry PALETTE_ALIASES → get_color_ramp).
    seams.palette_stops =
        [](const std::string& name,
           pwb::mapping_document::ComposerRenderSeams::ColorStops& stops) {
            std::string key = name;
            if (key == "lithofacies-v1") key = "jet";
            else if (key == "paleogeographic-v1") key = "water_depth";
            const pwb::cartography::ColorRamp ramp =
                pwb::cartography::get_color_ramp(key);
            for (const auto& stop : ramp.stops) {
                stops.emplace_back(stop.position, stop.color);
            }
            return !stops.empty();
        };
    return seams;
}

// The panel's export seam: pixel budget → native QGIS layout executor
// (when the platform bound one) → native composer engine (SVG + Qt
// PNG/PDF replay). The engine label in the report says which path
// produced the file (D-V14-03: the layout_export D-03 "no composer
// fallback" decision is superseded by the native engine).
std::function<pwb::ui_seqviz::qt::CompositionExportResult(
    const pwb::mapping_document::Composition&, const std::string&,
    const std::string&, double)>
make_export_fn(const Install& platform_install, const QWidget* canvas) {
    return [platform_install, canvas](
               const pwb::mapping_document::Composition& document,
               const std::string& path, const std::string& fmt,
               double dpi) -> pwb::ui_seqviz::qt::CompositionExportResult {
        pwb::ui_seqviz::qt::CompositionExportResult result;
        result.path = path;
        std::string format = fmt;
        if (format.empty()) {
            const std::filesystem::path target(path);
            format = target.has_extension() ? target.extension().string() : "";
            if (!format.empty() && format.front() == '.') format.erase(0, 1);
        }
        if (format.empty()) format = "png";
        std::transform(format.begin(), format.end(), format.begin(),
                       [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
        if (format != "svg" && format != "png" && format != "pdf") {
            result.message = "unsupported composition export format '" + format + "'";
            return result;
        }
        // 1. Export pixel budget (layout_export.py MAX_EXPORT_PIXELS) — a
        //    budget breach is a caller error, never an engine fallback.
        try {
            pwb::layout_export::check_pixel_budget(document, dpi);
        } catch (const std::invalid_argument& ex) {
            result.message = ex.what();
            return result;
        }
        const pwb::mapping_document::ComposerRenderSeams render_seams =
            make_render_seams(canvas);
        // 2. Native QGIS layout executor (vector map output).
        if (platform_install.layout_export) {
            const Json report = platform_install.layout_export(
                pwb::mapping_document::dump_composition(document), path, format, dpi);
            const bool ok = report.is_object() && report.value("ok", false);
            if (ok) {
                result.ok = true;
                result.engine = report.value("engine", std::string("qgis_layout"));
                const Json warnings = report.value("warnings", Json::array());
                if (warnings.is_array()) {
                    for (const Json& warning : warnings) {
                        if (warning.is_string()) result.warnings.push_back(warning.get<std::string>());
                    }
                }
                return result;
            }
            // The QGIS path refused (hybrid elements, no session, …):
            // remember why, then try the composer engine — the same
            // document, a different writer.
            const std::string failure =
                report.is_object() ? report.value("failure", std::string()) : std::string();
            result.message = failure;
        }
        // 3. Composer engine (native SVG; PNG/PDF replayed on Qt).
        const pwb::mapping_document::ComposerReplaySeams replay =
            pwb::ui_seqviz::qt::make_composition_replay_seams();
        const pwb::mapping_document::CompositionExportReport report =
            pwb::mapping_document::export_composition_page(document, path, format, dpi,
                                                           render_seams, replay);
        result.ok = report.ok;
        result.engine = report.engine;
        result.message = report.message;
        if (!report.ok && result.message.empty()) {
            result.message = "composition export failed";
        }
        return result;
    };
}

}  // namespace
// END V14-COMPILATION-PUBLISH

// ---------------------------------------------------------------------------
// install
// ---------------------------------------------------------------------------

bool install(const Install& install) {
    if (install.window == nullptr || install.shell == nullptr) {
        return false;
    }
    auto* mapping_page = install.shell->mapping_page();
    if (mapping_page == nullptr) return false;

    // Capture the getter BY VALUE — the Install struct lives on the
    // caller's frame only.
    auto store_getter = install.store_getter;
    const auto store =
        store_getter ? store_getter()
                       : std::shared_ptr<pwb::application::PwbDataStore>{};

    // ---- 1. mapping-page adopt set ---------------------------------------
    auto* view = new pwb::ui_pages_mapedit::MapEditView(mapping_page);
    auto* scene = view->edit_scene();
    mapping_page->adopt_edit_view(view);
    mapping_page->adopt_reference_panel(
        new pwb::ui_pages_mapedit::MapReferencePanel(mapping_page));
    mapping_page->adopt_bottom_workbench(
        new pwb::ui_pages_mapedit::MapWorkbenchBottom(mapping_page));

    auto* composition_panel =
        new pwb::ui_seqviz::qt::CompositionPanel(mapping_page);
    mapping_page->adopt_composition_panel(composition_panel);

    // BEGIN V14-COMPILATION-PUBLISH
    // The per-window context is created before the composition seams so
    // the main-map binding seam can record its element ids on it.
    auto* context = new ClosureContext(install.window);
    context->install = Install{install.window, install.shell, store_getter};
    install.window->setProperty(
        "closure_mapping_context",
        QVariant::fromValue(static_cast<QObject*>(context)));
    // END V14-COMPILATION-PUBLISH

    pwb::ui_seqviz::qt::CompositionRegistrySeams seams;
    seams.element_menu = [] {
        std::vector<pwb::ui_seqviz::qt::CompositionMenuGroup> groups;
        const char* order[] = {"basic", "geological", "chart"};
        for (const char* category : order) {
            pwb::ui_seqviz::qt::CompositionMenuGroup group;
            group.category_label = category_label(category);
            for (const auto& spec : registry_specs()) {
                if (spec.category == category) {
                    group.specs.emplace_back(spec.type, spec.label);
                }
            }
            if (!group.specs.empty()) groups.push_back(std::move(group));
        }
        return groups;
    };
    seams.property_schema = [](const std::string& type) -> Json {
        const auto* spec = find_spec(type);
        return spec != nullptr ? spec->schema : Json::array();
    };
    seams.element_label_fn = [](const std::string& type) -> std::string {
        const auto* spec = find_spec(type);
        return spec != nullptr ? spec->label : type;
    };
    seams.chart_series_schemas = chart_series_schemas_map();
    // No native SVG string renderer / export executor is wired into this
    // install yet — the panel keeps its honest 预览渲染失败 / 导出失败
    // surfaces (registered limitation; engine wiring lands with the
    // layout-service host slice).
    pwb::mapping_document::CompositionFactory factory;
    factory.set_spec_provider(
        [](const std::string& type)
            -> const pwb::mapping_document::ElementSpec* {
        // The provider must return a stable pointer per type — a
        // process-wide table (registry.py parity: module registry).
        static const std::map<std::string, pwb::mapping_document::ElementSpec>
            table = [] {
                std::map<std::string, pwb::mapping_document::ElementSpec> out;
                for (const auto& spec : registry_specs()) {
                    pwb::mapping_document::ElementSpec entry;
                    entry.default_geometry = spec.geometry;
                    entry.default_properties = spec.defaults;
                    out.emplace(spec.type, std::move(entry));
                }
                return out;
            }();
        auto it = table.find(type);
        if (it == table.end()) {
            // Python get_spec degrades unknown types to the TEXT spec.
            it = table.find("text");
        }
        return it != table.end() ? &it->second : nullptr;
    });
    composition_panel->set_factory(factory);
    // BEGIN V14-COMPILATION-PUBLISH
    // Composer template library + preview renderer + export executor —
    // the native ports of composer/{templates,renderer,export}.py close
    // the three gaps #1433 registered (blank A4 start / 预览渲染失败 /
    // 导出引擎不可用). Live map content reaches the renderer through host
    // seams (D-V14-01); nothing here fabricates map content.
    seams.template_library = [] {
        std::vector<pwb::ui_seqviz::qt::CompositionTemplateEntry> entries;
        for (const auto& tpl : pwb::mapping_document::composer_template_library()) {
            entries.push_back({tpl.template_id, tpl.label, tpl.description});
        }
        return entries;
    };
    seams.instantiate_template =
        [factory](const std::string& template_id) -> pwb::mapping_document::Composition {
        return pwb::mapping_document::instantiate_composer_template(factory, template_id);
    };
    // Preview: the native renderer with the live-canvas seams.
    seams.render_svg =
        [render_seams = make_render_seams(mapping_page)](
            const pwb::mapping_document::Composition& document) -> std::string {
        return pwb::mapping_document::render_composition_to_svg(document, render_seams);
    };
    // Export: budget → QGIS layout executor → composer engine.
    seams.export_fn = make_export_fn(install, mapping_page);
    // Provenance: best-effort export-ledger write into the live project.
    seams.project_provider = [store_getter]() -> std::any {
        const auto store = store_getter ? store_getter() : nullptr;
        if (store == nullptr) return {};
        return std::make_any<std::shared_ptr<pwb::application::PwbDataStore>>(store);
    };
    seams.record_export = [](const std::any& project_any,
                             const std::string& path) {
        auto store = std::any_cast<std::shared_ptr<pwb::application::PwbDataStore>>(
            project_any);
        if (store == nullptr) return;
        Json& root = store->document().root();
        if (!root.is_object()) return;
        if (!root.contains("export_artifacts") || !root["export_artifacts"].is_array()) {
            root["export_artifacts"] = Json::array();
        }
        Json artifact = Json::object();
        artifact["id"] = "artifact_" + std::to_string(
            std::chrono::duration_cast<std::chrono::milliseconds>(
                std::chrono::system_clock::now().time_since_epoch()).count());
        artifact["linked_id"] = "composition";
        artifact["format"] = "svg";
        artifact["output_path"] = path;
        artifact["options"] = Json::object();
        artifact["included_map_elements"] = Json::array();
        artifact["generated_at"] = "";
        artifact["source_task_ids"] = Json::array();
        // Honest degradation: no catalog OUTPUT registration from this
        // seam (registered=false), never a fabricated version id.
        artifact["catalog_version_id"] = Json(nullptr);
        root["export_artifacts"].push_back(std::move(artifact));
    };
    // set_main_map: bind the live map document to this composition's main
    // map frame (host-side; a live document cannot ride inside JSON
    // properties). The panel hands over the session + document, so the
    // host resolves the frame: the first visible MAIN_MAP, else the first
    // visible INSET_MAP. An empty any unbinds.
    seams.main_map_bind_fn =
        [context](pwb::mapping_document::CompositionEditSession& session,
                  pwb::mapping_document::Composition& document,
                  const std::any& map_doc) -> bool {
        (void)session;
        const pwb::mapping_document::ComposerElement* target = nullptr;
        for (const auto& element : document.elements) {
            if (element.element_type == "main_map" && element.visible) {
                target = &element;
                break;
            }
        }
        if (target == nullptr) {
            for (const auto& element : document.elements) {
                if (element.element_type == "inset_map" && element.visible) {
                    target = &element;
                    break;
                }
            }
        }
        if (target == nullptr) return false;
        auto* element = pwb::mapping_document::find_element(document, target->id);
        if (element == nullptr) return false;
        const bool bind = map_doc.has_value();
        if (!element->properties.is_object()) element->properties = Json::object();
        element->properties["map_bound"] = bind;
        if (bind) {
            context->bound_map_elements.insert(element->id);
        } else {
            context->bound_map_elements.erase(element->id);
        }
        return true;
    };
    composition_panel->set_registry(std::move(seams));
    // The panel opens on the first template document (Python
    // composition_panel __init__ materialises the default template) — the
    // blank A4 start is gone.
    const std::string default_template_id =
        pwb::mapping_document::composer_template_library().empty()
            ? std::string()
            : pwb::mapping_document::composer_template_library().front().template_id;
    if (!default_template_id.empty()) {
        composition_panel->set_document(
            pwb::mapping_document::instantiate_composer_template(factory,
                                                                 default_template_id));
    } else {
        composition_panel->set_document(factory.create_document("未命名组图"));
    }
    // END V14-COMPILATION-PUBLISH

    // ---- 2. document bank -------------------------------------------------
    auto* bank = new MapDocumentBank(scene, view, install.window);
    // BEGIN V14-COMPILATION-PUBLISH — the context was created before the
    // composition seams (the main-map binding seam records on it); only
    // the bank back-pointer is set here now.
    context->bank = bank;
    // END V14-COMPILATION-PUBLISH
    bank->set_persist_fn([store_getter, store](std::string*) -> bool {
        const auto persisted =
            store != nullptr ? store
                             : (store_getter ? store_getter() : nullptr);
        if (persisted == nullptr) return false;
        // ProjectManager::save is the atomic project write kernel (crash-
        // safe replace + .bak + stale-write guard). The store does not
        // expose save yet (01-line surface), so the same kernel runs
        // against the store's live document.
        pwb::project::ProjectManager manager(persisted->project_file());
        auto result = manager.save(persisted->document());
        return result.is_ok();
    });
    if (store != nullptr) {
        std::vector<Json> documents;
        const auto& root = store->document().root();
        const auto section = root.find("paleomap_documents");
        if (section != root.end() && section->is_array()) {
            for (const auto& entry : *section) documents.push_back(entry);
        }
        bank->set_documents(std::move(documents), {}, install.window);
    }

    // ---- 3. preparation page ---------------------------------------------
    auto* preparation =
        new pwb::ui_pages_data::qt::PreparationPage(install.window);
    preparation->setObjectName(QStringLiteral("PreparationPage"));
    preparation->set_task_panel(new TaskPanelShim(preparation));
    preparation->set_well_table_panel(new WellTableShim(preparation));
    preparation->set_preview_grid(new PreviewGridShim(preparation));
    preparation->set_boundary_panel(
        new pwb::ui_pages_mapedit::BoundaryPanel(preparation));

    auto* host = new WorkerHost(install.window);

    // Project store seam — returns the STORE (shared_ptr), never a raw
    // pointer into its document: every caller holds the store alive for
    // its own use (review finding: a bare Json* outlived the local
    // shared_ptr).
    auto project_store_fn = [store_getter]()
        -> std::shared_ptr<pwb::application::PwbDataStore> {
        return store_getter ? store_getter() : nullptr;
    };
    preparation->set_factor_map_tasks_fn(
        [project_store_fn](void*) -> Json {
        const auto store = project_store_fn();
        if (store == nullptr) return Json::array();
        const auto& root = store->document().root();
        const auto it = root.find("factor_map_tasks");
        return it != root.end() ? *it : Json::array();
    });

    auto generation = std::make_shared<int>(0);
    preparation->set_generation_fns(
        [generation] { return ++*generation; },
        [generation] { return *generation; });

    // OwnedWorkerJob seams — the page's running/target/cancel guards need
    // a live job binding (review P1-7); WorkerHost owns the thread.
    preparation->set_prepare_job(
        pwb::ui_pages_data::qt::WorkerJobApi{
            [host] { return host->busy(); },
            [host](int wait_ms) { return host->shutdown(wait_ms); },
            [host] { host->cancel(); },
            [host]() -> void* { return host->target(); }});
    preparation->set_contour_job(
        pwb::ui_pages_data::qt::WorkerJobApi{
            [host] { return host->busy(); },
            [host](int wait_ms) { return host->shutdown(wait_ms); },
            [host] { host->cancel(); },
            [host]() -> void* { return host->target(); }});
    preparation->set_snapshot_task_count_fn(
        [project_store_fn](void*, const std::string&, int) {
            const auto store = project_store_fn();
            if (store == nullptr) return 0;
            const auto& root = store->document().root();
            const auto it = root.find("factor_map_tasks");
            return it != root.end() && it->is_array()
                       ? static_cast<int>(it->size())
                       : 0;
        });

    // Prepare worker: the real batch grid kernel is not ported natively
    // yet (cross-line dependency — registered in the PR). The run stages a
    // real batch result whose tasks carry the explicit kernel-missing
    // error; the page shows the honest failure instead of a fabricated
    // product.
    preparation->set_prepare_worker_fn(
        [host](void* project, const std::string& method, int gen,
               std::function<void(const pwb::ui_pages_data::qt::PrepareProgressView&)>
                   progress,
               std::function<void(const pwb::ui_pages_data::qt::PrepareResultView&)>
                   completed,
               std::function<void(const QString&)>,
               std::function<void()> cancelled) {
        (void)project;
        host->run(project, [host, method, gen, progress, completed,
                            cancelled]() {
            pwb::ui_pages_data::qt::PrepareProgressView start;
            start.generation = gen;
            start.phase = "classify";
            start.message = "网格计算内核未接入";
            host->marshal([progress, start] { progress(start); });

            pwb::ui_workers::FactorPrepareBatchResult result;
            result.generation = gen;
            result.method = method;
            for (int i = 0; i < 1; ++i) {
                if (host->cancelled()) {
                    host->marshal([cancelled] { cancelled(); });
                    return;
                }
                pwb::ui_workers::FactorPrepareTaskResult item;
                item.task_id = "kernel_binding";
                item.dirty_state = "missing_output";
                item.error = "网格计算内核未接入（等待科学计算内核绑定）";
                result.task_results.push_back(std::move(item));
            }
            pwb::ui_pages_data::qt::PrepareResultView done;
            done.generation = gen;
            done.clean_count = result.clean_count;
            done.executed_count = result.executed_count;
            host->marshal([completed, done] { completed(done); });
        });
        });

    // Commit: the Python host-side guard semantics (stale generation
    // mutates nothing). Task-patch application lands with the science
    // kernel binding (the conversion seam needs produced task payloads).
    preparation->set_commit_prepare_fn(
        [](void*, const pwb::ui_pages_data::qt::PrepareResultView&,
           int) { return 0; });

    // Contour worker: the REAL ui_workers compile pipeline with the REAL
    // viz_charts marching-squares extraction kernel over legacy parameter
    // grids. Without completed grids it honestly yields zero drafts.
    preparation->set_contour_worker_fn(
        [host, project_store_fn](
            void* project, std::function<void(void*)> completed,
            std::function<void(const QString&)> failed) {
        // Keep the store alive for the whole worker run (captured on the
        // GUI thread): the Json root pointer stays valid even if the user
        // opens another project mid-run — the stale commit then writes to
        // the captured (superseded) store and is dropped by the page
        // guards on the GUI thread.
        auto store = project_store_fn();
        host->run(project, [host, completed = std::move(completed),
                            failed = std::move(failed), store]() {
            try {
                Json* root = store != nullptr ? &store->document().root()
                                              : nullptr;
                // Shared result payload: the ledger JSON the GUI-thread
                // commit writes back, plus the created-draft count.
                auto payload = std::make_shared<Json>(Json::array());
                int count = 0;
                if (root != nullptr) {
                    std::vector<pwb::ui_workers::FactorTaskSlice> tasks;
                    Json tasks_json = Json::array();
                    if (const auto it = root->find("factor_map_tasks");
                        it != root->end() && it->is_array()) {
                        tasks_json = *it;
                    }
                    for (const auto& entry : tasks_json) {
                        pwb::ui_workers::FactorTaskSlice task;
                        auto field = [&entry](const char* key) {
                            const auto f = entry.find(key);
                            return f != entry.end() && f->is_string()
                                       ? f->get<std::string>()
                                       : std::string{};
                        };
                        task.id = field("id");
                        task.name = field("name");
                        task.status = field("status");
                        task.target_horizon = field("target_horizon");
                        task.factor_type = field("factor_type");
                        task.method = field("method");
                        if (task.status == "complete") {
                            std::vector<double> x, y;
                            pwb::ui_workers::Grid2D z;
                            if (grid_from_task_parameters(entry, x, y, z)) {
                                task.grid_x = std::move(x);
                                task.grid_y = std::move(y);
                                task.grid_z = std::move(z);
                            }
                        }
                        tasks.push_back(std::move(task));
                    }

                    std::vector<pwb::ui_workers::ContourDraftSlice> ledger;
                    // Existing ledger rides in the project (upsert parity).
                    // (Parsing existing entries back is not needed for the
                    // created-count contract; compile upserts into a fresh
                    // snapshot ledger and the commit replaces the section.)
                    job::CancellationToken token;
                    // The real extraction kernel: viz_charts marching
                    // squares (contourpy serial port) behind the
                    // ui_workers ExtractLinesFn seam.
                    pwb::ui_workers::ExtractLinesFn extract =
                        [](const std::vector<double>& grid_x,
                           const std::vector<double>& grid_y,
                           const pwb::ui_workers::Grid2D& grid_z,
                           const std::vector<double>& levels,
                           const job::CancellationToken& token) {
                            std::map<double, std::vector<
                                                 std::vector<std::pair<double, double>>>>
                                out;
                            if (levels.empty()) return out;
                            auto cancelled = [&token]() {
                                return token.is_cancelled();
                            };
                            const auto lines =
                                pwb::viz_charts::extract_contour_lines(
                                    grid_x, grid_y, grid_z.data, levels,
                                    cancelled);
                            if (!lines.has_value()) return out;
                            for (const auto& [level, polylines] : *lines) {
                                auto& points = out[level];
                                for (const auto& line : polylines) {
                                    std::vector<std::pair<double, double>> pts;
                                    pts.reserve(line.xs.size());
                                    for (std::size_t i = 0;
                                         i < line.xs.size() &&
                                         i < line.ys.size();
                                         ++i) {
                                        pts.emplace_back(line.xs[i],
                                                         line.ys[i]);
                                    }
                                    points.push_back(std::move(pts));
                                }
                            }
                            return out;
                        };
                    const auto drafts =
                        pwb::ui_workers::compile_contour_drafts_for_project(
                            tasks, ledger, std::nullopt, /*only_complete=*/true,
                            pwb::ui_workers::kContourDefaultNLevels, token,
                            extract, /*id_fn=*/{},
                            /*updated_at=*/{});
                    count = static_cast<int>(drafts.size());
                    for (const auto& draft : drafts) {
                        payload->push_back(draft_to_json(draft));
                    }
                }
                host->marshal([completed, payload] {
                    completed(payload.get());
                });
            } catch (const std::exception& exc) {
                const QString message = QString::fromUtf8(exc.what());
                host->marshal([failed, message] { failed(message); });
            }
        });
        });
    // The commit receives the shared Json payload pointer and writes the
    // compiled ledger into project.contour_drafts.
    preparation->set_commit_contour_fn(
        [project_store_fn](void*, void* result) -> int {
            auto* payload = static_cast<Json*>(result);
            if (payload == nullptr) return 0;
            const auto store = project_store_fn();
            if (store != nullptr) {
                store->document().root()["contour_drafts"] = *payload;
            }
            return payload->is_array() ? static_cast<int>(payload->size()) : 0;
        });

    context->preparation = preparation;

    install.shell->adopt_preparation_page(preparation);

    // Bind whatever project is already open (review P0-1: the page's
    // project guard stayed null forever, making the real contour kernel
    // unreachable and QC lie about "工程未绑定").
    notify_project_changed(install.window);
    return true;
}

void notify_project_changed(QMainWindow* window) {
    if (window == nullptr) return;
    const QVariant stored = window->property("closure_mapping_context");
    auto* context = stored.value<QObject*>();
    if (context == nullptr) return;
    auto* self = dynamic_cast<ClosureContext*>(context);
    if (self == nullptr) return;
    const auto store =
        self->install.store_getter ? self->install.store_getter() : nullptr;
    void* project_root =
        store != nullptr ? &store->document().root() : nullptr;
    if (self->preparation != nullptr) {
        self->preparation->set_project(project_root);
    }
    if (self->bank != nullptr) {
        std::vector<Json> documents;
        if (store != nullptr) {
            const auto& root = store->document().root();
            const auto section = root.find("paleomap_documents");
            if (section != root.end() && section->is_array()) {
                for (const auto& entry : *section) documents.push_back(entry);
            }
        }
        self->bank->set_documents(std::move(documents), {}, window);
    }
}

bool save_documents(QMainWindow* window, std::string* error) {
    if (window == nullptr) {
        if (error != nullptr) *error = "无宿主窗口";
        return false;
    }
    const QVariant stored = window->property("closure_mapping_context");
    auto* context = stored.value<QObject*>();
    auto* self = dynamic_cast<ClosureContext*>(context);
    if (self == nullptr || self->bank == nullptr) {
        if (error != nullptr) *error = "编图文档库未安装";
        return false;
    }
    // Route through the bank's public save (persist seam included).
    if (!self->bank->save_active(window)) {
        if (error != nullptr) *error = "编图文档保存失败（见页面诊断）";
        return false;
    }
    return true;
}

}  // namespace pwb::app::closure_mapping

#include "closure_mapping_install.moc"
