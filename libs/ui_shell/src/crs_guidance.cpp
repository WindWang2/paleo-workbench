#include "pwb/ui_shell/crs_guidance.hpp"

#include <QLabel>
#include <QListWidget>
#include <QPushButton>
#include <QVBoxLayout>

namespace pwb::ui_shell {

namespace {
QString qstr(const std::string& s) {
    return QString::fromUtf8(s.data(), static_cast<qsizetype>(s.size()));
}
}  // namespace

CrsGuidanceDialog::CrsGuidanceDialog(
    CrsGuidanceVerdict verdict,
    std::vector<std::pair<std::string, std::string>> affected_layers,
    QWidget* parent)
    : QDialog(parent) {
    setObjectName(QStringLiteral("CrsGuidanceDialog"));
    setWindowTitle(QStringLiteral("坐标系声明与数据不符"));

    auto* layout = new QVBoxLayout(this);
    auto* intro = new QLabel(
        QStringLiteral(
            "进入编辑前检查发现：工程/图层声明的坐标系与数据的实际坐标"
            "范围不符。继续编辑会把数据写进错误的坐标帧。"),
        this);
    intro->setWordWrap(true);
    layout->addWidget(intro);

    auto* reason = new QLabel(qstr(verdict.reason), this);
    reason->setWordWrap(true);
    layout->addWidget(reason);

    // Affected layers: caller supplies (layer_id, display) rows; default
    // lists the mismatch facts.
    auto* layers = new QListWidget(this);
    QStringList rows;
    for (const auto& [layer_id, display] : affected_layers) {
        rows << QStringLiteral("%1（%2）")
                    .arg(qstr(display), qstr(layer_id));
    }
    if (rows.isEmpty()) {
        for (const std::string& row : verdict.mismatch_rows) {
            rows << qstr(row);
        }
    }
    rows << QStringLiteral("当前声明 CRS：%1")
                .arg(verdict.declared_crs.empty()
                         ? QStringLiteral("（图层声明）")
                         : qstr(verdict.declared_crs));
    for (const QString& row : rows) {
        layers->addItem(row);
    }
    layout->addWidget(new QLabel(QStringLiteral("受影响图层："), this));
    layout->addWidget(layers, 1);

    auto* fix_button =
        new QPushButton(QStringLiteral("改为本地坐标（清除声明）并进入编辑"),
                        this);
    fix_button->setDefault(true);
    QObject::connect(fix_button, &QPushButton::clicked, this, [this] {
        cleared_ = true;
        accept();
    });
    auto* cancel_button = new QPushButton(QStringLiteral("取消"), this);
    QObject::connect(cancel_button, &QPushButton::clicked, this,
                     &QDialog::reject);
    layout->addWidget(fix_button);
    layout->addWidget(cancel_button);
}

}  // namespace pwb::ui_shell
