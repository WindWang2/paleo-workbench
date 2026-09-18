// Controlled expression evaluator: recursive-descent parser over the same
// restricted grammar as curve_operations.evaluate_curve_expression, with the
// Python visitor's exact fold order and NumPy element-wise semantics.
// Error texts are frozen against the Python module.
#include <algorithm>
#include <cctype>
#include <charconv>
#include <cmath>
#include <limits>
#include <string>
#include <string_view>
#include <vector>

#include <pwb/well_science/curve_expr.hpp>
#include <pwb/well_science/errors.hpp>

namespace pwb::well_science {
namespace {

constexpr double kNan = std::numeric_limits<double>::quiet_NaN();

[[noreturn]] void syntax_error(const std::string& detail) {
    throw CurveOpError("invalid expression: " + detail);
}

// ---------------------------------------------------------------------------
// Tokenizer
// ---------------------------------------------------------------------------

enum class Tok {
    End, Number, Name, String,
    Plus, Minus, Star, Slash, DoubleStar, DoubleSlash, Percent,
    Lt, Gt, Le, Ge, Eq, Ne,
    LParen, RParen, Comma,
    And, Or, Not,
    // Recognized only to produce the visitor's exact "not allowed" messages.
    Dot, LBracket, RBracket, LBrace, RBrace,
    BitAnd, BitOr, BitXor, Shl, Shr, At, Tilde, Bang, Assign, Lambda,
};

struct Token {
    Tok kind;
    double number = 0.0;
    std::string text{};  // Name / String payload
};

class Lexer {
public:
    explicit Lexer(std::string_view src) : src_(src) {}

    std::vector<Token> lex() {
        std::vector<Token> out;
        while (true) {
            Token t = next();
            const bool end = t.kind == Tok::End;
            out.push_back(std::move(t));
            if (end) break;
        }
        return out;
    }

private:
    std::string_view src_;
    std::size_t pos_ = 0;

    Token next() {
        while (pos_ < src_.size() &&
               std::isspace(static_cast<unsigned char>(src_[pos_])))
            ++pos_;
        if (pos_ >= src_.size()) return Token{Tok::End};
        const char c = src_[pos_];
        // string literal → preserved for the frozen "constant ... not allowed"
        if (c == '\'' || c == '"') {
            const char quote = c;
            ++pos_;
            std::string body;
            while (pos_ < src_.size() && src_[pos_] != quote)
                body += src_[pos_++];
            if (pos_ < src_.size()) ++pos_;  // closing quote
            else syntax_error("unterminated string literal");
            return {Tok::String, 0.0, std::move(body)};
        }
        if (std::isdigit(static_cast<unsigned char>(c)) ||
            (c == '.' && pos_ + 1 < src_.size() &&
             std::isdigit(static_cast<unsigned char>(src_[pos_ + 1])))) {
            std::size_t len = 0;
            const double value = std::stod(std::string(src_.substr(pos_)), &len);
            pos_ += len;
            return Token{Tok::Number, value};
        }
        if (std::isalpha(static_cast<unsigned char>(c)) || c == '_') {
            std::size_t e = pos_ + 1;
            while (e < src_.size() &&
                   (std::isalnum(static_cast<unsigned char>(src_[e])) || src_[e] == '_'))
                ++e;
            const std::string word(src_.substr(pos_, e - pos_));
            pos_ = e;
            if (word == "and") return Token{Tok::And};
            if (word == "or") return Token{Tok::Or};
            if (word == "not") return Token{Tok::Not};
            if (word == "lambda") return Token{Tok::Lambda};
            return {Tok::Name, 0.0, word};
        }
        ++pos_;
        const auto mk = [](Tok k) { return Token{k, 0.0, {}}; };
        switch (c) {
            case '+': return mk(Tok::Plus);
            case '-': return mk(Tok::Minus);
            case '*':
                if (peek() == '*') { ++pos_; return mk(Tok::DoubleStar); }
                return mk(Tok::Star);
            case '/':
                if (peek() == '/') { ++pos_; return mk(Tok::DoubleSlash); }
                return mk(Tok::Slash);
            case '%': return mk(Tok::Percent);
            case '<':
                if (peek() == '=') { ++pos_; return mk(Tok::Le); }
                if (peek() == '<') { ++pos_; return mk(Tok::Shl); }
                return mk(Tok::Lt);
            case '>':
                if (peek() == '=') { ++pos_; return mk(Tok::Ge); }
                if (peek() == '>') { ++pos_; return mk(Tok::Shr); }
                return mk(Tok::Gt);
            case '=':
                if (peek() == '=') { ++pos_; return mk(Tok::Eq); }
                return mk(Tok::Assign);
            case '!':
                if (peek() == '=') { ++pos_; return mk(Tok::Ne); }
                return mk(Tok::Bang);
            case '(': return mk(Tok::LParen);
            case ')': return mk(Tok::RParen);
            case ',': return mk(Tok::Comma);
            case '.': return mk(Tok::Dot);
            case '[': return mk(Tok::LBracket);
            case ']': return mk(Tok::RBracket);
            case '{': return mk(Tok::LBrace);
            case '}': return mk(Tok::RBrace);
            case '&': return mk(Tok::BitAnd);
            case '|': return mk(Tok::BitOr);
            case '^': return mk(Tok::BitXor);
            case '~': return mk(Tok::Tilde);
            case '@': return mk(Tok::At);
            default: syntax_error(std::string("unexpected character '") + c + "'");
        }
    }

