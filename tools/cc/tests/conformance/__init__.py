"""The `cc conformance` harness's pytest test face (`tests/conformance/`).

A real package (mirrors `tests/integration/`'s own `__init__.py`) so
`conftest.py`'s `FleetFactory` and friends can be imported explicitly
(`from tests.conformance.conftest import FleetFactory`) as well as used
through ordinary pytest fixture injection.
"""
