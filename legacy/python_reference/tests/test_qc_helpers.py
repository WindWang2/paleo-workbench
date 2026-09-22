from paleo_workbench.ui import tokens
from paleo_workbench.ui.pages.qc_helpers import derive_rule_result


def test_derive_no_issue_returns_pass():
    issues = [{"rule": "other", "severity": "error", "message": "x"}]
    severity, text, color = derive_rule_result("层级一致性", issues)
    assert severity == "pass"
    assert text == "✓通过"
    assert color == tokens.SUCCESS


def test_derive_warning_issue():
    issues = [{"rule": "未分类区域", "severity": "warning", "message": "1处"}]
    severity, text, color = derive_rule_result("未分类区域", issues)
    assert severity == "warning"
    assert "!警告" in text
    assert "1处" in text
    assert color == tokens.WARNING


def test_derive_error_precedence():
    """Regression: a rule with BOTH warning and error issues → error wins."""
    issues = [
        {"rule": "低可信区", "severity": "warning", "message": "warn-msg"},
        {"rule": "低可信区", "severity": "error", "message": "err-msg"},
    ]
    severity, text, color = derive_rule_result("低可信区", issues)
    assert severity == "error"
    assert color == tokens.ERROR_RED
    assert "!待处理" in text


def test_derive_uses_first_message():
    """Multiple warning issues → text uses first matching issue's message."""
    issues = [
        {"rule": "未分类区域", "severity": "warning", "message": "first-msg"},
        {"rule": "未分类区域", "severity": "warning", "message": "second-msg"},
    ]
    severity, text, color = derive_rule_result("未分类区域", issues)
    assert severity == "warning"
    assert "first-msg" in text
    assert "second-msg" not in text
    assert color == tokens.WARNING
