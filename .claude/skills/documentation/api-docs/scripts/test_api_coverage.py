"""
Tests for api_coverage.py — bundled alongside the linter.

Run with:
  python3 -m pytest .claude/skills/documentation/api-docs/scripts/test_api_coverage.py -v
"""

import importlib.util
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Module import
# ---------------------------------------------------------------------------
SCRIPT = Path(__file__).parent / "api_coverage.py"

spec = importlib.util.spec_from_file_location("api_coverage", SCRIPT)
api_coverage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(api_coverage)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def run_script(args=(), stdin_text=None):
    """Run api_coverage.py as a subprocess; return (returncode, stdout, stderr)."""
    cmd = [sys.executable, str(SCRIPT)] + list(args)
    result = subprocess.run(cmd, input=stdin_text, capture_output=True, text=True)
    return result.returncode, result.stdout, result.stderr


def minimal_oas3(paths=None, info=None, security=None):
    """Build a minimal valid OAS3 spec for testing."""
    spec = {
        "openapi": "3.0.0",
        "info": info or {"title": "Test API", "version": "1.0.0"},
        "paths": paths or {},
    }
    if security is not None:
        spec["security"] = security
    return spec


def minimal_get_op(**overrides):
    """Build a minimal GET operation."""
    op = {
        "summary": "Get a resource",
        "description": "Returns a resource by ID.",
        "operationId": "getResource",
        "responses": {
            "200": {"description": "OK"},
            "400": {"description": "Bad request"},
        },
    }
    op.update(overrides)
    return op


def parse_json_block(stdout: str) -> dict:
    """Extract the first JSON block from script stdout."""
    return json.loads(stdout.split("\n\n")[0])


# ---------------------------------------------------------------------------
# detect_spec_version
# ---------------------------------------------------------------------------


class TestDetectSpecVersion:
    def test_oas3(self):
        assert api_coverage.detect_spec_version({"openapi": "3.0.0"}) == "oas3"

    def test_oas3_minor(self):
        assert api_coverage.detect_spec_version({"openapi": "3.1.0"}) == "oas3"

    def test_swagger2(self):
        assert api_coverage.detect_spec_version({"swagger": "2.0"}) == "swagger2"

    def test_unknown(self):
        assert api_coverage.detect_spec_version({"title": "nope"}) == "unknown"


# ---------------------------------------------------------------------------
# assign_band equivalents — rule triggering
# ---------------------------------------------------------------------------


class TestRuleR01MissingSummary:
    def test_missing_summary_flagged(self):
        op = minimal_get_op()
        del op["summary"]
        paths = {"/items": {"get": op}}
        spec = minimal_oas3(paths=paths)
        findings = api_coverage.run_checks(spec)
        rules = [f["rule"] for f in findings]
        assert "R01" in rules

    def test_present_summary_not_flagged(self):
        paths = {"/items": {"get": minimal_get_op()}}
        spec = minimal_oas3(paths=paths)
        findings = api_coverage.run_checks(spec)
        assert not any(f["rule"] == "R01" for f in findings)

    def test_empty_summary_flagged(self):
        op = minimal_get_op(summary="   ")
        paths = {"/items": {"get": op}}
        spec = minimal_oas3(paths=paths)
        findings = api_coverage.run_checks(spec)
        assert any(f["rule"] == "R01" for f in findings)


class TestRuleR02MissingDescription:
    def test_missing_description_flagged(self):
        op = minimal_get_op()
        del op["description"]
        paths = {"/items": {"get": op}}
        spec = minimal_oas3(paths=paths)
        findings = api_coverage.run_checks(spec)
        assert any(f["rule"] == "R02" for f in findings)

    def test_present_description_not_flagged(self):
        paths = {"/items": {"get": minimal_get_op()}}
        spec = minimal_oas3(paths=paths)
        findings = api_coverage.run_checks(spec)
        assert not any(f["rule"] == "R02" for f in findings)


