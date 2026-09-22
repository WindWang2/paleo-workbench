from __future__ import annotations

from paleo_workbench.ui import tokens


def derive_rule_result(rule: str, issues: list[dict]) -> tuple[str, str, str]:
    """Derive (severity, result_text, color_hex) for a single QC rule.

    Scans issues for entries where issue["rule"] == rule. If multiple match,
    error takes precedence over warning. Returns ("pass", "✓通过", SUCCESS) if
    no matching issue exists.
    """
    matching = [i for i in issues if i.get("rule") == rule]
    if not matching:
        return ("pass", tokens.QC_RESULT_LABELS["pass"], tokens.SUCCESS)
    # error takes precedence over warning
    severity = "warning"
    for i in matching:
        s = i.get("severity", "warning")
        if s == "error":
            severity = "error"
            break
    message = matching[0].get("message", "")  # use first matching issue's message
    text = f"{tokens.QC_RESULT_LABELS[severity]} {message}".rstrip()
    color = tokens.QC_RESULT_COLORS[severity]
    return (severity, text, color)
