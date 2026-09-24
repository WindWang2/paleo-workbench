// Read-only Python environment diagnostics (Prompt 7, Phase L).
//
// Everything is obtained by evaluating expressions inside the already-running
// QGIS Python runtime — nothing is imported for its side effects, nothing is
// installed, nothing is written.

#include <pwb/qgis_python/python_diagnostics.hpp>

#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QStringList>

#include <qgsapplication.h>

#include <pwb/qgis_python/python_runtime.hpp>

namespace pwb::qgis_python {

namespace {

// Keys that may appear in the environment section. Everything else is
// reported as "<redacted>" (09-security-trust-model.md §6).
bool isEnvAllowed(const QString& key) {
    static const QStringList allowed{
        QStringLiteral("PATH"),
        QStringLiteral("PYTHONPATH"),
        QStringLiteral("PYTHONHOME"),
        QStringLiteral("QGIS_PREFIX_PATH"),
        QStringLiteral("PYQGIS_STARTUP"),
        QStringLiteral("QT_QPA_PLATFORM"),
        QStringLiteral("HOME"),
        QStringLiteral("USERPROFILE"),
    };
    return allowed.contains(key.toUpper());
}

QString sanitizeEnvValue(const QString& key, const QString& value) {
    Q_UNUSED(key)
    // PATH-like values can be very long and frequently contain user paths;
    // keep the first entries and mark truncation explicitly.
    const int kMax = 512;
    if (value.size() <= kMax) {
        return value;
    }
    return value.left(kMax) + QStringLiteral(" …[truncated]");
}

QString evalExpr(const QString& expression) {
    QString value;
    if (!PythonRuntime::instance().evalString(expression, &value)) {
        return QString();
    }
    value.remove(QLatin1Char('\''));
    return value.trimmed();
}

QString pythonList(const QString& expression, int limit) {
    const QString raw = evalExpr(expression);
    if (raw.isEmpty()) {
        return QString();
    }
    // Expression results come back as repr() strings; strip the brackets and
    // quotes so the report carries plain entries.
    QString body = raw;
    if (body.startsWith(QLatin1Char('[')) && body.endsWith(QLatin1Char(']'))) {
        body = body.mid(1, body.size() - 2);
    }
    const QStringList parts = body.split(QStringLiteral(", "));
    QStringList out;
    for (const QString& part : parts) {
        QString entry = part;
        entry.remove(QLatin1Char('\''));
        entry.remove(QLatin1Char('"'));
        if (!entry.isEmpty()) {
            out.push_back(entry);
        }
        if (out.size() >= limit) {
            break;
        }
    }
    return out.join(QStringLiteral("\n"));
}

}  // namespace

QString PythonDiagnostics::pythonScalar(const QString& expression) {
    QString value;
    if (!PythonRuntime::instance().evalString(expression, &value)) {
        return QString();
    }
    value.remove(QLatin1Char('\''));
    return value.trimmed();
}

QString PythonDiagnostics::reportJson() {
    PythonRuntime& runtime = PythonRuntime::instance();
    const PythonCapability cap = runtime.capability();

    QJsonObject root;
    root.insert(QStringLiteral("pythonAvailable"), cap.runtimeAvailable);
    root.insert(QStringLiteral("pythonEnabled"), cap.pythonEnabled);
    root.insert(QStringLiteral("bindingsAvailable"), cap.bindingsAvailable);
    root.insert(QStringLiteral("processingAvailable"), cap.processingAvailable);
    root.insert(QStringLiteral("consoleAvailable"), cap.consoleAvailable);
    root.insert(QStringLiteral("qgispythonLibrary"), cap.libraryPath);
    root.insert(QStringLiteral("qgispythonError"), cap.libraryError);
    root.insert(QStringLiteral("qgisVersion"), cap.qgisVersion);
    root.insert(QStringLiteral("pythonVersion"), cap.pythonVersion);
    root.insert(QStringLiteral("runnerInstalled"), cap.runnerInstalled);

    // QGIS-side paths (native, no Python needed).
    root.insert(QStringLiteral("qgisSettingsDirPath"),
                QgsApplication::qgisSettingsDirPath());
    root.insert(QStringLiteral("pkgDataPath"), QgsApplication::pkgDataPath());
    root.insert(QStringLiteral("libraryPath"), QgsApplication::libraryPath());

    if (!cap.pythonEnabled) {
        root.insert(QStringLiteral("note"),
                    QStringLiteral("QGIS Python runtime is not enabled; "
                                   "Python-side fields are unavailable."));
        return QString::fromUtf8(
            QJsonDocument(root).toJson(QJsonDocument::Indented));
    }

    root.insert(QStringLiteral("pyQgisVersion"),
                pythonScalar(QStringLiteral(
                    "__import__('qgis.core',fromlist=['x']).Qgis.QGIS_VERSION")));
    root.insert(QStringLiteral("pyqtVersion"),
                pythonScalar(QStringLiteral(
                    "__import__('PyQt6.QtCore',fromlist=['x']).QT_VERSION_STR")));
    root.insert(
        QStringLiteral("sipVersion"),
        pythonScalar(QStringLiteral(
            "__import__('PyQt6.sip',fromlist=['x']).SIP_VERSION_STR")));
    root.insert(QStringLiteral("sysPrefix"),
                pythonScalar(QStringLiteral("__import__('sys').prefix")));
    root.insert(QStringLiteral("sysExecutable"),
                pythonScalar(QStringLiteral("__import__('sys').executable")));

    const QString pathEntries = pythonList(
        QStringLiteral("[p for p in __import__('sys').path if p]"), 64);
    QJsonArray sysPath;
    for (const QString& entry :
         pathEntries.split(QLatin1Char('\n'), Qt::SkipEmptyParts)) {
        sysPath.push_back(entry);
    }
    root.insert(QStringLiteral("sysPath"), sysPath);

    const QString pluginPaths = pythonList(
        QStringLiteral("[p for p in __import__('sys').path if 'plugins' in p]"),
        32);
    QJsonArray plugins;
    for (const QString& entry :
         pluginPaths.split(QLatin1Char('\n'), Qt::SkipEmptyParts)) {
        plugins.push_back(entry);
    }
    root.insert(QStringLiteral("pluginPaths"), plugins);

    root.insert(QStringLiteral("loadedPlugins"),
                pythonList(QStringLiteral(
                               "__import__('qgis.utils',fromlist=['x'])"
                               ".active_plugins[:]"),
                           128));

    // Sanitised environment: allow-listed keys only.
    QJsonObject env;
    const QStringList keys = QStringList{
        QStringLiteral("PATH"),       QStringLiteral("PYTHONPATH"),
        QStringLiteral("PYTHONHOME"), QStringLiteral("QGIS_PREFIX_PATH"),
        QStringLiteral("PYQGIS_STARTUP"), QStringLiteral("QT_QPA_PLATFORM"),
    };
    for (const QString& key : keys) {
        if (!isEnvAllowed(key)) {
            continue;
        }
        const QString value = pythonScalar(
            QStringLiteral("__import__('os').environ.get('%1','')").arg(key));
        env.insert(key, sanitizeEnvValue(key, value));
    }
    root.insert(QStringLiteral("environment"), env);

    return QString::fromUtf8(QJsonDocument(root).toJson(QJsonDocument::Indented));
}

QString PythonDiagnostics::reportText() {
    const QJsonDocument doc =
        QJsonDocument::fromJson(reportJson().toUtf8());
    if (!doc.isObject()) {
        return reportJson();
    }
    const QJsonObject root = doc.object();
    QStringList lines;
    lines.push_back(QStringLiteral("QGIS Python runtime diagnostics"));
    lines.push_back(QStringLiteral("--------------------------------"));
    for (auto it = root.constBegin(); it != root.constEnd(); ++it) {
        const QJsonValue value = it.value();
        if (value.isString()) {
            lines.push_back(QStringLiteral("%1: %2")
                                .arg(it.key(), value.toString()));
        } else if (value.isBool()) {
            lines.push_back(QStringLiteral("%1: %2")
                                .arg(it.key(), value.toBool()
                                                   ? QStringLiteral("yes")
                                                   : QStringLiteral("no")));
        } else if (value.isArray()) {
            lines.push_back(QStringLiteral("%1:").arg(it.key()));
            for (const QJsonValue& entry : value.toArray()) {
                lines.push_back(QStringLiteral("  - %1").arg(entry.toString()));
            }
        } else if (value.isObject()) {
            lines.push_back(QStringLiteral("%1:").arg(it.key()));
            const QJsonObject obj = value.toObject();
            for (auto e = obj.constBegin(); e != obj.constEnd(); ++e) {
                lines.push_back(QStringLiteral("  %1 = %2")
                                    .arg(e.key(), e.value().toString()));
            }
        }
    }
    return lines.join(QStringLiteral("\n"));
}

}  // namespace pwb::qgis_python
