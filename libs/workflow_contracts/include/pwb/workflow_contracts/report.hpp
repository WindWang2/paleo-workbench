// CONV-23 — workflow/contracts/report.py port.
#pragma once

#include <filesystem>
#include <optional>
#include <string>
#include <utility>

#include <pwb/workflow_contracts/readiness.hpp>
#include <pwb/workflow_contracts/registry.hpp>

namespace pwb::workflow_contracts {

// Deterministic markdown reports (Python returns "\n".join(lines) — no
// trailing newline).
std::string generate_consultation_report(
    const WorkflowContractRegistry* registry = nullptr,
    const ProjectView* project = nullptr);

std::string generate_gap_report(
    const WorkflowContractRegistry* registry = nullptr);

// write_reports(out_dir): mkdir(parents=True, exist_ok=True) +
// write_text(encoding="utf-8"); returns (consult_path, gap_path).
std::pair<std::filesystem::path, std::filesystem::path> write_reports(
    const std::filesystem::path& out_dir,
    const ProjectView* project = nullptr,
    const WorkflowContractRegistry* registry = nullptr);

}  // namespace pwb::workflow_contracts