class TestRuleR03R04Parameters:
    def test_path_param_missing_desc_is_r03(self):
        op = minimal_get_op(parameters=[{"name": "id", "in": "path", "required": True}])
        paths = {"/items/{id}": {"get": op}}
        spec = minimal_oas3(paths=paths)
        findings = api_coverage.run_checks(spec)
        r03_findings = [f for f in findings if f["rule"] == "R03"]
        assert len(r03_findings) == 1
        assert "id" in r03_findings[0]["location"]

    def test_query_param_missing_desc_is_r04(self):
        op = minimal_get_op(parameters=[{"name": "limit", "in": "query"}])
        paths = {"/items": {"get": op}}
        spec = minimal_oas3(paths=paths)
        findings = api_coverage.run_checks(spec)
        assert any(f["rule"] == "R04" for f in findings)

    def test_param_with_description_not_flagged(self):
        op = minimal_get_op(
            parameters=[
                {
                    "name": "id",
                    "in": "path",
                    "required": True,
                    "description": "Resource ID",
                }
            ]
        )
        paths = {"/items/{id}": {"get": op}}
        spec = minimal_oas3(paths=paths)
        findings = api_coverage.run_checks(spec)
        assert not any(f["rule"] in ("R03", "R04") for f in findings)

    def test_r03_severity_is_medium(self):
        op = minimal_get_op(parameters=[{"name": "id", "in": "path", "required": True}])
        paths = {"/items/{id}": {"get": op}}
        spec = minimal_oas3(paths=paths)
        findings = api_coverage.run_checks(spec)
        r03 = next(f for f in findings if f["rule"] == "R03")
        assert r03["severity"] == "MEDIUM"

    def test_r04_severity_is_low(self):
        op = minimal_get_op(parameters=[{"name": "q", "in": "query"}])
        paths = {"/search": {"get": op}}
        spec = minimal_oas3(paths=paths)
        findings = api_coverage.run_checks(spec)
        r04 = next(f for f in findings if f["rule"] == "R04")
        assert r04["severity"] == "LOW"


class TestRuleR05R06RequestBody:
    def test_missing_req_body_desc_flagged(self):
        op = minimal_get_op(
            requestBody={
                "content": {"application/json": {"schema": {"type": "object"}}}
            }
        )
        paths = {"/items": {"post": op}}
        spec = minimal_oas3(paths=paths)
        findings = api_coverage.run_checks(spec)
        assert any(f["rule"] == "R05" for f in findings)

    def test_req_body_missing_example_r06(self):
        op = minimal_get_op(
            requestBody={
                "description": "New item",
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {"name": {"type": "string"}},
                        }
                    }
                },
            }
        )
        paths = {"/items": {"post": op}}
        spec = minimal_oas3(paths=paths)
        findings = api_coverage.run_checks(spec)
        assert any(f["rule"] == "R06" for f in findings)

    def test_req_body_with_example_not_flagged_r06(self):
        op = minimal_get_op(
            requestBody={
                "description": "New item",
                "content": {
                    "application/json": {
                        "schema": {"type": "object"},
                        "example": {"name": "test"},
                    }
                },
            }
        )
        paths = {"/items": {"post": op}}
        spec = minimal_oas3(paths=paths)
        findings = api_coverage.run_checks(spec)
        assert not any(f["rule"] == "R06" for f in findings)


class TestRuleR07R08Responses:
    def test_response_missing_desc_r07(self):
        op = minimal_get_op(
            responses={"200": {}, "400": {"description": "Bad Request"}}
        )
        paths = {"/items": {"get": op}}
        spec = minimal_oas3(paths=paths)
        findings = api_coverage.run_checks(spec)
        assert any(f["rule"] == "R07" for f in findings)

    def test_response_with_schema_no_example_r08(self):
        op = minimal_get_op(
            responses={
                "200": {
                    "description": "OK",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {"id": {"type": "string"}},
                            }
                        }
                    },
                },
                "400": {"description": "Bad Request"},
            }
        )
        paths = {"/items": {"get": op}}
        spec = minimal_oas3(paths=paths)
        findings = api_coverage.run_checks(spec)
        assert any(f["rule"] == "R08" for f in findings)

    def test_response_with_schema_and_example_not_r08(self):
        op = minimal_get_op(
            responses={
                "200": {
                    "description": "OK",
                    "content": {
                        "application/json": {
                            "schema": {"type": "object"},
                            "example": {"id": "abc"},
                        }
                    },
                },
                "400": {"description": "Bad Request"},
            }
        )
        paths = {"/items": {"get": op}}
        spec = minimal_oas3(paths=paths)
        findings = api_coverage.run_checks(spec)
        assert not any(f["rule"] == "R08" for f in findings)


