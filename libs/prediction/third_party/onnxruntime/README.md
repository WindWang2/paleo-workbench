# Vendored ONNX Runtime C API header

`onnxruntime_c_api.h` is a verbatim copy of the ONNX Runtime C API header at
upstream tag **v1.17.0** (`ORT_API_VERSION 17`), MIT licensed (see
`LICENSE`). Upstream source:

    https://github.com/microsoft/onnxruntime/blob/v1.17.0/include/onnxruntime/core/session/onnxruntime_c_api.h

SHA-256 of the vendored header:

    7e47eb78563da119f740dc0ddfda96800e779e0bcbd169a9a49e9c10746c4cd5

## Why a vendored header and not `find_package(onnxruntime)`

The prediction runtime must build **without** an ONNX Runtime SDK installed
(ORT is an optional runtime dependency; absence is a normal state, not a
configure error). The session adapter therefore loads the runtime library at
process start (`LoadLibraryW` / `dlopen`) and only needs the ABI types at
compile time.

## Version policy

ONNX Runtime guarantees ABI stability for `OrtApi` field order (new
functions are appended; existing fields never change meaning), and
`OrtApiBase::GetApi(version)` returns a usable struct for any version
`<=` the running library's `ORT_API_VERSION`. The header exposes exactly
version 17, so it works against any runtime `>= 1.17` including the current
1.29 line (verified locally against `onnxruntime.dll` 1.29.0).

Do **not** edit the header. Bump it by copying the file from a newer
upstream tag and updating this README (tag + SHA-256).
