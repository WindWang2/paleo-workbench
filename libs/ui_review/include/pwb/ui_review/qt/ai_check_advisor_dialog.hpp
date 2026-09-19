#pragma once

// UI-11 — ai_check_advisor_dialog.py Qt shell: non-modal deterministic
// consistency report (rule checks, not an AI model — labels avoid the
// "AI expert" overclaim). The HTML body comes from the Qt-free
// build_advisor_html core.

#include "pwb/domain/json.hpp"
#include "pwb/ui_widgets/dialog.hpp"

class QTextBrowser;

namespace pwb::ui_review::qt {

class AICheckAdvisorDialog : public ui_widgets::PwbDialog {
    Q_OBJECT
public:
    AICheckAdvisorDialog(QWidget* parent, const domain::Json& bh_report,
                         const domain::Json& fault_report);

    QTextBrowser* browser() const { return browser_; }

private:
    QTextBrowser* browser_ = nullptr;
};

}  // namespace pwb::ui_review::qt
