#pragma once

// Port of paleo_workbench/mapping/tool_help.py (UI-12).
// Static tool-help registry (pure data, no Qt).
//
// TOOL_LABELS / TOOL_SHORTCUTS / TOOL_HELP are the single registry of
// names, shortcuts, and help facts for the tool surface. Dynamic
// derivation (explain/format_*) lives in action_help.hpp; dynamic
// availability lives ONLY in pwb::tool_policy (no second evaluator).
//
// Qt-free.

#include <map>
#include <string>

namespace pwb::ui_workstation {

// One tool's static help facts (registry; contains no availability
// judgment).
struct ToolHelpSpec {
    std::string label;
    std::string requirements;   // required preconditions (human readable)
    std::string impact;         // execution impact
    bool modifies_data = false;
    bool creates_version = false;
    bool background_task = false;
    std::string stages;         // applicable stages (presentation word)
    std::string layer_kinds;    // applicable layer kinds (presentation word)
};

// tool_id -> display label (registry order preserved = Python dict order).
const std::map<std::string, std::string>& tool_labels();
// tool_id -> shortcut text (mirror of the QAction registry for help text).
const std::map<std::string, std::string>& tool_shortcuts();
// tool_id -> static help spec.
const std::map<std::string, ToolHelpSpec>& tool_help();

// Lookup helpers (nullptr when unknown).
const ToolHelpSpec* tool_help_for(const std::string& tool_id);
std::string tool_label(const std::string& tool_id);
std::string tool_shortcut(const std::string& tool_id);

}  // namespace pwb::ui_workstation
