#include "viz_d_seismic_install.hpp"

#include <QAction>
#include <QFileDialog>
#include <QFileInfo>
#include <QMenu>
#include <QMessageBox>
#include <QString>

#include <pwb/seismic_viewer/seismic_slice_widget.hpp>

namespace pwb::viz_d {

void add_seismic_horizon_menu_actions(
    QMenu& menu, pwb::seismic_viewer::SeismicSliceWidget& widget) {
    auto* picking = menu.addAction(QObject::tr("地平线拾取"));
    picking->setCheckable(true);
    picking->setChecked(widget.picking_enabled());
    QObject::connect(picking, &QAction::toggled, &widget,
                     [&widget](bool on) { widget.enable_picking(on); });

    menu.addAction(QObject::tr("清空地平线拾取"), &widget,
                   [&widget] { widget.clear_picks(); });

    menu.addAction(QObject::tr("导出地平线拾取…"), &widget, [&widget] {
        const QString path = QFileDialog::getSaveFileName(
            &widget, QObject::tr("导出地平线拾取"),
            QStringLiteral("horizon_picks.json"),
            QObject::tr("Horizon picks (*.json)"));
        if (path.isEmpty()) {
            return;
        }
        std::string error;
        if (!widget.save_picks(path.toStdString(), error)) {
            QMessageBox::warning(&widget, QObject::tr("导出失败"),
                                 QString::fromStdString(error));
        }
    });

    menu.addAction(QObject::tr("导入地平线拾取…"), &widget, [&widget] {
        const QString path = QFileDialog::getOpenFileName(
            &widget, QObject::tr("导入地平线拾取"), QString(),
            QObject::tr("Horizon picks (*.json)"));
        if (path.isEmpty()) {
            return;
        }
        std::string error;
        const auto status = widget.load_picks(path.toStdString(), error);
        if (status == pwb::seismic_viewer::PicksLoadStatus::error) {
            QMessageBox::warning(&widget, QObject::tr("导入失败"),
                                 QString::fromStdString(error));
        } else if (status == pwb::seismic_viewer::PicksLoadStatus::mismatched_volume) {
            QMessageBox::information(
                &widget, QObject::tr("地平线拾取"),
                QObject::tr("拾取已载入，但其源体与当前体不一致（坐标仍按原体解释）。"));
        }
    });
}

void add_seismic_export_menu_actions(
    QMenu& menu, pwb::seismic_viewer::SeismicSliceWidget& widget) {
    menu.addAction(QObject::tr("导出切片…"), &widget, [&widget] {
        static const QString kFilter = QObject::tr(
            "NumPy 数组 (*.npy);;CSV (*.csv);;PNG 图像 (*.png)");
        const QString path = QFileDialog::getSaveFileName(
            &widget, QObject::tr("导出切片"), QStringLiteral("slice.npy"), kFilter);
        if (path.isEmpty()) {
            return; // user cancel — honest no-op
        }
        // The chosen filter decides the format (the frozen export dialog
        // behavior); a missing suffix falls back from the filter default.
        pwb::seismic_viewer::SeismicSliceWidget::SliceExportFormat format =
            pwb::seismic_viewer::SeismicSliceWidget::SliceExportFormat::npy;
        const QString suffix = QFileInfo(path).suffix().toLower();
        if (suffix == QLatin1String("csv")) {
            format = pwb::seismic_viewer::SeismicSliceWidget::SliceExportFormat::csv;
        } else if (suffix == QLatin1String("png")) {
            format = pwb::seismic_viewer::SeismicSliceWidget::SliceExportFormat::png;
        }
        std::string error;
        if (!widget.export_slice(path.toStdString(), format, error)) {
            QMessageBox::warning(&widget, QObject::tr("导出失败"),
                                 QString::fromStdString(error));
        }
    });
}

void add_seismic_view_state_menu_actions(
    QMenu& menu, pwb::seismic_viewer::SeismicSliceWidget& widget) {
    menu.addAction(QObject::tr("保存视图态…"), &widget, [&widget] {
        const QString path = QFileDialog::getSaveFileName(
            &widget, QObject::tr("保存视图态"), QStringLiteral("seismic_view.json"),
            QObject::tr("Seismic view state (*.json)"));
        if (path.isEmpty()) {
            return;
        }
        std::string error;
        if (!widget.save_view_state(path.toStdString(), error)) {
            QMessageBox::warning(&widget, QObject::tr("保存失败"),
                                 QString::fromStdString(error));
        }
    });
    menu.addAction(QObject::tr("加载视图态…"), &widget, [&widget] {
        const QString path = QFileDialog::getOpenFileName(
            &widget, QObject::tr("加载视图态"), QString(),
            QObject::tr("Seismic view state (*.json)"));
        if (path.isEmpty()) {
            return;
        }
        std::string error;
        const auto status = widget.load_view_state(path.toStdString(), error);
        if (status == pwb::seismic_viewer::SeismicSliceWidget::ViewStateLoadStatus::error) {
            QMessageBox::warning(&widget, QObject::tr("加载失败"),
                                 QString::fromStdString(error));
        } else if (status ==
                   pwb::seismic_viewer::SeismicSliceWidget::ViewStateLoadStatus::
                       mismatched_volume) {
            // Cross-volume restore is rejected wholesale — never a partial
            // application onto the wrong body.
            QMessageBox::warning(&widget, QObject::tr("视图态"),
                                 QObject::tr("视图态属于其他数据体，已拒绝应用。"));
        }
    });
}

} // namespace pwb::viz_d
