# Test suite layout

- `tests/test_*.py`: unit tests. Each module covers one `huginn` module or CLI command, called directly or through the Typer `CliRunner`, without running a test plan end to end.
- `tests/brokers/`: unit tests for the SSH, NETCONF and HTTP brokers and their shared protocol.
- `tests/runner/`: integration tests that stage a project from `tests/fixtures/runner/` into a temporary directory and run it through `huginn run` or `huginn relearn`. A fake runtime broker in `tests/runner/conftest.py` replaces every device connection.
- `tests/runner/hooks/`: integration tests for hook plugins. The hook harness in `tests/runner/hooks/conftest.py` installs test hooks as `huginn.hooks` entry points.
- `tests/fixtures/`: input files. `runner/` holds one directory per staged project, `loaders/` holds testbed and plan files for the loader tests, and `jobs/` and `packages/` hold job files and importable packages for the job loading tests.

Each runner module is named after the behavior its tests check, such as `test_exit_codes.py` or `test_broker_lifecycle.py`. Helpers shared by more than one module live in the nearest `conftest.py`, because the `name-tests-test` pre-commit hook only accepts `test_*.py`, `conftest.py` and `__init__.py` under `tests/`.
