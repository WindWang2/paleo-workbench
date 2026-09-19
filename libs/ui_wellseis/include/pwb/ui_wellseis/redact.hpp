#pragma once

// UI-09 — credential redaction for diagnostics (Qt-free).
//
// Ports well_log_prediction_page.py:
//   _AUTHORIZATION_RE  (authorization: bearer XXX -> bearer <REDACTED>)
//   _SECRET_VALUE_RE   (api_key|token|secret|password =|: value -> key<REDACTED>)
//   _redact_endpoint   (urlsplit -> scheme://host[:port]/path, no query,
//                       no userinfo; unparseable -> "<无效地址>"; no
//                       scheme/host -> secret-scrubbed raw text)
//   _redact_diagnostic_text (both regexes + 3000-char cap)

#include <string>

namespace pwb::ui_wellseis {

// _redact_diagnostic_text parity — auth + secret scrub, capped at 3000
// characters so a failure dump cannot flood the UI log.
std::string redact_diagnostic_text(const std::string& value);

// _redact_endpoint parity — scheme://host[:port]/path only.
std::string redact_endpoint(const std::string& value);

// The two substitutions on their own (test seam + composed use).
std::string redact_authorization(const std::string& value);
std::string redact_secret_values(const std::string& value);

inline constexpr std::size_t kDiagnosticCharCap = 3000;

}  // namespace pwb::ui_wellseis
