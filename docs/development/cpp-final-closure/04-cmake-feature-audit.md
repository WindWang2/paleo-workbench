# CMake Feature Audit

The root feature comparison now reports no unclassified root option:

```text
root options missing feature/report: []
```

The declarative graph now includes the previously missing 18 root switches.
`PWB_BUILD_NATIVE_PRODUCT` is declared inside `PwbFeatures.cmake`, so its
implications resolve before any `add_subdirectory()` consumes them.

The native-product configure reaches Qt discovery with all product
implications resolved. During this audit it also exposed and fixed an
order-dependent duplicate target defect between CONV-28 and
`libs/science_suite`.

Verified configuration:

```text
platform OFF, data ON, tests OFF, tools OFF
configure PASS
pwb_data + pwb_job_runtime build PASS (76 build steps)

platform OFF, data ON, tests ON, tools OFF
configure PASS
data.* + job_runtime.* CTest PASS (28/28)
```

Unavailable configuration:

```text
PWB_BUILD_NATIVE_PRODUCT=ON, BUILD_TESTING=OFF
feature fixpoint PASS
configure stops at required Qt 6.8 discovery
```

The final gate carries the full product, integration-test, packaging, and
runtime sequence under the shared resource lock with two build/test jobs.
