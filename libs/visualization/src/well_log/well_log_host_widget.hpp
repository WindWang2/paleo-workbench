#pragma once

// Well-log host adapter over the real well-log-engine C++ SDK (C2).
//
// This widget is the C-line replacement for the Python WellLogHost bridge:
// it talks to welllog::WellLogSession / welllog::WellLogView directly — no
// Shiboken, no integer widget addresses, no Python. Selection/range changes
// are translated into the Qt-free pwb::viz::SelectionEventV1 contract so the
// application layer can fan them out without any Qt type.
//
// No Q_OBJECT on purpose (no custom signals): the selection callback is a
// std::function, keeping this translation unit moc-free.

#include <cstdint>
#include <functional>
#include <memory>

#include <QWidget>

#include <pwb/viz/selection.hpp>

namespace welllog {
class WellLogSession;
class WellLogView;
} // namespace welllog

namespace pwb::viz {

class WellLogHostWidget final : public QWidget {
public:
    using SelectionCallback = std::function<void(const SelectionEventV1&)>;

    explicit WellLogHostWidget(QWidget* parent = nullptr);
    ~WellLogHostWidget() override;

    WellLogHostWidget(const WellLogHostWidget&) = delete;
    WellLogHostWidget& operator=(const WellLogHostWidget&) = delete;

    // Parses a real LAS file with the engine's LasSourceAdapter, builds one
    // track per curve (linear scale from the curve's finite value range) and
    // submits document + presentation to the session. Returns false and fills
    // *error on parse or submission failure.
    [[nodiscard]] bool load_las(const class QString& path, class QString* error = nullptr);

    void set_selection_callback(SelectionCallback callback);

    // Issues SetSelectionCommand on the loaded document's first sampling
    // axis (reference depth, engine units).
    bool select_depth_range(double top, double bottom);
    void clear_selection();
    void reset_viewport();

    // --- introspection for hosts and tests -------------------------------
    [[nodiscard]] welllog::WellLogView* view() const noexcept;
    [[nodiscard]] welllog::WellLogSession* session() const noexcept;
    [[nodiscard]] bool has_document() const noexcept;
    [[nodiscard]] QString document_id_text() const;
    [[nodiscard]] std::uint64_t document_revision() const noexcept;
    // Number of recoverable LAS diagnostics observed by the last load.
    [[nodiscard]] std::size_t last_load_diagnostics() const noexcept;

private:
    struct State;
    std::unique_ptr<State> state_;
};

} // namespace pwb::viz
