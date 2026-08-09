"""Parent `src` package.

Hosts the small HTTP health/status API (``src.api``) and the standalone
entry points (``src.app`` / ``src.config``). This ``__init__.py`` makes
``src`` a regular package so it deterministically wins over the
``geo-viz-engine`` submodule's own ``src`` package on ``sys.path``
(see tests collection / CI).
"""
