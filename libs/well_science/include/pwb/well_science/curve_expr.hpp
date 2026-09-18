// Controlled derived-curve expression evaluator (AST whitelist, no eval).
// Port of curve_operations.evaluate_curve_expression: restricted grammar over
// named curve arrays with NumPy element-wise semantics. Operator precedence
// and the comparison/boolean fold replicate the Python visitor exactly (see
// ledgers/11-decisions.md D6).
#pragma once

#include <string>
#include <vector>

namespace pwb::well_science {

// One named curve (dict insertion order matters: the FIRST variable defines
// the reference shape and the "available" list is reported sorted).
struct CurveVariable {
    std::string name;
    std::vector<double> values;
};

// Grammar: numbers, curve names, unary +/-, binary + - * / ** % //, chained
// comparisons (> < >= <= == !=), `and`/`or`, and positional calls to
// abs min max log log10 log2 exp sqrt sin cos tan where clip. Anything else —
// attribute access, subscripts, lambdas, keywords, non-listed names — raises
// CurveOpError rather than being evaluated. Scalars broadcast to the first
// variable's shape; a non-scalar result of any other length raises.
std::vector<double> evaluate_curve_expression(
    const std::string& expr, const std::vector<CurveVariable>& variables);

}  // namespace pwb::well_science
