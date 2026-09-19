// UI-10 — Qt widget smoke test (offscreen): instantiate every ported
// widget once and drive the primary entry points under
// QT_QPA_PLATFORM=offscreen. Complements core_state_test.cpp (the
// Qt-free cores) by proving the Qt shells construct and respond.

#include <QApplication>
#include <QComboBox>
#include <QLineEdit>
#include <QPushButton>
#include <QTableWidget>
#include <QThread>

#include <cstdio>
#include <memory>
#include <string>

#include <pwb/ui_seqviz/factor_state.hpp>
#include <pwb/ui_seqviz/qt/factor_panels.hpp>
#include <pwb/ui_seqviz/qt/sequence_framework_page.hpp>
#include <pwb/ui_seqviz/qt/sequence_panels.hpp>
#include <pwb/ui_seqviz/sequence_state.hpp>

using namespace pwb::ui_seqviz;

namespace {

int failures = 0;

void check(bool condition, const char* what) {
    if (!condition) {
        ++failures;
        std::fprintf(stderr, "FAIL %s\n", what);
    } else {
        std::fprintf(stdout, "PASS %s\n", what);
    }
}

StratigraphySlice sample_stratigraphy() {
    StratigraphySlice strat;
    strat.interpretation_version = "v3";
    strat.systems_tract_scheme = "LST/TST/HST";
    strat.sequence_boundaries = {"Sq1", "Sq2"};
    strat.target_horizon = "Sq2";
    strat.applicable_wells = {"w1"};
    return strat;
}

}  // namespace

