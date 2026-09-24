// Project/conversion algorithms for QGIS Processing:
//   paleo:project_validate_sources -> catalog::find_missing_sources over a
//                                    manifest JSON document
//   paleo:batch_convert            -> interchange::BatchConversionService over
//                                    the native model adapters
// Thin adapters: scanning and orchestration stay in the kernels.

#include <QVariant>

#include <qgsexception.h>
#include <qgsfeedback.h>
#include <qgsprocessingcontext.h>
#include <qgsprocessingfeedback.h>
#include <qgsprocessingoutputs.h>
#include <qgsprocessingparameters.h>

#include <pwb/domain/json.hpp>
#include <pwb/qgis_processing/algorithm_ids.hpp>
#include <pwb/qgis_processing/paleo_algorithm.hpp>

#include <pwb/catalog/document_index.hpp>
#include <pwb/catalog/models.hpp>
#include <pwb/catalog/repository.hpp>
#include <pwb/catalog/sources.hpp>
#include <pwb/interchange/batch.hpp>
#include <pwb/interchange/service.hpp>

#include <QFile>
#include <QTextStream>

#include <algorithm>
#include <cctype>
#include <filesystem>
#include <functional>
#include <set>
#include <string>
#include <system_error>
#include <utility>
#include <vector>

namespace pwb::qgis_processing {

namespace {

// ---- paleo:project_validate_sources -------------------------------------------

class ProjectValidateSourcesAlgorithm final : public PaleoAlgorithm {
public:
    QString name() const override {
        return QString::fromLatin1(kAlgProjectValidateSources);
    }
    QString displayName() const override {
        return QStringLiteral("Validate project data sources");
    }
    QString groupId() const override { return QString::fromLatin1(kGroupProject); }
    QString group() const override { return QStringLiteral("Project"); }
    QString shortHelpString() const override {
        return QStringLiteral(
            "Stat-only missing-source scan (catalog kernel): checks every live "
            "version's recorded path against PROJECT's first-resolution rung "
            "(managed project-join / recorded absolute / naive "
            "project-relative). Managed payloads are included only when "
            "INCLUDE_MANAGED is set. REPORT is a JSON array of "
            "{path, reason, version_id}.");
    }

protected:
    void initAlgorithm(const QVariantMap& = QVariantMap()) override {
        addParameter(new QgsProcessingParameterFile(
            QStringLiteral("PROJECT"), QStringLiteral("Project folder"),
            Qgis::ProcessingFileParameterBehavior::Folder));
        addParameter(new QgsProcessingParameterFile(
            QStringLiteral("DOCUMENT"), QStringLiteral("Catalog document (JSON)"),
            Qgis::ProcessingFileParameterBehavior::File,
            QStringLiteral("json")));
        addParameter(new QgsProcessingParameterBoolean(
            QStringLiteral("INCLUDE_MANAGED"),
            QStringLiteral("Include managed payloads"), false));
        addParameter(new QgsProcessingParameterFileDestination(
            QStringLiteral("REPORT"), QStringLiteral("Missing-source report (JSON)"),
            QStringLiteral("JSON files (*.json)")));
        addOutput(new QgsProcessingOutputNumber(
            QStringLiteral("MISSING_COUNT"), QStringLiteral("Missing source count")));
    }

    QVariantMap processAlgorithm(const QVariantMap& parameters,
                                 QgsProcessingContext& context,
                                 QgsProcessingFeedback* feedback) override {
        const std::filesystem::path project_path = std::filesystem::path(
            parameterAsFile(parameters, QStringLiteral("PROJECT"), context)
                .toStdString());
        const std::filesystem::path document_path = std::filesystem::path(
            parameterAsFile(parameters, QStringLiteral("DOCUMENT"), context)
                .toStdString());

        const pwb::domain::Result<pwb::catalog::ManifestLoad> loaded =
            pwb::catalog::load_manifest(document_path);
        if (!loaded.is_ok()) {
            throw QgsProcessingException(
                QStringLiteral("cannot load DOCUMENT %1: %2")
                    .arg(QString::fromStdString(document_path.string()))
                    .arg(QString::fromStdString(loaded.error().message)));
        }
        const pwb::catalog::CatalogDocument& document = loaded.value().document;
        const pwb::catalog::DocumentIndex index(document);

        const std::function<bool()> cancel = [feedback]() {
            return feedback != nullptr && feedback->isCanceled();
        };
        const pwb::catalog::MissingSourceReport report = pwb::catalog::find_missing_sources(
            document, index, project_path,
            parameterAsBool(parameters, QStringLiteral("INCLUDE_MANAGED"), context),
            cancel);
        if (feedback != nullptr && feedback->isCanceled()) return {};

        pwb::domain::Json entries = pwb::domain::Json::array();
        for (const pwb::catalog::MissingSource& entry : report.entries) {
            pwb::domain::Json row = pwb::domain::Json::object();
            row["path"] = entry.recorded_path;
            row["reason"] = std::string(entry.managed ? "managed payload not found"
                                                      : "external source not found");
            row["version_id"] = entry.version_id;
            entries.push_back(std::move(row));
        }

        const QString report_path = parameterAsOutputLayer(
            parameters, QStringLiteral("REPORT"), context);
        QFile output(report_path);
        if (!output.open(QIODevice::WriteOnly | QIODevice::Truncate)) {
            throw QgsProcessingException(
                QStringLiteral("cannot write REPORT file %1").arg(report_path));
        }
        QTextStream stream(&output);
        stream.setEncoding(QStringConverter::Utf8);
        stream << QString::fromStdString(entries.dump(2));
        stream.flush();
        if (stream.status() != QTextStream::Ok) {
            throw QgsProcessingException(
                QStringLiteral("short write to REPORT file %1").arg(report_path));
        }

        QVariantMap results;
        results.insert(QStringLiteral("REPORT"), report_path);
        results.insert(QStringLiteral("MISSING_COUNT"),
                       static_cast<qlonglong>(report.entries.size()));
        if (feedback != nullptr) feedback->setProgress(100.0);
        return results;
    }

