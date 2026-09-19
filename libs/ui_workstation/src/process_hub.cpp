#include "pwb/ui_workstation/process_hub.hpp"

#include <QDateTime>
#include <QVBoxLayout>

namespace pwb::ui_workstation {

namespace {

std::string now_hh_mm_ss() {
    return QDateTime::currentDateTime().toString("HH:mm:ss")
        .toStdString();
}

}  // namespace

void LogBridge::post(const std::string& level,
                     const std::string& logger_name,
                     const std::string& message) {
    post_line(format_log_line(now_hh_mm_ss(), level, logger_name,
                              message));
}

void LogBridge::post_line(const std::string& line) {
    buffer_.push(line);
    // emit 碰上 DeferredDelete 竞态被销毁：行已在缓冲里，不能向上抛。
    try {
        emit message_ready(QString::fromStdString(line));
    } catch (...) {
    }
}

// ----------------------------------------------------------- LogViewer

WorkstationLogViewer::WorkstationLogViewer(QWidget* parent)
    : QFrame(parent) {
    setObjectName("WorkstationLogPanel");
    auto* outer = new QVBoxLayout(this);
    outer->setContentsMargins(0, 0, 0, 0);
    outer->setSpacing(0);

    logs_ = new QPlainTextEdit(this);
    logs_->setObjectName("WorkstationLogView");
    logs_->setReadOnly(true);
    logs_->setMaximumBlockCount(kLogLineCap);
    outer->addWidget(logs_);

    poll_timer_ = new QTimer(this);
    poll_timer_->setInterval(1000);
    connect(poll_timer_, &QTimer::timeout, this,
            &WorkstationLogViewer::drain_lines);
    poll_timer_->start();
}

void WorkstationLogViewer::attach_bridge(LogBridge* bridge) {
    if (bridge_ == bridge) return;
    if (conn_) disconnect(conn_);
    bridge_ = bridge;
    if (bridge_ != nullptr) {
        conn_ = connect(bridge_, &LogBridge::message_ready, this,
                        &WorkstationLogViewer::drain_lines);
        drain_lines();
    }
}

void WorkstationLogViewer::log(const std::string& level,
                               const std::string& logger_name,
                               const std::string& message) {
    if (bridge_ != nullptr) bridge_->post(level, logger_name, message);
}

void WorkstationLogViewer::drain_lines() {
    if (bridge_ == nullptr) return;
    for (const auto& line : bridge_->take_pending()) {
        logs_->appendPlainText(QString::fromStdString(line));
    }
}

void WorkstationLogViewer::shutdown() {
    poll_timer_->stop();
    if (conn_) {
        disconnect(conn_);
        conn_ = {};
    }
}

// --------------------------------------------------------- ConsolePane

WorkstationConsolePane::WorkstationConsolePane(QWidget* parent)
    : QFrame(parent) {
    setObjectName("WorkstationConsolePane");
    auto* outer = new QVBoxLayout(this);
    outer->setContentsMargins(0, 0, 0, 0);
    outer->setSpacing(0);

    auto* console = new QPlainTextEdit(this);
    console->setObjectName("WorkstationConsoleView");
    console->setReadOnly(true);
    console->setPlainText("预留：嵌入式控制台");
    outer->addWidget(console);
}

}  // namespace pwb::ui_workstation
