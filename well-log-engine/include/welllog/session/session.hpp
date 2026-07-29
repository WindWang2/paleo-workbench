#pragma once

#include <cstdint>
#include <memory>
#include <optional>
#include <span>
#include <vector>

#include <welllog/core/document.hpp>
#include <welllog/core/result.hpp>
#include <welllog/session/export.hpp>

namespace welllog {

struct SetDocumentCommand {
  WellLogDocument document;
};

struct CommandReceipt {
  std::uint64_t state_version{};
  EntityId document_id;
  DocumentRevision document_revision;
  bool asynchronous_preparation_started{};
  std::optional<std::uint64_t> diagnostic_id;
};

enum class ViewEventKind : std::uint8_t {
  documents_changed,
  diagnostic_published,
};

struct ViewEvent {
  ViewEventKind kind{ViewEventKind::documents_changed};
  std::uint64_t state_version{};
  EntityId document_id;
  DocumentRevision document_revision;
};

enum class DiagnosticCode : std::uint16_t {
  missing_samples,
};

struct Diagnostic {
  std::uint64_t id{};
  DiagnosticCode code{DiagnosticCode::missing_samples};
  Severity severity{Severity::warning};
  EntityId document_id;
  EntityId entity_id;
  DocumentRevision document_revision;
  std::uint64_t occurrence_count{};
};

class WELLLOG_SESSION_API WellLogSession {
public:
  WellLogSession();
  ~WellLogSession();
  WellLogSession(WellLogSession &&) noexcept;
  WellLogSession &operator=(WellLogSession &&) noexcept;
  WellLogSession(const WellLogSession &) = delete;
  WellLogSession &operator=(const WellLogSession &) = delete;

  [[nodiscard]] Result<CommandReceipt> execute(SetDocumentCommand command);
  [[nodiscard]] std::span<const ViewEvent> events() const noexcept;
  void clear_events() noexcept;
  [[nodiscard]] std::span<const Diagnostic> diagnostics() const noexcept;
  [[nodiscard]] std::shared_ptr<const WellLogDocument>
  document(EntityId id) const noexcept;

private:
  struct Impl;
  std::unique_ptr<Impl> impl_;
};

} // namespace welllog