    char peek() const {
        return pos_ < src_.size() ? src_[pos_] : '\0';
    }
};

// ---------------------------------------------------------------------------
// Values (scalar = 0-d, array = sample-aligned vector)
// ---------------------------------------------------------------------------

struct Value {
    bool is_array = false;
    double scalar = 0.0;
    std::vector<double> arr;
};

std::string shape_text(const Value& v) {
    return v.is_array ? "(" + std::to_string(v.arr.size()) + ",)" : "()";
}

Value scalar(double v) {
    Value out;
    out.scalar = v;
    return out;
}

Value array_value(std::vector<double> v) {
    Value out;
    out.is_array = true;
    out.arr = std::move(v);
    return out;
}

[[noreturn]] void broadcast_error(const Value& a, const Value& b) {
    // numpy text, including the trailing space.
    throw CurveOpError("operands could not be broadcast together with shapes " +
                       shape_text(a) + " " + shape_text(b) + " ");
}

double elem(const Value& v, std::size_t i) { return v.is_array ? v.arr[i] : v.scalar; }

std::size_t broadcast_size(const Value& a, const Value& b) {
    if (a.is_array && b.is_array) {
        if (a.arr.size() != b.arr.size()) broadcast_error(a, b);
        return a.arr.size();
    }
    return a.is_array ? a.arr.size() : b.arr.size();
}

// element-wise kernel over (a, b) with scalar broadcast
template <typename F>
Value zip2(const Value& a, const Value& b, F fn) {
    if (!a.is_array && !b.is_array) return scalar(fn(a.scalar, b.scalar));
    std::vector<double> out(broadcast_size(a, b));
    for (std::size_t i = 0; i < out.size(); ++i) out[i] = fn(elem(a, i), elem(b, i));
    return array_value(std::move(out));
}

double py_mod(double a, double b) {
    const double r = std::fmod(a, b);
    if (r == 0.0 || std::isnan(r)) return r;
    if ((r < 0.0) != (b < 0.0)) return r + b;
    return r;
}

double py_floordiv(double a, double b) { return std::floor(a / b); }

double np_minimum(double a, double b) {
    if (std::isnan(a)) return a;
    if (std::isnan(b)) return b;
    return a < b ? a : b;
}

double np_maximum(double a, double b) {
    if (std::isnan(a)) return a;
    if (std::isnan(b)) return b;
    return a > b ? a : b;
}

// comparison result is 0.0/1.0 (numpy bool → float)
Value compare(Tok op, const Value& a, const Value& b) {
    auto cmp = [op](double x, double y) {
        switch (op) {
            case Tok::Lt: return x < y;
            case Tok::Gt: return x > y;
            case Tok::Le: return x <= y;
            case Tok::Ge: return x >= y;
            case Tok::Eq: return x == y;
            default: return x != y;
        }
    };
    return zip2(a, b, [cmp](double x, double y) { return cmp(x, y) ? 1.0 : 0.0; });
}

Value to_bool_array(const Value& v) {
    // np.asarray(value, dtype=bool): nonzero (NaN is truthy).
    if (!v.is_array) return scalar(v.scalar != 0.0 ? 1.0 : 0.0);
    std::vector<double> out(v.arr.size());
    for (std::size_t i = 0; i < v.arr.size(); ++i)
        out[i] = v.arr[i] != 0.0 ? 1.0 : 0.0;
    return array_value(std::move(out));
}

Value bool_fold(bool is_and, const Value& a, const Value& b) {
    return zip2(a, b, [is_and](double x, double y) {
        return is_and ? (x != 0.0 && y != 0.0 ? 1.0 : 0.0)
                      : (x != 0.0 || y != 0.0 ? 1.0 : 0.0);
    });
}

// element-wise math over one operand
template <typename F>
Value map1(F fn, const Value& v) {
    if (!v.is_array) return scalar(fn(v.scalar));
    std::vector<double> out(v.arr.size());
    for (std::size_t i = 0; i < v.arr.size(); ++i) out[i] = fn(v.arr[i]);
    return array_value(std::move(out));
}

Value unary(Tok op, const Value& v) {
    return map1([op](double x) { return op == Tok::Plus ? x : -x; }, v);
}

Value apply_binary(Tok op, const Value& a, const Value& b) {
    return zip2(a, b, [op](double x, double y) {
        switch (op) {
            case Tok::Plus: return x + y;
            case Tok::Minus: return x - y;
            case Tok::Star: return x * y;
            case Tok::Slash: return x / y;
            case Tok::DoubleStar: return std::pow(x, y);
            case Tok::DoubleSlash: return py_floordiv(x, y);
            case Tok::Percent: return py_mod(x, y);
            default: return kNan;  // unreachable: parser only passes binary ops
        }
    });
}

// np.minimum/maximum with numpy's positional-out binding for the third arg.
Value minmax_call(bool is_min, std::vector<Value> args) {
    if (args.size() == 2)
        return zip2(args[0], args[1], is_min ? np_minimum : np_maximum);
    if (args.size() == 3) {
        const Value result = zip2(args[0], args[1], is_min ? np_minimum : np_maximum);
        const Value& out = args[2];
        const bool compatible = !result.is_array
                                    ? true
                                    : (out.is_array && out.arr.size() == result.arr.size());
        if (!compatible)
            throw CurveOpError(
                "non-broadcastable output operand with shape " + shape_text(out) +
                " doesn't match the broadcast shape " + shape_text(result));
        if (!out.is_array) return result;
        if (!result.is_array) {
            return array_value(std::vector<double>(out.arr.size(), result.scalar));
        }
        return result;
    }
    throw CurveOpError("function '" + std::string(is_min ? "min" : "max") +
                       "' takes exactly 2 positional arguments");
}

Value call_function(const std::string& name, std::vector<Value> args) {
    const auto need = [&](std::size_t n) {
        if (args.size() != n)
            throw CurveOpError("function '" + name + "' takes exactly " +
                               std::to_string(n) + " positional argument(s)");
    };
    if (name == "abs") {
        need(1);
        return map1([](double v) { return std::fabs(v); }, args[0]);
    }
    if (name == "min") return minmax_call(true, std::move(args));
    if (name == "max") return minmax_call(false, std::move(args));
    if (name == "log") {
        need(1);
        return map1([](double v) { return std::log(v); }, args[0]);
    }
    if (name == "log10") {
        need(1);
        return map1([](double v) { return std::log10(v); }, args[0]);
    }
    if (name == "log2") {
        need(1);
        return map1([](double v) { return std::log2(v); }, args[0]);
    }
    if (name == "exp") {
        need(1);
        return map1([](double v) { return std::exp(v); }, args[0]);
    }
    if (name == "sqrt") {
        need(1);
        return map1([](double v) { return std::sqrt(v); }, args[0]);
    }
    if (name == "sin") {
        need(1);
        return map1([](double v) { return std::sin(v); }, args[0]);
    }
    if (name == "cos") {
        need(1);
        return map1([](double v) { return std::cos(v); }, args[0]);
    }
    if (name == "tan") {
        need(1);
        return map1([](double v) { return std::tan(v); }, args[0]);
    }
    if (name == "where") {
        need(3);
        const Value cond = to_bool_array(args[0]);
        const Value& a = args[1];
        const Value& b = args[2];
        if (!cond.is_array) {
            const double chosen = cond.scalar != 0.0 ? elem(a, 0) : elem(b, 0);
            if (!a.is_array && !b.is_array) return scalar(chosen);
            return array_value(std::vector<double>(broadcast_size(a, b), chosen));
        }
        std::vector<double> res(cond.arr.size());
        for (std::size_t i = 0; i < res.size(); ++i)
            res[i] = cond.arr[i] != 0.0 ? elem(a, i) : elem(b, i);
        return array_value(std::move(res));
    }
    if (name == "clip") {
        // np.clip requires both bounds in numpy 2.x (a_max is positional-
        // required): clip(x, lo) is a TypeError in the frozen environment.
        if (args.size() != 3)
            throw CurveOpError("function 'clip' takes exactly 3 positional arguments");
        // np.clip(a, a_min, a_max) == minimum(maximum(a, a_min), a_max);
        // NaN bounds/inputs propagate (frozen case: clip(HOLE, 2, 3) NaN→NaN).
        auto one = [&](double x, std::size_t i) {
            return np_minimum(np_maximum(x, elem(args[1], i)), elem(args[2], i));
        };
        const bool any_array = args[0].is_array || args[1].is_array || args[2].is_array;
        if (!any_array) return scalar(one(args[0].scalar, 0));
        std::size_t n = 0;
        for (const Value& a : args)
            if (a.is_array) n = n == 0 ? a.arr.size() : std::min(n, a.arr.size());
        for (const Value& a : args)
            if (a.is_array && a.arr.size() != n) broadcast_error(args[0], a);
        std::vector<double> res(n);
        for (std::size_t i = 0; i < n; ++i) res[i] = one(elem(args[0], i), i);
        return array_value(std::move(res));
    }
    // Unreachable for whitelisted names; the parser pre-checks and freezes text.
    throw CurveOpError("function '" + name + "' not allowed");
}

// ---------------------------------------------------------------------------
// Parser (visitor-equivalent fold)
// ---------------------------------------------------------------------------

class Parser {
public:
    Parser(const std::vector<Token>& toks, const std::vector<CurveVariable>& vars)
        : toks_(toks), vars_(vars) {}