class TestRuleR09Missing4xx:
    def test_no_4xx_flagged_high(self):
        op = minimal_get_op(responses={"200": {"description": "OK"}})
        paths = {"/items": {"get": op}}
        spec = minimal_oas3(paths=paths)
        findings = api_coverage.run_checks(spec)
        r09 = [f for f in findings if f["rule"] == "R09"]
        assert len(r09) == 1
        assert r09[0]["severity"] == "HIGH"

    def test_has_400_not_flagged(self):
        paths = {"/items": {"get": minimal_get_op()}}  # minimal_get_op has 400
        spec = minimal_oas3(paths=paths)
        findings = api_coverage.run_checks(spec)
        assert not any(f["rule"] == "R09" for f in findings)

    def test_has_404_not_flagged(self):
        op = minimal_get_op(
            responses={
                "200": {"description": "OK"},
                "404": {"description": "Not found"},
            }
        )
        paths = {"/items/{id}": {"get": op}}
        spec = minimal_oas3(paths=paths)
        findings = api_coverage.run_checks(spec)
        assert not any(f["rule"] == "R09" for f in findings)


class TestRuleR10SecuredMissingAuthErrors:
    def test_secured_op_no_401_403_flagged(self):
        op = minimal_get_op(
            security=[{"bearerAuth": []}],
            responses={"200": {"description": "OK"}, "400": {"description": "Bad"}},
        )
        paths = {"/secure": {"get": op}}
        spec = minimal_oas3(paths=paths)
        findings = api_coverage.run_checks(spec)
        r10 = [f for f in findings if f["rule"] == "R10"]
        assert len(r10) == 1
        assert r10[0]["severity"] == "HIGH"

    def test_secured_op_with_401_not_flagged(self):
        op = minimal_get_op(
            security=[{"bearerAuth": []}],
            responses={
                "200": {"description": "OK"},
                "401": {"description": "Unauthorized"},
                "400": {"description": "Bad"},
            },
        )
        paths = {"/secure": {"get": op}}
        spec = minimal_oas3(paths=paths)
        findings = api_coverage.run_checks(spec)
        assert not any(f["rule"] == "R10" for f in findings)

    def test_unsecured_op_no_r10(self):
        op = minimal_get_op(
            security=[],  # explicitly no security
            responses={"200": {"description": "OK"}, "400": {"description": "Bad"}},
        )
        paths = {"/public": {"get": op}}
        spec = minimal_oas3(paths=paths)
        findings = api_coverage.run_checks(spec)
        assert not any(f["rule"] == "R10" for f in findings)


class TestRuleR12OperationIdCasing:
    def test_snake_case_flagged(self):
        op = minimal_get_op(operationId="get_resource")
        paths = {"/items": {"get": op}}
        spec = minimal_oas3(paths=paths)
        findings = api_coverage.run_checks(spec)
        assert any(f["rule"] == "R12" for f in findings)

    def test_kebab_case_flagged(self):
        op = minimal_get_op(operationId="get-resource")
        paths = {"/items": {"get": op}}
        spec = minimal_oas3(paths=paths)
        findings = api_coverage.run_checks(spec)
        assert any(f["rule"] == "R12" for f in findings)

    def test_pascal_case_flagged(self):
        op = minimal_get_op(operationId="GetResource")
        paths = {"/items": {"get": op}}
        spec = minimal_oas3(paths=paths)
        findings = api_coverage.run_checks(spec)
        assert any(f["rule"] == "R12" for f in findings)

    def test_camel_case_not_flagged(self):
        op = minimal_get_op(operationId="getResource")
        paths = {"/items": {"get": op}}
        spec = minimal_oas3(paths=paths)
        findings = api_coverage.run_checks(spec)
        assert not any(f["rule"] == "R12" for f in findings)

    def test_camel_with_numbers_not_flagged(self):
        op = minimal_get_op(operationId="getResource2")
        paths = {"/items": {"get": op}}
        spec = minimal_oas3(paths=paths)
        findings = api_coverage.run_checks(spec)
        assert not any(f["rule"] == "R12" for f in findings)

    def test_r12_severity_is_low(self):
        op = minimal_get_op(operationId="get_resource")
        paths = {"/items": {"get": op}}
        spec = minimal_oas3(paths=paths)
        findings = api_coverage.run_checks(spec)
        r12 = next(f for f in findings if f["rule"] == "R12")
        assert r12["severity"] == "LOW"