    QgsProcessingAlgorithm* createInstance() const override {
        return new ProjectValidateSourcesAlgorithm();
    }
};

// ---- paleo:batch_convert --------------------------------------------------------

// Export-capable (format_id, display_name) pairs of the native adapter
// registry, insertion order — the FORMAT enum options.
[[nodiscard]] std::vector<std::pair<std::string, std::string>>
export_format_options() {
    static const std::vector<std::pair<std::string, std::string>> options = [] {
        std::vector<std::pair<std::string, std::string>> result;
        const pwb::interchange::NativeInterchangeService service;
        for (const pwb::domain::Json& row : service.capability_matrix()) {
            if (!row.value("export", false)) continue;
            result.emplace_back(row.value("format_id", std::string()),
                                row.value("display_name", std::string()));
        }
        return result;
    }();
    return options;
}

class BatchConvertAlgorithm final : public PaleoAlgorithm {
public:
    QString name() const override { return QString::fromLatin1(kAlgBatchConvert); }
    QString displayName() const override {
        return QStringLiteral("Batch convert model files");
    }
    QString groupId() const override { return QString::fromLatin1(kGroupProject); }
    QString group() const override { return QStringLiteral("Project"); }
    QString shortHelpString() const override {
        return QStringLiteral(
            "Batch-converts model files under INPUT (recursive) to FORMAT "
            "through the native interchange adapters: bounded concurrency, "
            "per-item failure isolation, deterministic collision-suffixed "
            "output names. Files whose extension no adapter recognizes are "
            "not scheduled. REPORT is the batch JSON result.");
    }

protected:
    void initAlgorithm(const QVariantMap& = QVariantMap()) override {
        QStringList format_labels;
        for (const auto& [format_id, display_name] : export_format_options()) {
            format_labels << QString::fromStdString(display_name);
        }
        addParameter(new QgsProcessingParameterFile(
            QStringLiteral("INPUT"), QStringLiteral("Input folder"),
            Qgis::ProcessingFileParameterBehavior::Folder));
        addParameter(new QgsProcessingParameterEnum(
            QStringLiteral("FORMAT"), QStringLiteral("Target format"),
            format_labels));
        addParameter(new QgsProcessingParameterNumber(
            QStringLiteral("WORKERS"), QStringLiteral("Worker count"),
            Qgis::ProcessingNumberParameterType::Integer, 2, false, 1, 4));
        addParameter(new QgsProcessingParameterFolderDestination(
            QStringLiteral("OUTPUT"), QStringLiteral("Output folder")));
        addParameter(new QgsProcessingParameterFileDestination(
            QStringLiteral("REPORT"), QStringLiteral("Batch report (JSON)"),
            QStringLiteral("JSON files (*.json)")));
        addOutput(new QgsProcessingOutputNumber(
            QStringLiteral("CONVERTED"), QStringLiteral("Converted count")));
        addOutput(new QgsProcessingOutputNumber(
            QStringLiteral("FAILED"), QStringLiteral("Failed count")));
        addOutput(new QgsProcessingOutputNumber(
            QStringLiteral("SKIPPED"), QStringLiteral("Skipped count")));
    }