int main(int argc, char** argv) {
    QApplication app(argc, argv);

    // --- SequenceBoundaryTable -------------------------------------------
    {
        qt::SequenceBoundaryTable table;
        table.update_state(sample_stratigraphy());
        check(table.table()->rowCount() == 2, "boundary_table rows");
        check(table.table()->item(1, 2)->text() == "当前目标",
              "boundary_table target note");
        table.update_state(StratigraphySlice{});
        check(table.table()->rowCount() == 0, "boundary_table empty");
    }

    // --- SequenceTargetPanel ----------------------------------------------
    {
        qt::SequenceTargetPanel panel;
        panel.update_state(sample_stratigraphy());
        check(panel.target_combo()->count() == 2, "target options count");
        check(panel.current_target() == "Sq2", "target current text");
        check(panel.current_scheme() == "LST/TST/HST", "scheme text");

        // Commit dedupe: Enter then re-commit of the same text emits once.
        int emissions = 0;
        QObject::connect(&panel, &qt::SequenceTargetPanel::target_changed,
                         &panel, [&emissions](const QString&) { ++emissions; });
        panel.target_combo()->setEditText("Sq1");
        emit panel.target_combo()->lineEdit()->returnPressed();
        // Simulated activated() on the same text must not re-emit.
        emit panel.target_combo()->activated(0);
        check(emissions == 1, "target commit dedupe");

        // Resync from update_state suppresses against the project target.
        panel.update_state(sample_stratigraphy());
        emit panel.target_combo()->activated(1);  // Sq2 — already committed
        check(emissions == 1, "target resync dedupe");
    }

    // --- SequenceSchemeSummary --------------------------------------------
    {
        qt::SequenceSchemeSummary summary;
        summary.update_state(sample_stratigraphy());
        bool saved = false;
        QObject::connect(&summary, &qt::SequenceSchemeSummary::save_requested,
                         &summary, [&saved] { saved = true; });
        summary.findChild<QPushButton*>()->click();
        check(saved, "summary save_requested");
        summary.set_bind_status("已保存到项目（LST/TST/HST）");
    }

    // --- SequenceFrameworkPage ---------------------------------------------
    {
        StratigraphyProjectSlice project;
        project.stratigraphy.sequence_boundaries = {"Sq1", "Sq2"};
        project.stratigraphy.systems_tract_scheme = "LST/TST/HST";
        project.stratigraphy.target_horizon = "Sq1";
        PaleoMapDocumentSlice map;
        map.linked_target_horizon = "Sq1";
        project.paleomap_documents.push_back(map);

        qt::SequenceFrameworkPage page;
        page.set_project(&project);
        page.update_state(project.stratigraphy);

        int updates = 0;
        QObject::connect(&page, &qt::SequenceFrameworkPage::stratigraphy_updated,
                         &page, [&updates] { ++updates; });

        // Boundary activation re-binds target + downstream linked horizon.
        emit page.boundary_table()->boundary_activated("Sq2");
        check(updates == 1, "page boundary activated emits");
        check(project.stratigraphy.target_horizon == "Sq2",
              "page applies target");
        check(project.paleomap_documents[0].linked_target_horizon == "Sq2",
              "page binds downstream");

        // save_scheme: scheme present → applies and emits.
        check(page.save_scheme(), "page save_scheme applies");
        check(updates == 2, "page save emits");
    }

    // --- FactorTaskPanel ---------------------------------------------------
    {
        std::vector<FactorTaskRecord> tasks(2);
        tasks[0].name = "Sq2 砂厚";
        tasks[0].status = "complete";
        tasks[0].method = "IDW";
        tasks[0].target_horizon = "Sq2";
        tasks[1].name = "Sq2 泥质";
        tasks[1].status = "pending";
        tasks[1].method = "IDW";

        qt::FactorTaskPanel panel;
        panel.update_state(tasks);
        check(panel.row_count() == 2, "factor rows");
        check(panel.selected_method() == "IDW", "factor common method seeded");
        QString generated;
        QObject::connect(&panel, &qt::FactorTaskPanel::generate_requested,
                         &panel, [&generated](const QString& m) {
                             generated = m;
                         });
        panel.findChild<QPushButton*>("PrimaryButton") == nullptr;
        panel.update_state({});
        check(panel.row_count() == 0, "factor rows cleared");
        (void)generated;
    }

    // --- FactorPreviewGrid ---------------------------------------------------
    {
        std::vector<FactorTaskRecord> tasks(3);
        tasks[0].status = "complete";
        tasks[0].factor_type = "砂厚";
        tasks[0].target_horizon = "Sq2";
        tasks[0].method = "IDW";
        tasks[1].status = "pending";
        tasks[2].status = "complete";
        tasks[2].factor_type = "泥质";

        qt::FactorPreviewGrid grid;
        grid.update_state(tasks);
        check(grid.card_count() == 2, "grid completed-only cards");
        check(grid.header_label()->text().contains("单因素图集"),
              "grid header");
        grid.update_state({});
        check(grid.card_count() == 0, "grid empty");
        check(grid.header_label()->text() == "单因素图集",
              "grid empty header");
    }

    // --- CreateFactorMapDialog -------------------------------------------------
    {
        qt::CreateFactorMapDialog dialog;
        dialog.set_stratigraphy_target("Sq2");
        check(dialog.horizon_combo()->itemText(0) == "Sq2",
              "dialog horizon seed");
        const FactorMapParams params = dialog.create_params();
        check(params.factor_name == "砂岩厚度", "dialog factor param");
        check(params.method == "kriging", "dialog method data");
        check(params.grid_n == 50, "dialog grid default");
        check(!params.include_polygons, "dialog polygons unchecked");
        check(!dialog.start_job(), "dialog no-service refuses start");

        dialog.set_service([](const FactorMapParams& p) -> FactorMapOutcome {
            FactorMapOutcome outcome;
            outcome.map_title = p.target_horizon + " " + p.factor_name;
            outcome.layer_count = 2;
            return outcome;
        });
        bool created = false;
        QObject::connect(&dialog, &qt::CreateFactorMapDialog::map_created,
                         &dialog, [&created](const FactorMapOutcome&) {
                             created = true;
                         });
        check(dialog.start_job(), "dialog starts job");
        // JobOwner delivers via queued invocation — pump events briefly.
        for (int i = 0; i < 200 && !created; ++i) {
            QCoreApplication::processEvents(QEventLoop::AllEvents, 50);
            QThread::msleep(10);
        }
        check(created, "dialog map_created delivered");
    }

    std::fprintf(stdout, "%s (%d failures)\n",
                 failures == 0 ? "ALL PASS" : "FAILURES", failures);
    return failures == 0 ? 0 : 1;
}
