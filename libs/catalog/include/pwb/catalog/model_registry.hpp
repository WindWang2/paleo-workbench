// Model registry read/write group (conv-31b; service.py 2815-3124 — R7
// recon contract, frozen in 31b-findings). Free functions + the unified
// SaveHook (findings §C-2): the registry projects its dirty set onto the
// hook; a non-ok return triggers the caller-side in-memory snapshot
// rollback inside these functions.
//
// DTOs live in models.hpp (Model / ModelVersion). The gate
// can_promote_to_production is already delivered in policies.hpp
// (facts-struct dependency inversion) — model_gate_facts below is the
// document → facts assembler feeding it. All error messages are
// byte-identical to the Python texts (incl. the Python single-quote
// repr shapes inside gate reasons).
//
// Locking discipline (caller): promote_model / find_production_model
// fact assembly is IO-free and may run fully under the service lock;
// register_model_version's artifact hashing runs OUTSIDE it (Python
// "the lock never spans disk IO").
//
// CONV-31b: implemented in Wave2-A7 (src/model_registry.cpp).
#pragma once

#include "pwb/catalog/apply_changes.hpp"  // SaveHook
#include "pwb/catalog/models.hpp"
#include "pwb/catalog/policies.hpp"
#include "pwb/domain/errors.hpp"

#include <optional>
#include <string>
#include <string_view>
#include <tuple>
#include <vector>

namespace pwb::catalog {

struct RegisterModelRequest {
    std::string model_id;
    std::string model_name;
    std::string model_type = "unknown";
    std::string capability;
    std::string provider;
    std::string status = "demo";
    domain::Json metadata = domain::Json::object();
    domain::Json provenance = domain::Json::object();
    bool force_status = false;  // only true touches status/metadata (C2)
};

// Idempotent register-or-refresh (service.py 2821-2940): existing rows
// refresh under the truthy gates (empty/unknown model_type never
// overwrites; empty capability/provider never blank an existing value),
// status+metadata replace ONLY under force_status (whole-replace, not a
// merge), provenance merges key-wise; a pure no-op does NOT save (no
// revision churn, #1183). New rows append with make_id("model") ids.
// Failure → snapshot rollback, error passthrough. Returns a pointer into
// *document.
domain::Result<Model*> register_model(CatalogDocument& document,
                                      const SaveHook& save,
                                      const RegisterModelRequest& request);

struct RegisterModelVersionRequest {
    std::string model_id;
    std::string model_version = "1";
    std::string artifact_uri;
    // nullopt + readable artifact → sha256 of the file (outside the
    // commit window); unreadable → stays nullopt (silent Python
    // fallback).
    std::optional<std::string> checksum;
    domain::Json input_schema = domain::Json::object();
    domain::Json output_schema = domain::Json::object();
    std::string preprocessing_version;
    std::string runtime;
    bool deterministic = true;
    bool demo_only = false;
    std::string status = "demo";  // "production" refused below
    domain::Json metadata = domain::Json::object();
    domain::Json provenance = domain::Json::object();
};

// service.py 2942-3014: model existence checked before the window,
// status == "production" refused with the byte-identical text, duplicate
// (model_id, model_version) re-checked just before the append (the
// deliberate narrowing of Python's TOCTOU window — findings B-28).
domain::Result<ModelVersion*> register_model_version(
    CatalogDocument& document, const SaveHook& save,
    const RegisterModelVersionRequest& request);

// ---- reads -------------------------------------------------------------------
// Unknown lookups are NotFound with the byte-identical texts
//   "Unknown model: <model_id>"
//   "Unknown model version: <model_id>@<model_version>"   (original arg)
//   "Unknown model version: <version_id>"
domain::Result<const Model*> get_model(const CatalogDocument& document,
                                       std::string_view model_id);
domain::Result<const ModelVersion*> get_model_version(
    const CatalogDocument& document, std::string_view model_id,
    std::string_view model_version);
domain::Result<const ModelVersion*> get_model_version_by_id(
    const CatalogDocument& document, std::string_view model_version_id);

// Document (= rowid) order.
std::vector<const Model*> list_models(const CatalogDocument& document);
// model_id == nullptr → unfiltered (None semantics; "" filters).
// Sorted by created_at (ISO string compare), stable on ties.
std::vector<const ModelVersion*> list_model_versions(
    const CatalogDocument& document, const std::string* model_id);

// service.py promote_model (3043-3088): gate → status/demo_only triple
// flip → ONE save (models + model_versions dirty together = the caller's
// single transaction, repository promote_model_transaction). Failure →
// the three fields are restored.
domain::Result<ModelVersion*> promote_model(CatalogDocument& document,
                                            const SaveHook& save,
                                            std::string_view model_id,
                                            std::string_view model_version);

// service.py find_production_model (3090-3124), no lock: the elimination
// chain — demo_only/non-production skipped; orphan model rows skipped
// (never raise); capability mismatch skipped; the gate RE-CHECKED with
// require_input_schema=false (the read-path exemption is deliberate,
// findings: must not be "fixed"); newest created_at wins, ties keep the
// first in document order. Null when nothing qualifies.
const ModelVersion* find_production_model(const CatalogDocument& document,
                                          std::string_view capability);

// Document → gate-facts assembler (the D1 dependency-inversion seam made
// concrete): {model facts, version facts} on success; on a lookup
// failure the third member carries the byte-identical Unknown message
// (which the gate forwards as (false, msg), Python's str(exc) path).
std::tuple<std::optional<ModelGateFacts>,
           std::optional<ModelVersionGateFacts>,
           std::optional<std::string>>
model_gate_facts(const CatalogDocument& document, std::string_view model_id,
                 std::string_view model_version);

}  // namespace pwb::catalog
