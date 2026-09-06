# 13 — Known Limitations & Accepted Assumptions

## Accepted assumptions (explicit)
- SEG-Y scalar == 0 treated as "coordinates already in metres" (rev2 leaves
  it undefined; common writer convention, now documented at the helper).
- Local-scale ≈m² areas under geographic CRS (mean-latitude scale factor)
  are APPROXIMATIONS labelled as such; exact areas need a projected CRS.
- LAS preview loader's ResForm-compatible inferred-null whitelist
  (−999.25 default) stands per the domain contract; the DERIVED pipeline
  records its null policy explicitly.
- Kriging remains an exact interpolator at sample locations even with a
  nugget (standard γ-form OK system).

## Known limitations (not fixed this round)
- kriging barriers: unsupported (no defensible barrier covariance method
  implemented; no fake penalty was added).
- plain-IDW duplicate samples double-vote (documented; only constrained
  IDW and kriging collapse/report duplicates).
- the numpy-fallback kriging fitter still differs from the engine WLS fit
  (fallback is flagged \`kriging_fallback\`; unification deferred).
- engine multi-well section composites mixed m/ft wells without cross-well
  conversion (documented; unit envelopes now make it visible).
- 12 of the 17 §19 action families remain unwrapped (services exist;
  honesty contracts specified in 10).
- verifier coverage: grid/map payload auto-verification only; scientific
  WRITE actions beyond map.* remain without dedicated verifiers.
- 100GB seismic explicitly out of scope (program boundary).