    Value parse() {
        Value v = parse_or();
        if (peek().kind != Tok::End) syntax_error("unexpected token after expression");
        return v;
    }

private:
    const std::vector<Token>& toks_;
    const std::vector<CurveVariable>& vars_;
    std::size_t pos_ = 0;

    const Token& peek() const { return toks_[pos_]; }
    const Token& advance() { return toks_[pos_++]; }
    bool accept(Tok k) {
        if (peek().kind == k) { ++pos_; return true; }
        return false;
    }

    Value parse_or() {
        Value left = parse_and();
        while (peek().kind == Tok::Or) {
            advance();
            const Value right = parse_and();
            left = bool_fold(false, left, right);
        }
        return left;
    }

    Value parse_and() {
        Value left = parse_comparison();
        while (peek().kind == Tok::And) {
            advance();
            const Value right = parse_comparison();
            left = bool_fold(true, left, right);
        }
        return left;
    }

    Value parse_comparison() {
        // The Python visitor FOLDS: `left = left OP right` successively — the
        // next comparison sees the 0/1 result of the previous one (frozen).
        Value left = parse_additive();
        while (true) {
            const Tok k = peek().kind;
            if (k != Tok::Lt && k != Tok::Gt && k != Tok::Le && k != Tok::Ge &&
                k != Tok::Eq && k != Tok::Ne)
                break;
            advance();
            const Value right = parse_additive();
            left = compare(k, left, right);
        }
        return left;
    }

