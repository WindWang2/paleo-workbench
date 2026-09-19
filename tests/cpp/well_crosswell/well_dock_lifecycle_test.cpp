// 05 线 — 真实 viz_b dock + 真实 JobCenter 的生命周期测试。
//
// 验收口径（任务书）："真实 dock 测试覆盖对象销毁而非仅编译"、"编辑重开
// 与标定数值可复现"、"跨工程切换"。
//
//   1. 真 LAS 经生产 seam 加载进真 dock（井数/身份注册可见）；
//   2. 在飞 DTW 下销毁 dock：排队 GUI 投递被 released 守卫丢弃——
//      不崩溃、不迟到落账（销毁语义的真证据，非编译覆盖）；
//   3. 编辑（DTW 拾取）→ 保存 sidecar → 重开恢复：拾取逐值复现；
//   4. 跨工程切换：切到无 sidecar 的新工程 → 工作区清空（不串扰），
//      切回 → 原状态逐值恢复；
//   5. 标定数值可复现：同一井两次标定读数逐字符一致。

#include <QApplication>
#include <QDir>
#include <QEventLoop>
#include <QFile>
#include <QLabel>
#include <QProgressDialog>
#include <QTemporaryDir>
#include <QTimer>

#include <chrono>
#include <cstdio>
#include <memory>
#include <string>

#include "job_center.hpp"
#include "viz_b_cross_well_dock.hpp"

#include <pwb/domain/json.hpp>
#include <pwb/ui_workers/well_identity.hpp>

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

void spin(int milliseconds) {
    QEventLoop loop;
    QTimer::singleShot(milliseconds, &loop, &QEventLoop::quit);
    loop.exec();
}

// tie_readout_ 是 dock 私有成员；经文本特征找到"R = "读数标签。
QString tie_readout_text(QWidget* root) {
    for (QLabel* label : root->findChildren<QLabel*>()) {
        if (label->text().contains(QStringLiteral("R = ")) ||
            label->text().contains(QStringLiteral("标定不可用")) ||
            label->text().contains(QStringLiteral("时深"))) {
            return label->text();
        }
    }
    return QString();
}

}  // namespace