    QVariantMap processAlgorithm(const QVariantMap& parameters,
                                 QgsProcessingContext& context,
                                 QgsProcessingFeedback* feedback) override {
        const std::vector<std::pair<std::string, std::string>> formats =
            export_format_options();
        const int format_index = parameterAsEnum(
            parameters, QStringLiteral("FORMAT"), context);
        if (format_index < 0 || static_cast<std::size_t>(format_index) >= formats.size()) {
            throw QgsProcessingException(
                QStringLiteral("FORMAT index %1 is out of range").arg(format_index));
        }
        const std::string target_format =
            formats[static_cast<std::size_t>(format_index)].first;

        const std::filesystem::path input_dir(parameterAsFile(
            parameters, QStringLiteral("INPUT"), context).toStdString());
        const std::filesystem::path output_dir(parameterAsOutputLayer(
            parameters, QStringLiteral("OUTPUT"), context).toStdString());
        std::error_code ec;
        std::filesystem::create_directories(output_dir, ec);
        if (ec) {
            throw QgsProcessingException(
                QStringLiteral("cannot create OUTPUT folder %1: %2")
                    .arg(QString::fromStdString(output_dir.string()))
                    .arg(QString::fromStdString(ec.message())));
        }

        // Extensions the adapter registry can recognize (lowercase).
        pwb::interchange::NativeInterchangeService service;
        std::set<std::string> known_extensions;
        for (const pwb::domain::Json& row : service.capability_matrix()) {
            for (const auto& extension : row.value("extensions",
                                                   std::vector<std::string>{})) {
                known_extensions.insert(extension);
            }
        }

        std::vector<pwb::interchange::ConversionJob> jobs;
        if (std::filesystem::is_directory(input_dir)) {
            for (const auto& entry :
                 std::filesystem::recursive_directory_iterator(input_dir, ec)) {
                if (ec) break;
                if (!entry.is_regular_file()) continue;
                std::string extension =
                    entry.path().extension().string();
                if (!extension.empty() && extension.front() == '.') {
                    extension.erase(extension.begin());
                }
                std::transform(extension.begin(), extension.end(), extension.begin(),
                               [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
                if (known_extensions.count(extension) == 0) continue;
                pwb::interchange::ConversionJob job;
                job.source = entry.path();
                job.target_format = target_format;
                jobs.push_back(std::move(job));
            }
        }
        if (jobs.empty()) {
            throw QgsProcessingException(
                QStringLiteral("no convertible model files under %1")
                    .arg(QString::fromStdString(input_dir.string())));
        }
        std::sort(jobs.begin(), jobs.end(),
                  [](const pwb::interchange::ConversionJob& a,
                     const pwb::interchange::ConversionJob& b) {
                      return a.source.string() < b.source.string();
                  });

        const int workers = parameterAsInt(
            parameters, QStringLiteral("WORKERS"), context);
        const pwb::interchange::BatchConversionService batch(
            service, workers);

        // QGIS feedback -> interchange CancelToken bridge (item boundaries).
        pwb::interchange::CancelToken cancel_token;
        QMetaObject::Connection connection =
            QObject::connect(feedback, &QgsFeedback::canceled, feedback,
                              [&cancel_token]() { cancel_token.cancel(); },
                              Qt::DirectConnection);
        pwb::interchange::BatchProgressFn progress;
        if (feedback != nullptr) {
            progress = [feedback](int done, int total,
                                  const std::string& current) {
                if (total > 0) {
                    feedback->setProgress(100.0 * static_cast<double>(done) /
                                          static_cast<double>(total));
                }
                feedback->setProgressText(QString::fromStdString(current));
            };
        }
        const pwb::interchange::BatchResult result =
            batch.convert(jobs, output_dir, cancel_token, progress,
                          /*verify=*/true);
        QObject::disconnect(connection);
        if (feedback != nullptr && feedback->isCanceled()) return {};

        qlonglong converted = 0;
        qlonglong failed = 0;
        qlonglong skipped = 0;
        for (const pwb::interchange::BatchItemResult& item : result.results) {
            if (item.status == "converted") {
                ++converted;
            } else if (item.status == "failed") {
                ++failed;
            } else if (item.status == "skipped") {
                ++skipped;
            }
        }

        const QString report_path = parameterAsOutputLayer(
            parameters, QStringLiteral("REPORT"), context);
        QFile output(report_path);
        if (!output.open(QIODevice::WriteOnly | QIODevice::Truncate)) {
            throw QgsProcessingException(
                QStringLiteral("cannot write REPORT file %1").arg(report_path));
        }
        QTextStream stream(&output);
        stream.setEncoding(QStringConverter::Utf8);
        stream << QString::fromStdString(result.to_json().dump(2));
        stream.flush();
        if (stream.status() != QTextStream::Ok) {
            throw QgsProcessingException(
                QStringLiteral("short write to REPORT file %1").arg(report_path));
        }

        QVariantMap results;
        results.insert(QStringLiteral("OUTPUT"),
                       QString::fromStdString(output_dir.string()));
        results.insert(QStringLiteral("REPORT"), report_path);
        results.insert(QStringLiteral("CONVERTED"), converted);
        results.insert(QStringLiteral("FAILED"), failed);
        results.insert(QStringLiteral("SKIPPED"), skipped);
        if (feedback != nullptr) feedback->setProgress(100.0);
        return results;
    }

    QgsProcessingAlgorithm* createInstance() const override {
        return new BatchConvertAlgorithm();
    }
};

}  // namespace

std::vector<QgsProcessingAlgorithm*> make_project_algorithms() {
    std::vector<QgsProcessingAlgorithm*> algorithms;
    algorithms.push_back(new ProjectValidateSourcesAlgorithm());
    algorithms.push_back(new BatchConvertAlgorithm());
    return algorithms;
}

}  // namespace pwb::qgis_processing