    Value parse_additive() {
        Value left = parse_multiplicative();
        while (peek().kind == Tok::Plus || peek().kind == Tok::Minus) {
            const Tok k = advance().kind;
            const Value right = parse_multiplicative();
            left = apply_binary(k, left, right);
        }
        return left;
    }

    Value parse_multiplicative() {
        Value left = parse_unary();
        while (peek().kind == Tok::Star || peek().kind == Tok::Slash ||
               peek().kind == Tok::DoubleSlash || peek().kind == Tok::Percent) {
            const Tok k = advance().kind;
            const Value right = parse_unary();
            left = apply_binary(k, left, right);
        }
        return left;
    }

    Value parse_unary() {
        if (peek().kind == Tok::Plus || peek().kind == Tok::Minus) {
            const Tok k = advance().kind;
            return unary(k, parse_unary());
        }
        if (peek().kind == Tok::Not || peek().kind == Tok::Tilde ||
            peek().kind == Tok::Bang)
            throw CurveOpError("expression element UnaryOp is not allowed");
        return parse_power();
    }

    Value parse_power() {
        Value base = parse_primary();
        if (peek().kind == Tok::DoubleStar) {
            advance();
            const Value exponent = parse_unary();  // right-assoc, unary allowed
            return apply_binary(Tok::DoubleStar, base, exponent);
        }
        // trailing postfix that the whitelist refuses — exact node names
        if (peek().kind == Tok::Dot)
            throw CurveOpError("expression element Attribute is not allowed");
        if (peek().kind == Tok::LBracket)
            throw CurveOpError("expression element Subscript is not allowed");
        if (peek().kind == Tok::At || peek().kind == Tok::Shl ||
            peek().kind == Tok::Shr || peek().kind == Tok::BitAnd ||
            peek().kind == Tok::BitOr || peek().kind == Tok::BitXor)
            throw CurveOpError("expression element BinOp is not allowed");
        return base;
    }

