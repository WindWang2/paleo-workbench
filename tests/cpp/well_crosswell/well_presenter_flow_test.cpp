// 05 线 — 04 消费 presenter 的端到端测试：真实 app 安装器注册两类
// 外部 presenter，真实 VizEDataPage.preview_asset 对真资产出真页面。
//
//   * .las 资产 → "well_log" 页：真 WLE 文档曲线、真井名；
//   * .csv 时深资产 → "time_depth" 页：真校准对 + 标定核探针；
//   * 非井 .xml 资产 → 诚实诊断页（不伪造曲线，不假装失败缺失）；
//   * 注册表合同：first-wins，重复注册被响亮拒绝。

#include <QApplication>
#include <QEventLoop>
#include <QPixmap>
#include <QTimer>

#include <cstdio>
#include <string>
#include <vector>

#include "job_center.hpp"
#include "viz_e_install.hpp"
#include "well_presenter_install.hpp"

#include <pwb/ui_pages_preview/qt/time_depth_preview_presenter.hpp>
#include <pwb/ui_pages_preview/qt/well_log_preview_presenter.hpp>

#ifndef PWB_WELL_FIXTURE_DIR
#define PWB_WELL_FIXTURE_DIR "."
#endif

namespace {

int failures = 0;

#define CHECK(cond)                                                  \
    do {                                                             \
        if (!(cond)) {                                               \
            std::fprintf(stderr, "CHECK 失败 %s:%d: %s\n", __FILE__, \
                         __LINE__, #cond);                           \
            ++failures;                                              \
        }                                                            \
    } while (false)

using pwb::ui_pages_data::AssetRow;

AssetRow row_for(const QString& path, const char* name,
                 const char* format) {
    AssetRow row;
    row.view.id = name;
    row.view.name = name;
    row.view.format = format;
    row.view.path = path.toStdString();
    row.view.status = "indexed";
    return row;
}

struct Counter : public QObject {
    int count = 0;
    QString last;
    void track(pwb::viz_e::VizEDataPage* page) {
        connect(page, &pwb::viz_e::VizEDataPage::preview_rendered, this,
                [this](const QString& target) {
                    ++count;
                    last = target;
                });
    }
    bool wait_for(int wanted, int timeout_ms = 8000) {
        QEventLoop loop;
        QTimer deadline;
        deadline.setSingleShot(true);
        QObject::connect(&deadline, &QTimer::timeout, &loop,
                         &QEventLoop::quit);
        deadline.start(timeout_ms);
        while (count < wanted && deadline.isActive()) {
            QCoreApplication::processEvents(QEventLoop::AllEvents, 50);
        }
        return count >= wanted;
    }
};

// moc-free 页面（无 Q_OBJECT）不能进 findChild 的静态断言——dynamic_cast
// 遍历代替。
template <typename T>
std::vector<T*> find_pages(const QWidget* root) {
    std::vector<T*> out;
    for (const QObject* child : root->findChildren<QObject*>()) {
        if (auto* page = dynamic_cast<T*>(const_cast<QObject*>(child))) {
            out.push_back(page);
        }
    }
    return out;
}

}  // namespace

int main(int argc, char** argv) {
    // VizEDataPage 是 QWidget 家族：必须 QApplication（offscreen 由 CMake
    // 测试属性注入）。
    QApplication app(argc, argv);
    const std::string dir = PWB_WELL_FIXTURE_DIR;

    pwb::viz_e::reset_external_presenters_for_tests();

    // 注册合同：本线安装器一次性注册两类 presenter。
    CHECK(pwb::app::well_presenters::install());
    bool found_well_log = false;
    bool found_time_depth = false;
    for (const auto& status : pwb::viz_e::registered_presenters()) {
        found_well_log = found_well_log || status.kind == "well_log";
        found_time_depth =
            found_time_depth || status.kind == "time_depth";
    }
    CHECK(found_well_log);
    CHECK(found_time_depth);
    // first-wins：同 kind 再注册被响亮拒绝（装配 bug 不静默）。
    pwb::viz_e::ExternalPresenter duplicate;
    duplicate.kind = "well_log";
    duplicate.supports = [](const QString&) { return false; };
    duplicate.create = [](const QString&, QWidget* parent) {
        return new QWidget(parent);
    };
    CHECK(!pwb::viz_e::register_external_presenter(std::move(duplicate)));

    pwb::app::JobCenter jobs;
    pwb::viz_e::VizEDataPage page(nullptr, &jobs);
    Counter rendered;
    rendered.track(&page);

    // 04 消费：真 LAS 资产 → well_log 真页面。
    const QString las = QString::fromStdString(dir + "/las/well_a_metric.las");
    page.preview_asset(row_for(las, "W1", "las"));
    CHECK(rendered.wait_for(1));
    CHECK(page.active_target() == QStringLiteral("well_log"));
    const auto well_pages =
        find_pages<pwb::ui_pages_preview::qt::WellLogPreviewPage>(&page);
    CHECK(well_pages.size() == 1);
    if (!well_pages.empty()) {
        auto* well_page = well_pages.front();
        CHECK(well_page->data().diagnostic.empty());   // 不是诊断降级
        CHECK(well_page->data().well_name == "Well A");
        CHECK(well_page->data().curves.size() == 4);   // GR+DT+AC+DEN 真曲线
        // 渲染非空 smoke：grab 指定区域（页面可能已被父布局重新排布，
        // 以固定区域渲染保证可复现断言）。
        const QPixmap snapshot =
            well_page->grab(QRect(0, 0, 480, 320));
        CHECK(!snapshot.isNull());
        CHECK(snapshot.width() == 480);
    }

    // 04 消费：真时深 CSV → time_depth 真页面（校准对 + 探针）。
    const QString csv = QString::fromStdString(dir + "/tie/checkshot.csv");
    page.preview_asset(row_for(csv, "TD1", "csv"));
    CHECK(rendered.wait_for(2));
    CHECK(page.active_target() == QStringLiteral("time_depth"));
    const auto td_pages =
        find_pages<pwb::ui_pages_preview::qt::TimeDepthPreviewPage>(&page);
    CHECK(td_pages.size() == 1);
    if (!td_pages.empty()) {
        CHECK(td_pages.front()->data().diagnostic.empty());
        CHECK(td_pages.front()->data().pairs.size() == 4);  // 首井 4 对
    }

    // 非井 XML：诚实诊断页（解析拒绝可见，绝非假曲线）。
    const QString junk = QString::fromStdString(
        dir + "/xml/negative_generic_points.xml");
    page.preview_asset(row_for(junk, "X1", "xml"));
    CHECK(rendered.wait_for(3));
    bool saw_diagnostic = false;
    for (const auto* candidate :
         find_pages<pwb::ui_pages_preview::qt::WellLogPreviewPage>(&page)) {
        saw_diagnostic =
            saw_diagnostic || !candidate->data().diagnostic.empty();
    }
    CHECK(saw_diagnostic);

    pwb::viz_e::reset_external_presenters_for_tests();

    if (failures != 0) {
        std::fprintf(stderr, "well.presenter_flow：%d 处失败\n", failures);
        return 1;
    }
    std::printf("well.presenter_flow：全部通过\n");
    return 0;
}