class TestRuleR13InfoBlock:
    def test_missing_contact_flagged(self):
        info = {"title": "Test", "version": "1.0"}
        spec = minimal_oas3(info=info)
        findings = api_coverage.run_checks(spec)
        r13_messages = [f["message"] for f in findings if f["rule"] == "R13"]
        assert any("contact" in m for m in r13_messages)

    def test_missing_license_flagged(self):
        info = {"title": "Test", "version": "1.0"}
        spec = minimal_oas3(info=info)
        findings = api_coverage.run_checks(spec)
        r13_messages = [f["message"] for f in findings if f["rule"] == "R13"]
        assert any("license" in m for m in r13_messages)

    def test_full_info_not_flagged(self):
        info = {
            "title": "Test",
            "version": "1.0",
            "contact": {"email": "api@example.com"},
            "license": {"name": "MIT"},
        }
        spec = minimal_oas3(info=info)
        findings = api_coverage.run_checks(spec)
        assert not any(f["rule"] == "R13" for f in findings)


# ---------------------------------------------------------------------------
# rank_findings — sort order
# ---------------------------------------------------------------------------


class TestRankFindings:
    def test_high_before_medium_before_low(self):
        raw = [
            {"rule": "R02", "severity": "LOW", "location": "GET /a", "message": "low"},
            {
                "rule": "R09",
                "severity": "HIGH",
                "location": "GET /b",
                "message": "high",
            },
            {
                "rule": "R01",
                "severity": "MEDIUM",
                "location": "GET /c",
                "message": "medium",
            },
        ]
        ranked = api_coverage.rank_findings(raw)
        severities = [f["severity"] for f in ranked]
        assert severities == ["HIGH", "MEDIUM", "LOW"]


# ---------------------------------------------------------------------------
# load_input — stdin vs file path
# ---------------------------------------------------------------------------


class TestLoadInput:
    def test_stdin_hyphen(self, monkeypatch):
        data = minimal_oas3()
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(data)))
        result = api_coverage.load_input("-")
        assert result["openapi"] == "3.0.0"

    def test_stdin_none(self, monkeypatch):
        data = minimal_oas3()
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(data)))
        result = api_coverage.load_input(None)
        assert result["openapi"] == "3.0.0"

    def test_file_path(self, tmp_path):
        data = minimal_oas3()
        p = tmp_path / "spec.json"
        p.write_text(json.dumps(data))
        result = api_coverage.load_input(str(p))
        assert result["openapi"] == "3.0.0"

    def test_missing_file_raises(self):
        with pytest.raises(ValueError, match="not found"):
            api_coverage.load_input("/nonexistent/spec.json")

    def test_empty_stdin_returns_none(self, monkeypatch):
        monkeypatch.setattr("sys.stdin", io.StringIO(""))
        result = api_coverage.load_input(None)
        assert result is None

    def test_invalid_json_raises(self, monkeypatch):
        monkeypatch.setattr("sys.stdin", io.StringIO("{bad json"))
        with pytest.raises(ValueError, match="Invalid JSON"):
            api_coverage.load_input(None)

    def test_array_raises(self, monkeypatch):
        monkeypatch.setattr("sys.stdin", io.StringIO("[1,2,3]"))
        with pytest.raises(ValueError, match="JSON object"):
            api_coverage.load_input(None)