int main(int argc, char** argv) {
    // QWidget 家族（dock/进度对话框）要求 QApplication；offscreen 平台由
    // CMake 测试属性注入。
    QApplication app(argc, argv);
    using pwb::domain::Json;
    const std::string dir = PWB_WELL_FIXTURE_DIR;
    const QString las_a = QString::fromStdString(dir + "/las/well_a_metric.las");
    const QString las_b =
        QString::fromStdString(dir + "/las/well_b_ft_reverse.las");
    const QString csv_tie = QString::fromStdString(dir + "/tie/checkshot.csv");

    // 共享井身份注册表从干净状态开始（first-register-wins 语义）。
    pwb::ui_workers::WellIdentityRegistry::instance().clear_for_tests();

    // ---------------------------------------------------------------
    // 1)+5) 真加载 + 校准表通道 + 标定读数可复现。
    // ---------------------------------------------------------------
    QString error;
    {
        pwb::app::JobCenter jobs;
        pwb::app::VizBCrossWellDock dock(&jobs);
        CHECK(dock.load_wells_from_las({las_a, las_b}, &error));
        CHECK(dock.well_count() == 2);
        // 共享井身份：两井按名注册（同键幂等，A 页此前注册的复用）。
        CHECK(pwb::ui_workers::WellIdentityRegistry::instance()
                  .find_by_name("Well A")
                  .has_value());
        CHECK(pwb::ui_workers::WellIdentityRegistry::instance()
                  .find_by_name("Well B")
                  .has_value());

        // 校准表进 dock（checkshot CSV），井震标定页有真数据。
        CHECK(dock.load_checkshot_csv(csv_tie, &error));
        QMetaObject::invokeMethod(&dock, "on_well_tie_well_changed");
        spin(50);
        const QString first_reading = tie_readout_text(&dock);
        CHECK(!first_reading.isEmpty());
        // 同一井重算两次 → 读数逐字符一致（标定数值可复现）。
        QMetaObject::invokeMethod(&dock, "on_well_tie_well_changed");
        spin(50);
        CHECK(tie_readout_text(&dock) == first_reading);
    }

    // ---------------------------------------------------------------
    // 2) 在飞 DTW 下销毁 dock。
    // JobOwner 双重所有权（JobCenter unique_ptr + QObject 父=dock）要求
    // JobCenter 先于 dock 析构——生产中由「JobCenter 是 MainWindow 成员、
    // dock 是 QObject 子」的析构序保证；测试用 unique_ptr 复刻同一序。
    // ---------------------------------------------------------------
    {
        auto jobs = std::make_unique<pwb::app::JobCenter>();
        auto* dock = new pwb::app::VizBCrossWellDock(jobs.get());
        CHECK(dock->load_wells_from_las({las_a, las_b}, &error));
        // 播种拾取（restore_state 公共 API；state["picks"] 的形状 =
        // HorizonPicksModel::to_json() 的 {"picks": [...]} 包装）。
        Json pick = Json::object(
            {{"pick_id", "p-seed"},
             {"formation_name", "T-SEED"},
             {"well_depths", Json::array({Json::array({"Well A", 97.0})})},
             {"source", "manual"}});
        Json seed = Json::object();
        seed["picks"] = Json::object({{"picks", Json::array({pick})}});
        dock->restore_state(seed);
        CHECK(dock->pick_count() == 1);
        // 私有槽经 moc 名字调用（与真实按钮同一路径）。
        QMetaObject::invokeMethod(dock, "on_propagate_dtw");
        // 产品关闭协议：先 bounded 关停（取消+汇合），再按生产析构序
        //（JobCenter 先亡，dock 后亡）。
        jobs->shutdown_workers(400);
        spin(200);
        jobs.reset();  // JobCenter 析构：owners_ 在 dock 存活时回收
        delete dock;   // 其后销毁 dock（迟到投递若未被代际丢弃即 UAF 现场）
        spin(200);
    }

    // ---------------------------------------------------------------
    // 3)+4) 编辑 → 保存 → 重开复现；跨工程切换不串扰。
    // ---------------------------------------------------------------
    {
        QTemporaryDir project_a;
        QTemporaryDir project_b;
        CHECK(project_a.isValid() && project_b.isValid());
        Json saved_state;

        // 工程 A：打开工程（设目录）→ 加载 → DTW（真实作业）→ 落盘 sidecar。
        // （析构序同上：JobCenter 先亡。）
        {
            auto jobs = std::make_unique<pwb::app::JobCenter>();
            pwb::app::VizBCrossWellDock dock(jobs.get());
            dock.set_project_directory(project_a.path());
            CHECK(dock.load_wells_from_las({las_a, las_b}, &error));
            QMetaObject::invokeMethod(&dock, "on_propagate_dtw");
            // 等真实 DTW 作业完成（拾取落地）。
            const auto deadline = std::chrono::steady_clock::now() +
                                  std::chrono::seconds(8);
            while (dock.pick_count() == 0 &&
                   std::chrono::steady_clock::now() < deadline) {
                spin(50);
            }
            CHECK(dock.pick_count() > 0);
            // 落盘：拾取变更已 schedule_persistence（300ms 合并，目录已设）。
            spin(600);
            CHECK(QFile::exists(project_a.path() +
                                QStringLiteral("/cross_well_workspace.json")));
            QFile sidecar(project_a.path() +
                          QStringLiteral("/cross_well_workspace.json"));
            CHECK(sidecar.open(QIODevice::ReadOnly));
            saved_state = pwb::domain::Json::parse(
                sidecar.readAll().toStdString());
            CHECK(saved_state.contains("well_source_las"));  // 05：LAS 来源
            // handle_project_closed：flush + generation bump。
            dock.handle_project_closed();
            jobs.reset();
        }

        // 切到工程 B（无 sidecar）：工作区必须清空，绝不串扰。
        {
            auto jobs = std::make_unique<pwb::app::JobCenter>();
            pwb::app::VizBCrossWellDock dock(jobs.get());
            CHECK(dock.load_wells_from_las({las_a}, &error));
            dock.restore_state(saved_state);
            CHECK(dock.well_count() == 2);
            CHECK(dock.pick_count() > 0);

            dock.set_project_directory(project_b.path());
            dock.restore_from_project();
            CHECK(dock.well_count() == 0);  // 05：新工程重置
            CHECK(dock.pick_count() == 0);

            // 切回工程 A：井 + 拾取逐值恢复。
            dock.set_project_directory(project_a.path());
            dock.restore_from_project();
            spin(400);  // LAS 来源重载走真解析
            CHECK(dock.well_count() == 2);
            CHECK(dock.pick_count() > 0);
            // 复现：恢复后的 picks JSON 与保存时逐值一致。
            const Json restored_picks = dock.save_state().at("picks");
            CHECK(restored_picks == saved_state.at("picks"));

            // 迟到投递丢弃：再起一个 DTW，随即 restore_state（代际
            // bump）——迟到的完成不得改动已恢复的拾取集。
            QMetaObject::invokeMethod(&dock, "on_propagate_dtw");
            dock.restore_state(saved_state);
            jobs->shutdown_workers(400);
            spin(200);
            const Json after_late = dock.save_state().at("picks");
            CHECK(after_late == saved_state.at("picks"));
            jobs.reset();
        }
    }

    if (failures != 0) {
        std::fprintf(stderr, "well.dock_lifecycle：%d 处失败\n", failures);
        return 1;
    }
    std::printf("well.dock_lifecycle：全部通过\n");
    return 0;
}
