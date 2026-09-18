// providers.schema — validate_parameters subset semantics beyond the frozen
// oracle: NaN/Inf boundaries (not JSON-freezable, exercised natively),
// Python type-name/repr formatting, and error envelope shapes.

#include <cmath>
#include <cstdio>
#include <limits>
#include <string>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/providers/schema.hpp>

using pwb::domain::Json;
namespace pp = pwb::providers;

int g_failures = 0;
int g_checks = 0;

void check(bool ok, const std::string& what) {
    ++g_checks;
    if (!ok) {
        std::fprintf(stderr, "FAIL %s\n", what.c_str());
        ++g_failures;
    }
}

auto validate(const Json& schema, const Json& params, const std::string& label = "parameters") {
    return pp::validate_parameters(schema, params, label);
}

int main() {
    // NaN never violates minimum/maximum (Python float comparisons are all
    // false) — not JSON-freezable, so covered natively.
    Json schema = Json::object();
    schema["type"] = "object";
    Json props = Json::object();
    Json ratio = Json::object();
    ratio["type"] = "number";
    ratio["minimum"] = 0.0;
    ratio["maximum"] = 1.0;
    props["ratio"] = ratio;
    schema["properties"] = props;
    Json params = Json::object();
    params["ratio"] = std::nan("");
    auto problems = validate(schema, params);
    check(problems.empty(), "NaN passes numeric bounds (Python parity)");

    params["ratio"] = std::numeric_limits<double>::infinity();
    problems = validate(schema, params);
    check(problems.size() == 1 &&
              problems[0] == "parameters.ratio: inf > maximum 1.0",
          "Inf violates maximum with Python str formatting: " +
              (problems.empty() ? "<none>" : problems[0]));

    // Python float str parity: 3.0 stays "3.0", not "3".
    params["ratio"] = 1.0;
    problems = validate(schema, params);
    check(problems.empty(), "1.0 within bounds");
    params["ratio"] = 3.0;
    problems = validate(schema, params);
    check(problems.size() == 1 && problems[0] == "parameters.ratio: 3.0 > maximum 1.0",
          "float 3.0 formatting parity: " +
              (problems.empty() ? "<none>" : problems[0]));

    // Integer values never get ".0".
    Json ischema = Json::object();
    ischema["type"] = "object";
    Json iprops = Json::object();
    Json width = Json::object();
    width["type"] = "integer";
    width["minimum"] = 64;
    iprops["width"] = width;
    ischema["properties"] = iprops;
    Json iparams = Json::object();
    iparams["width"] = 10;
    problems = validate(ischema, iparams);
    check(problems.size() == 1 && problems[0] == "parameters.width: 10 < minimum 64",
          "integer minimum message parity");

    // Union with a numeric member: 2.5 matches "number" but not "string".
    Json uschema = Json::object();
    uschema["type"] = "object";
    Json uprops = Json::object();
    Json mixed = Json::object();
    mixed["type"] = Json::array({"string", "number"});
    uprops["v"] = mixed;
    uschema["properties"] = uprops;
    Json uparams = Json::object();
    uparams["v"] = true;
    problems = validate(uschema, uparams);
    check(problems.size() == 1 &&
              problems[0] ==
                  "parameters.v: expected one of ['string', 'number'], got bool",
          "union message with raw list repr: " +
              (problems.empty() ? "<none>" : problems[0]));

    // bool accepted where "boolean" declared; rejected where "integer".
    uparams["v"] = false;
    Json bprops = Json::object();
    Json bfield = Json::object();
    bfield["type"] = "boolean";
    bprops["v"] = bfield;
    uschema["properties"] = bprops;
    problems = validate(uschema, uparams);
    check(problems.empty(), "boolean type accepts false");

    // Deeply nested arrays/objects build composed paths.
    Json deep = Json::object();
    deep["type"] = "array";
    Json item = Json::object();
    item["type"] = "object";
    Json item_props = Json::object();
    Json depth = Json::object();
    depth["type"] = "integer";
    depth["minimum"] = 0;
    item_props["depth"] = depth;
    item["properties"] = item_props;
    item["required"] = Json::array({"depth"});
    deep["items"] = item;
    Json deep_params = Json::array();
    Json ok_elem = Json::object();
    ok_elem["depth"] = 1;
    deep_params.push_back(ok_elem);
    problems = validate(deep, deep_params);
    check(problems.empty(), "deep structure valid");
    Json bad_elem = Json::object();
    bad_elem["dept"] = 1;
    deep_params.clear();
    deep_params.push_back(bad_elem);
    problems = validate(deep, deep_params);
    check(problems.size() == 1 && problems[0] == "parameters[0].depth: required",
          "nested required message");

    // Enum list message includes Unicode members verbatim.
    Json eschema = Json::object();
    eschema["type"] = "object";
    Json eprops = Json::object();
    Json emode = Json::object();
    emode["type"] = "string";
    emode["enum"] = Json::array({"fast", "精细"});
    eprops["mode"] = emode;
    eschema["properties"] = eprops;
    Json eparams = Json::object();
    eparams["mode"] = "slow";
    problems = validate(eschema, eparams);
    check(problems.size() == 1 &&
              problems[0] == "parameters.mode: 'slow' not in enum ['fast', '精细']",
          "enum message parity with Unicode");

    // Negative array bounds never trip (Python numeric comparison parity).
    Json nschema = Json::object();
    nschema["type"] = "object";
    Json nprops = Json::object();
    Json ntags = Json::object();
    ntags["type"] = "array";
    ntags["minItems"] = -1;
    ntags["maxItems"] = -1;
    nprops["tags"] = ntags;
    nschema["properties"] = nprops;
    Json nparams = Json::object();
    nparams["tags"] = Json::array();
    problems = validate(nschema, nparams);
    check(problems.size() == 1 &&
              problems[0] == "parameters.tags: 0 items > maxItems -1",
          "negative maxItems trips, negative minItems does not: " +
              (problems.empty() ? "<none>" : problems[0]));

    // Python type names of JSON values.
    check(pp::json_python_type_name(Json::object()) == "dict", "object → dict");
    check(pp::json_python_type_name(Json::array()) == "list", "array → list");
    check(pp::json_python_type_name(Json("x")) == "str", "string → str");
    check(pp::json_python_type_name(Json(3)) == "int", "int → int");
    check(pp::json_python_type_name(Json(3.5)) == "float", "float → float");
    check(pp::json_python_type_name(Json(true)) == "bool", "bool → bool");
    check(pp::json_python_type_name(Json(nullptr)) == "NoneType", "null → NoneType");

    // python_repr formatting.
    check(pp::python_repr(Json("it's")) == "\"it's\"", "repr prefers double quotes on '");
    check(pp::python_repr(Json(3)) == "3", "repr int");
    check(pp::python_repr(Json(nullptr)) == "None", "repr null");
    Json list = Json::array({"a", "b"});
    check(pp::python_repr(list) == "['a', 'b']", "repr list");

    if (g_failures != 0) {
        std::fprintf(stderr, "providers.schema: %d checks, %d failures\n", g_checks,
                     g_failures);
        return 1;
    }
    std::printf("providers.schema: %d checks passed\n", g_checks);
    return 0;
}
