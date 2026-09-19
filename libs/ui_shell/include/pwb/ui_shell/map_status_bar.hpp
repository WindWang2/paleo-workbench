#pragma once

// Port of paleo_workbench/ui/map_status_bar.py (UI-01).
// Compact status readout for the unified GIS canvas (V10 Goal §14–§17):
// edit-target/dirty, snapping/topology (with error counts), CRS (with
// mismatch warning), scale, selection — all persistent readouts; details
// (tolerance/modes/recommendations) live in tooltips. The host projects
// facts from the canonical ToolContext via apply_context; this widget
// holds the presentation vocabulary and zero business judgment.

#include <QFrame>
#include <QLabel>
#include <QStringList>

#include <array>
#include <functional>
#include <map>
#include <optional>
#include <set>
#include <string>
#include <vector>

namespace pwb::ui_shell {

// Status-bar CRS short name: auth id verbatim; custom +proj strings fold to
// "本地坐标" (with （米） when +units=m). Empty input → "" (caller renders
// 「未声明」). The full declared value only ever goes into tooltips.
QString short_crs_name(const QString& text);

// Scale readout: "1:N" (thousands separators); 0/unknown/<1 → honest
// "1:—" — never fabricate precision.
QString format_scale(double denominator);

// Coordinate decimals policy: geographic CRS → 6 (≈0.1 m); projected → 2.
// The Python original resolves via pyproj with a magnitude fallback
// (|x|≤360 & |y|≤90 → geographic). Native: the resolver is injectable
// (platform wiring can bind a QGIS/PROJ lookup); the default is the same
// magnitude heuristic Python uses when pyproj is missing.
using CrsDecimalsResolver =
    std::function<std::optional<bool>(const QString& crs)>;
void set_crs_decimals_resolver(CrsDecimalsResolver resolver);
int coordinate_decimals(const QString& crs,
                        const std::pair<double, double>* point);

// Canonical fact projection consumed by apply_context — every key is
// optional and absent keys leave the current readout untouched. Mirrors
// the Python facts dict exactly.
struct MapStatusFacts {
    std::optional<std::pair<double, double>> point;
    std::optional<std::string> crs;
    std::optional<std::string> renderer;
    std::optional<double> scale_denominator;
    std::optional<int> selection_count;
    std::optional<bool> snapping_enabled;
    std::optional<double> snapping_tolerance_px;  // effective, overrides win
    std::optional<std::vector<std::string>> snapping_modes;
    std::optional<int> snapping_reference_count;
    std::optional<bool> snapping_role_recommended;
    std::optional<bool> snapping_available;  // absent → true
    std::optional<bool> topology_enabled;
    std::optional<int> topology_error_count;
    std::optional<bool> crs_mismatch;
    std::optional<std::string> layer_crs;
    std::optional<bool> editing;
    std::optional<bool> dirty;
    std::optional<std::string> layer_name;
    std::optional<bool> raw_locked;
    std::optional<bool> layer_frozen;
    // Three-state edit gate: true/false/absent → open/closed/unknown.
    std::optional<bool> edit_gate_open;
    std::optional<std::string> edit_gate_reason;
    std::optional<bool> save_blocked;
};

class MapStatusBar : public QFrame {
    Q_OBJECT
public:
    explicit MapStatusBar(QWidget* parent = nullptr);

    // --- high-frequency light paths (R5: pointer/extent events never
    // rebuild the full fact set or re-parse styles) ---
    void update_coordinate(std::pair<double, double> point,
                           const QString& crs = QString());
    void update_scale(double denominator);
    // V7 native measure display (empty string clears). Independent of
    // update_state: measure events arrive at pointer frequency.
    void set_measure(const QString& text);

    // Last native snap hit (snap_feedback intake, V12 M0-4): tooltip only,
    // never the chip text — a per-pixel event must not fight the
    // authoritative apply_context state.
    void set_snap_match(bool matched, const QString& match_type = QString(),
                        const QString& layer_doc_id = QString(),
                        std::optional<double> distance = std::nullopt);

    // --- V10 legacy entry (subset keyword path for old map pages) ---
    struct LegacyState {
        std::optional<std::pair<double, double>> point;
        std::optional<std::array<double, 4>> extent;
        std::string crs;
        std::string renderer;
        int selection_count = 0;
        bool editing = false;
        std::string editing_label;
        std::optional<bool> snapping;
        double scale_denominator = 0.0;
    };
    void update_state(const LegacyState& state);

    // --- V10 main entry: canonical ToolContext projection ---
    void apply_context(const MapStatusFacts& facts);

signals:
    // topology_activated — issue-chip click (enter validation/locate);
    // snapping_activated — snapping readout click (open snap settings).
    void topology_activated();
    void snapping_activated();

protected:
    void resizeEvent(QResizeEvent* event) override;
    void mousePressEvent(QMouseEvent* event) override;
    void mouseReleaseEvent(QMouseEvent* event) override;

private:
    enum class ChipMode { Emphasis, Warning, Neutral };

    QString snap_tooltip_text() const;
    int decimals_for(const QString& crs,
                     const std::pair<double, double>* point);
    void apply_edit_chip(bool editing, const QString& editing_label,
                         bool dirty, bool raw_locked, bool frozen,
                         bool gate_closed, const QString& gate_reason,
                         bool editable_unknown, bool save_blocked);
    QString render_edit_chip() const;
    QString render_issue_chip() const;
    void apply_collapse();
    const char* hit_clickable(const QPoint& pos) const;

    QLabel* coordinate_ = nullptr;
    QLabel* scale_ = nullptr;
    QLabel* crs_ = nullptr;
    QLabel* render_ = nullptr;
    QLabel* selection_ = nullptr;
    QLabel* snapping_ = nullptr;
    QLabel* topology_ = nullptr;
    QLabel* measure_ = nullptr;
    QLabel* topology_issue_ = nullptr;
    QLabel* edit_ = nullptr;

    std::map<std::string, QLabel*> labels_;  // collapsible set
    QStringList snap_tip_lines_;
    struct SnapMatch {
        bool matched = false;
        QString match_type;
        QString layer_doc_id;
        std::optional<double> distance;
    };
    std::optional<SnapMatch> last_snap_match_;

    QString crs_decimals_key_;
    bool crs_decimals_valid_ = false;
    int coord_decimals_ = 2;  // _PROJECTED_DECIMALS

    ChipMode edit_chip_mode_ = ChipMode::Neutral;
    bool edit_chip_mode_set_ = false;
    bool issue_visible_ = false;
    bool crs_warning_ = false;
    std::set<std::string> collapsed_;
    const char* press_inside_ = nullptr;
};

}  // namespace pwb::ui_shell
