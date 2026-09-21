# Runtime and Lifetime Review

Reviewed source ownership and shutdown paths:

- `AppContext` exclusively owns `ProjectSession`, the seismic
  `AlgorithmRunner`, and the provider service;
- the project store is a shared project-lifetime handle and is reset on
  shutdown;
- `ProjectSession::close()` runs while the canvas host is alive;
- shutdown is idempotent;
- provider and algorithm services outlive UI consumers;
- job delivery uses the existing Qt queued bridge and bounded scheduler;
- late completion and cancellation continue through generation/cancellation
  guards in the existing native services;
- editing remains on real `QgsVectorLayer` edit buffers;
- catalog storage retains its existing SQLite transaction/repository
  ownership.

No new raw callback ownership or cross-thread QObject ownership was added.
The closure deliberately did not bind workflow/agent services whose production
lifetime and project-switch ownership are not yet defined.

Runtime execution under Qt/QGIS is still required before final acceptance.
