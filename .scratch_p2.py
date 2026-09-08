path = "paleo_workbench/workflow/factor_fusion.py"
src = open(path, encoding="utf-8").read()

old = '''    parents = sorted({ref for ev in result.model.evidences for ref in ev.grid.source_refs})
    provenance = result.provenance()
    # V6 §16 (P1-11): sensitivity was computed but never persisted — leave-
    # one-factor-out is part of the product's honesty record.
    try:
        sensitivity = sensitivity_report(result.model, result)
    except Exception:
        sensitivity = None
    if sensitivity is not None:
        provenance["sensitivity_leave_one_factor_out"] = sensitivity
    with tempfile.TemporaryDirectory() as td:'''
new = '''    parents = sorted({ref for ev in result.model.evidences for ref in ev.grid.source_refs})
    provenance = result.provenance()
    # V6 §16 (P1-11): sensitivity is part of the product's honesty record.
    # V8 M5: compute ONCE here and stash it on qc — the integrated entry
    # reuses the cached copy instead of recomputing (which doubled the
    # (N-1) extra full fusions per registered run).
    sensitivity = result.qc.pop("_cached_sensitivity", None)
    if sensitivity is None:
        try:
            sensitivity = sensitivity_report(result.model, result)
        except Exception:
            sensitivity = None
    if sensitivity is not None:
        provenance["sensitivity_leave_one_factor_out"] = sensitivity
        result.qc["_cached_sensitivity"] = sensitivity
    with tempfile.TemporaryDirectory() as td:'''
assert old in src, "register_output sensitivity block not found"
src = src.replace(old, new)

old2 = '''        except Exception:
            derived_conf = None
    result.likelihood.run_ref = getattr(derived, "run_id", None) or str(
        getattr(derived, "id", "")
    )
    result.qc["catalog_version_id"] = str(derived.id)
    if derived_conf is not None:
        result.qc["confidence_version_id"] = str(derived_conf.id)
    return str(derived.id)'''
new2 = '''        except Exception:
            derived_conf = None
        # V8 M5: the propagated VARIANCE surface registers as a sibling too
        # (it existed only as a runtime descriptor before — downstream QA
        # could not verify the uncertainty claim from the catalog).
        derived_var = None
        if result.variance is not None:
            try:
                variance_path = write_grid_artifact(
                    result.variance, td, "fusion_variance"
                )
                derived_var = catalog_service.create_derived(
                    variance_path,
                    parent_version_ids=[str(derived.id)],
                    name=f"{result.model.name} 融合方差",
                    operation="factor_fusion:variance",
                    parameters={"fusion_version_id": str(derived.id)},
                    generator=FUSION_GENERATOR_VERSION,
                    type="factor_map",
                    format="npz",
                )
            except Exception:
                derived_var = None
    result.likelihood.run_ref = getattr(derived, "run_id", None) or str(
        getattr(derived, "id", "")
    )
    result.qc["catalog_version_id"] = str(derived.id)
    if derived_conf is not None:
        result.qc["confidence_version_id"] = str(derived_conf.id)
    if derived_var is not None:
        result.qc["variance_version_id"] = str(derived_var.id)
    result.qc.pop("_cached_sensitivity", None)
    return str(derived.id)'''
assert old2 in src, "register_output tail not found"
src = src.replace(old2, new2)
open(path, "w", encoding="utf-8").write(src)
print("factor_fusion patched")

# --- integrated_compilation: sensitivity reuse + weight provenance ---------
path = "paleo_workbench/workflow/integrated_compilation.py"
src = open(path, encoding="utf-8").read()

old3 = '''    class_names: Sequence[str] | None = None,
    class_thresholds: Sequence[float] | None = None,
    name: str = DEFAULT_FUSION_MODEL_NAME,
) -> FusionModel:'''
new3 = '''    class_names: Sequence[str] | None = None,
    class_thresholds: Sequence[float] | None = None,
    name: str = DEFAULT_FUSION_MODEL_NAME,
    weight_provenance: Mapping[str, Any] | None = None,
) -> FusionModel:'''
assert old3 in src, "build_fusion_model signature not found"
src = src.replace(old3, new3)

old4 = '''    return FusionModel(
        name=name,
        kind="weighted_evidence",
        evidences=evidences,
        default_class=default_class,
        class_thresholds=class_thresholds_r,
        class_names=class_names_r,
    )'''
new4 = '''    model = FusionModel(
        name=name,
        kind="weighted_evidence",
        evidences=evidences,
        default_class=default_class,
        class_thresholds=class_thresholds_r,
        class_names=class_names_r,
    )
    # V8 M5 weight provenance: WHO chose the weights and WHY travels with
    # the model dict (fingerprinted + catalog run parameters) — "explicit"
    # vs "equal default" alone could not answer who decided.
    if weight_provenance:
        record = {
            str(k): v for k, v in dict(weight_provenance).items() if v is not None
        }
        if record:
            model.model_dict = {**model.to_dict(), "weight_provenance": record}
    return model'''
assert old4 in src, "FusionModel return not found"
src = src.replace(old4, new4)

old5 = "    sensitivity = sensitivity_report(model, result)"
new5 = '''    # V8 M5: reuse the sensitivity cached by registration when present —
    # computing it twice doubled the (N-1) re-fusions per run.
    sensitivity = result.qc.pop("_cached_sensitivity", None)
    if sensitivity is None:
        sensitivity = sensitivity_report(model, result)'''
assert old5 in src, "integrated sensitivity line not found"
src = src.replace(old5, new5)
open(path, "w", encoding="utf-8").write(src)
print("integrated_compilation patched")