# ---------------------------------------------------------------------------
# Subprocess integration — exit codes and output structure
# ---------------------------------------------------------------------------


class TestSubprocess:
    def test_valid_spec_exits_zero(self):
        spec = minimal_oas3(paths={"/items": {"get": minimal_get_op()}})
        code, out, err = run_script(args=("-",), stdin_text=json.dumps(spec))
        assert code == 0

    def test_output_has_json_block(self):
        spec = minimal_oas3(paths={"/items": {"get": minimal_get_op()}})
        code, out, err = run_script(args=("-",), stdin_text=json.dumps(spec))
        assert code == 0
        result = parse_json_block(out)
        assert "findings" in result
        assert "summary" in result

    def test_output_has_markdown_section(self):
        spec = minimal_oas3()
        code, out, err = run_script(args=("-",), stdin_text=json.dumps(spec))
        assert code == 0
        assert "API Documentation Coverage Report" in out

    def test_empty_input_exits_zero(self):
        code, out, err = run_script(args=("-",), stdin_text="")
        assert code == 0

    def test_empty_array_exits_nonzero(self):
        # Arrays are not valid spec objects
        code, out, err = run_script(args=("-",), stdin_text="[]")
        assert code != 0
        assert "ERROR" in err

    def test_bad_json_exits_nonzero(self):
        code, out, err = run_script(args=("-",), stdin_text="not json")
        assert code != 0
        assert "ERROR" in err

    def test_unknown_spec_format_exits_nonzero(self):
        code, out, err = run_script(args=("-",), stdin_text='{"title": "unknown"}')
        assert code != 0
        assert "ERROR" in err

    def test_file_path_argument(self, tmp_path):
        spec = minimal_oas3(paths={"/items": {"get": minimal_get_op()}})
        p = tmp_path / "spec.json"
        p.write_text(json.dumps(spec))
        code, out, err = run_script(args=(str(p),))
        assert code == 0
        result = parse_json_block(out)
        assert result["spec_version"] == "oas3"

    def test_nonexistent_file_exits_nonzero(self):
        code, _, err = run_script(args=("/no/such/spec.json",))
        assert code != 0
        assert "ERROR" in err

    def test_summary_counts_match_findings(self):
        # Build a spec with known findings: missing info fields + no-security op
        spec = minimal_oas3()
        # info has no contact/license -> 2 R13 LOW findings
        code, out, err = run_script(args=("-",), stdin_text=json.dumps(spec))
        assert code == 0
        result = parse_json_block(out)
        total = result["summary"]["total"]
        assert (
            total
            == result["summary"]["high"]
            + result["summary"]["medium"]
            + result["summary"]["low"]
        )
        assert total == len(result["findings"])

    def test_clean_spec_zero_findings(self):
        """A spec with all docs complete should emit zero findings."""
        info = {
            "title": "Full API",
            "version": "1.0.0",
            "contact": {"email": "api@example.com"},
            "license": {"name": "MIT"},
        }
        op = {
            "summary": "Get items",
            "description": "Returns a list of items.",
            "operationId": "getItems",
            "responses": {
                "200": {
                    "description": "OK",
                    "content": {
                        "application/json": {
                            "schema": {"type": "array"},
                            "example": [{"id": "1"}],
                        }
                    },
                },
                "400": {"description": "Bad Request"},
            },
        }
        spec = {"openapi": "3.0.0", "info": info, "paths": {"/items": {"get": op}}}
        code, out, err = run_script(args=("-",), stdin_text=json.dumps(spec))
        assert code == 0
        result = parse_json_block(out)
        assert result["summary"]["total"] == 0

    def test_swagger2_spec_accepted(self):
        spec = {
            "swagger": "2.0",
            "info": {"title": "Old API", "version": "1.0"},
            "paths": {},
        }
        code, out, err = run_script(args=("-",), stdin_text=json.dumps(spec))
        assert code == 0
        result = parse_json_block(out)
        assert result["spec_version"] == "swagger2"
