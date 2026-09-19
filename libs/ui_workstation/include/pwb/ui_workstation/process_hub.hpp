#pragma once

// Qt shells over log_buffer (UI-12) — port of
// paleo_workbench/ui/workstation/process_hub.py:
//
//  * LogBridge: the QtLogHandler equivalent — any thread may post a
//    formatted log line; it lands in a bounded LogBuffer AND is
//    re-emitted as message_ready (queued to the GUI thread). A
//    destroyed receiver never faults the caller: the emit is wrapped.
//  * LogViewer: the「日志」dock content — read-only QPlainTextEdit at
//    LOG_LINE_CAP blocks, signal + 1 s poll share take_pending().
//  * ConsolePane:「控制台」honest placeholder — 预留：嵌入式控制台.

#include <QFrame>
#include <QObject>
#include <QPlainTextEdit>
#include <QTimer>

#include <pwb/ui_workstation/log_buffer.hpp>

namespace pwb::ui_workstation {

class LogBridge : public QObject {
    Q_OBJECT
public:
    explicit LogBridge(int capacity = kLogLineCap,
                       QObject* parent = nullptr)
        : QObject(parent), buffer_(capacity) {}

    // Producer-side entry (any thread): format + buffer + emit. Never
    // throws — the logging contract (a dead receiver drops the emit,
    // the line stays in the buffer for the poll path).
    void post(const std::string& level, const std::string& logger_name,
              const std::string& message);
    // Pre-formatted line variant.
    void post_line(const std::string& line);

    std::vector<std::string> take_pending() {
        return buffer_.take_pending();
    }
    int pending_count() const { return buffer_.pending_count(); }

signals:
    void message_ready(const QString& line);

private:
    LogBuffer buffer_;
};

class WorkstationLogViewer : public QFrame {
    Q_OBJECT
public:
    explicit WorkstationLogViewer(QWidget* parent = nullptr);

    // The bridge this viewer drains (host-owned; may outlive us —
    // shutdown() only detaches, never destroys).
    void attach_bridge(LogBridge* bridge);
    LogBridge* bridge() const { return bridge_; }

    // Producer convenience: post straight into the attached bridge.
    void log(const std::string& level, const std::string& logger_name,
             const std::string& message);

    void shutdown();  // stop the poll timer + detach the signal

private:
    void drain_lines();

    QPlainTextEdit* logs_ = nullptr;
    LogBridge* bridge_ = nullptr;
    QTimer* poll_timer_ = nullptr;
    QMetaObject::Connection conn_;
};

class WorkstationConsolePane : public QFrame {
    Q_OBJECT
public:
    explicit WorkstationConsolePane(QWidget* parent = nullptr);
};

}  // namespace pwb::ui_workstation
