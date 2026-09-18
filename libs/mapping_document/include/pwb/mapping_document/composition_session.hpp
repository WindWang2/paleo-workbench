// CompositionEditSession — undoable edit history over one Composition
// (CONV-27). Port of paleo_workbench/mapping/composer/components.py
// `CompositionEditSession` + `CompositionFactory`, over the CONV-02
// Composition data kernel.
//
// Parity contract (frozen by fixtures/map_document_edit_oracle.json):
//   * labels: "add <type>", "insert <type>", "remove <type>", "move",
//     "scale", "configure", "duplicate", "lock", "visibility",
//     "bring_to_front", "send_to_back", "raise";
//   * revision += 1 on every applied command and every undo/redo; a new
//     command clears the redo stack; clear_history does not touch revision;
//   * locked elements refuse move/scale/configure/remove/duplicate with
//     ComposerError; visibility/z-order/lock stay allowed;
//   * unknown ids raise UnknownElementError (Python KeyError) — except
//     remove/duplicate, which return nullopt like Python returns None
//     without creating a command;
//   * scale refuses non-positive sizes with the Python ValueError message;
//     the locked check comes first (Python order);
//   * remove's revert re-inserts at the captured index WITHOUT re-sorting
//     (Python inserts into the list directly);
//   * z-order commands capture the extreme z before mutating and restore it
//     on revert, with a stable sort by z_index both ways.
//
// C++-contract additions (no Python equivalent, same command semantics,
// documented in ledgers/27-decisions.md): set_paper / set_title /
// set_metadata and grouped edits (begin_group / end_group /
// rollback_group).
#pragma once

#include <pwb/mapping_document/composition.hpp>
#include <pwb/mapping_document/edit_command.hpp>

#include <array>
#include <functional>
#include <optional>
#include <stdexcept>
#include <string>

namespace pwb::mapping_document {

// Python ComposerError(RuntimeError): a composition command was refused.
class ComposerError : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

// Python KeyError from CompositionEditSession._require.
class UnknownElementError : public std::out_of_range {
public:
    using std::out_of_range::out_of_range;
};

// Frozen registry view: the C++ kernel does not port the registry *data*
// (CONV-02 decision D-10); the host supplies defaults per element type.
// Python get_spec degrades unknown types to the TEXT spec — a provider that
// mirrors that behavior simply returns its TEXT spec for unknown keys.
struct ElementSpec {
    std::array<double, 4> default_geometry{0.0, 0.0, 1.0, 1.0};
    Json default_properties;  // object payload
};
using SpecProvider = std::function<const ElementSpec*(const std::string& element_type)>;

// Creates elements and empty documents with authoring defaults.
class CompositionFactory {
public:
    CompositionFactory() = default;
    explicit CompositionFactory(SpecProvider provider);

    void set_spec_provider(SpecProvider provider) { provider_ = std::move(provider); }

    // D-04/D-27-04: new ids are the host's responsibility. The default
    // generator produces deterministic "el_%010x" counters so tests and
    // oracles are reproducible; product hosts inject a uuid-style generator.
    void set_element_id_generator(std::function<std::string()> generator);
    void set_id_prefix(const std::string& prefix) { id_prefix_ = prefix; }

    // properties must be a JSON object (Python Mapping) or null.
    ComposerElement create(const std::string& element_type,
                           std::optional<double> x_mm = std::nullopt,
                           std::optional<double> y_mm = std::nullopt,
                           std::optional<double> width_mm = std::nullopt,
                           std::optional<double> height_mm = std::nullopt,
                           Json properties = Json()) const;

    Composition create_document(const std::string& title = "",
                                const std::string& paper_size = "A4",
                                const std::string& orientation = "landscape",
                                double dpi = 300.0) const;

    std::string new_element_id() const {
        // Deterministic "%010x" counter unless the host injected a generator.
        return id_generator_ ? id_prefix_ + "_" + id_generator_()
                             : default_element_id();
    }

private:
    std::string default_element_id() const;

    SpecProvider provider_;
    std::function<std::string()> id_generator_;
    std::string id_prefix_ = "el";
    mutable long long next_id_ = 1;  // deterministic default generator counter
};

class CompositionEditSession {
public:
    // Non-owning document reference: the host (or a service facade) keeps
    // the Composition alive for the session's lifetime.
    CompositionEditSession(Composition& document, CompositionFactory factory = {});

    CompositionEditSession(const CompositionEditSession&) = delete;
    CompositionEditSession& operator=(const CompositionEditSession&) = delete;
    // Movable so service facades can rebind a session onto a reloaded
    // document (history resets on reload).
    CompositionEditSession(CompositionEditSession&&) = default;
    CompositionEditSession& operator=(CompositionEditSession&&) = default;

    // -- queries ----------------------------------------------------------
    bool can_undo() const { return stack_.can_undo(); }
    bool can_redo() const { return stack_.can_redo(); }
    long long revision() const { return stack_.revision(); }
    const CommandStack& stack() const { return stack_; }

    // -- commands (one undoable mutation each) ------------------------------
    ComposerElement add_element(const std::string& element_type,
                                std::optional<double> x_mm = std::nullopt,
                                std::optional<double> y_mm = std::nullopt,
                                std::optional<double> width_mm = std::nullopt,
                                std::optional<double> height_mm = std::nullopt,
                                Json properties = Json());
    void insert_element(ComposerElement element);
    // Missing id → nullopt, no command (Python returns None).
    std::optional<ComposerElement> remove_element(const std::string& element_id);
    void move_element(const std::string& element_id, double x_mm, double y_mm);
    void scale_element(const std::string& element_id, double width_mm,
                       double height_mm);
    // properties: JSON object merged into the element's existing properties
    // (Python dict.update); revert restores the whole previous object.
    void configure_element(const std::string& element_id, Json properties);
    std::optional<ComposerElement> duplicate_element(const std::string& element_id);
    void set_locked(const std::string& element_id, bool locked);
    void set_element_visible(const std::string& element_id, bool visible);

    // -- z-order ------------------------------------------------------------
    void bring_to_front(const std::string& element_id);
    void send_to_back(const std::string& element_id);
    void raise_element(const std::string& element_id);

    // -- composition-level (C++ contract; Python edits these directly) ------
    void set_paper(const std::string& paper_size, const std::string& orientation);
    void set_title(const std::string& title);
    void set_metadata(const std::string& key, Json value);

    // -- history --------------------------------------------------------------
    bool undo() { return stack_.undo(); }
    bool redo() { return stack_.redo(); }
    void clear_history() { stack_.clear_history(); }

    // -- grouped edit ---------------------------------------------------------
    void begin_group(const std::string& label) { stack_.begin_group(label); }
    void end_group() { stack_.end_group(); }
    void rollback_group() { stack_.rollback_group(); }
    bool group_open() const { return stack_.group_open(); }

private:
    const ComposerElement& require(const std::string& element_id) const;
    const ComposerElement& require_mutable(const std::string& element_id) const;
    void discard(const std::string& element_id);

    Composition* document_;
    CompositionFactory factory_;
    CommandStack stack_;
};

// Resolve every element's `data_binding` property against *binding_context*
// (components.py bind_template). A binding is
// {"key": "...", "fields": [...opt]}; context maps keys to property-update
// objects. Unresolved keys keep their defaults; returns the resolved count.
long long bind_template(Composition& document, const Json& binding_context);

}  // namespace pwb::mapping_document
