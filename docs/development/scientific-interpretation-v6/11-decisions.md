# 11 — Decisions

1. **Unknown ≠ default**: every unit/CRS/grid/null unknown is a typed
   refusal or explicit null, never a meters/4326/default-grid guess.
2. **One authority per fact**: scalar application (engine loader helper),
   depth-unit classification (well_science), constraint capabilities
   (constraint_capabilities), factor units (factor_units), evaluation
   (interpolation_evaluation). No second authorities were created.
3. **Constraints are recorded, not wished**: the capability matrix is code;
   routing evaluates it before interpolating and the record travels with
   the result. Strict mode exists for agent callers.
4. **Raw semantics + labels over silent conversion**: polygon areas stay in
   CRS-axis units (conservation) with unit labels and ≈m² approximations
   added, instead of redefining the number under existing consumers.
5. **Engine gaps via NaN, not schema surgery**: the native bridge already
   splits runs at non-finite values — submitting NaN values on finite
   depths achieves gap parity without a payload-schema break.
6. **Anisotropy by transform**: geometric anisotropy solved as isotropic
   kriging in the transformed frame (exact, reuses all numerics).
7. **No fake barrier kriging**: unsupported stays unsupported.
8. **100GB seismic explicitly excluded** (program boundary); no
   out-of-core or volume-scale work was touched.
9. **Fixtures declare what construction implies**: tests that build
   synthetic meters-by-construction data attach the unit envelope (the
   refusal paths stay testable with truly-unknown documents).