    Value parse_primary() {
        const Token& t = peek();
        switch (t.kind) {
            case Tok::Number: {
                advance();
                return scalar(t.number);
            }
            case Tok::String:
                throw CurveOpError("constant '" + t.text + "' not allowed (numbers only)");
            case Tok::Name: {
                if (t.text == "True" || t.text == "False")
                    throw CurveOpError("constant " + t.text + " not allowed (numbers only)");
                if (t.text == "None")
                    throw CurveOpError("constant None not allowed (numbers only)");
                advance();
                if (peek().kind == Tok::LParen) return parse_call(t.text);
                return lookup(t.text);
            }
            case Tok::LParen: {
                advance();
                if (peek().kind == Tok::RParen) syntax_error("empty parentheses");
                Value inner = parse_or();
                if (peek().kind == Tok::Comma)
                    throw CurveOpError("expression element Tuple is not allowed");
                if (!accept(Tok::RParen)) syntax_error("closing parenthesis is missing");
                return inner;
            }
            case Tok::LBracket:
                throw CurveOpError("expression element List is not allowed");
            case Tok::LBrace:
                throw CurveOpError("expression element Dict is not allowed");
            case Tok::Lambda:
                throw CurveOpError("expression element Lambda is not allowed");
            case Tok::End:
                syntax_error("unexpected end of expression");
            default:
                syntax_error("unexpected token");
        }
    }

    Value parse_call(const std::string& name) {
        advance();  // '('
        static const char* kAllowed =
            "['abs', 'clip', 'cos', 'exp', 'log', 'log10', 'log2', 'max', 'min', "
            "'sin', 'sqrt', 'tan', 'where']";
        const bool whitelisted = name == "abs" || name == "clip" || name == "cos" ||
                                 name == "exp" || name == "log" || name == "log10" ||
                                 name == "log2" || name == "max" || name == "min" ||
                                 name == "sin" || name == "sqrt" || name == "tan" ||
                                 name == "where";
        if (!whitelisted)
            throw CurveOpError("function '" + name +
                               "' not allowed; supported: " + kAllowed);
        // The Python visitor checks node.keywords BEFORE visiting any
        // argument: `clip(NOPE, a_min=0)` refuses on keywords, not the name.
        // The scan must skip nested calls (paren depth), so
        // `clip(GR, abs(RT), a_max=1)` still refuses on keywords.
        int depth = 0;
        for (std::size_t i = pos_; i + 1 < toks_.size(); ++i) {
            if (toks_[i].kind == Tok::LParen) {
                ++depth;
            } else if (toks_[i].kind == Tok::RParen) {
                if (depth == 0) break;
                --depth;
                continue;
            }
            if (toks_[i].kind == Tok::Assign ||
                (toks_[i].kind == Tok::Name && toks_[i + 1].kind == Tok::Assign))
                throw CurveOpError("keyword arguments are not allowed");
        }
        std::vector<Value> args;
        if (peek().kind == Tok::RParen) {
            advance();
            return call_function(name, std::move(args));
        }
        while (true) {
            args.push_back(parse_or());
            if (accept(Tok::Comma)) continue;
            if (accept(Tok::RParen)) break;
            syntax_error("expected ',' or ')' in argument list");
        }
        return call_function(name, std::move(args));
    }

    Value lookup(const std::string& name) {
        for (const auto& v : vars_)
            if (v.name == name) {
                Value out;
                out.is_array = true;
                out.arr = v.values;
                return out;
            }
        std::vector<std::string> names;
        for (const auto& v : vars_) names.push_back(v.name);
        std::sort(names.begin(), names.end());
        std::string joined = "[";
        for (std::size_t i = 0; i < names.size(); ++i)
            joined += (i ? ", '" : "'") + names[i] + "'";
        joined += "]";
        throw CurveOpError("unknown curve name '" + name + "'; available: " + joined);
    }
};

}  // namespace

std::vector<double> evaluate_curve_expression(
    const std::string& expr, const std::vector<CurveVariable>& variables) {
    if (expr.empty() || std::all_of(expr.begin(), expr.end(), [](unsigned char ch) {
            return std::isspace(ch) != 0;
        }))
        throw CurveOpError("empty expression");
    if (variables.empty())
        throw CurveOpError("expression needs at least one curve variable");

    const auto tokens = Lexer(expr).lex();
    Value result = Parser(tokens, variables).parse();

    const std::size_t reference = variables.front().values.size();
    if (!result.is_array) {
        return std::vector<double>(reference, result.scalar);
    }
    if (result.arr.size() != reference)
        throw CurveOpError("expression did not produce a sample-aligned result");
    return result.arr;
}

}  // namespace pwb::well_science
