"""Deletion guards are tested against unrelated, active and identity-drifted resources."""

import copy
import time

import pytest
from cc.core.docker_resources import (
    PREFIX,
    Docker,
    Hold,
    Manager,
    atomic_json,
    check_capacity,
    lock,
)


class Engine:
    endpoint = "unix:///test/docker.sock"
    daemon = "daemon-one"

    def __init__(self, record):
        self.record = record
        self.removals = []
        self.volume = {
            "Name": record["volume"],
            "CreatedAt": record["volume_created"],
            "Driver": "local",
            "Options": None,
            "Labels": dict(record["labels"]),
        }
        self.container = {
            "Id": record["container"],
            "Name": "/" + record["name"],
            "Image": record["image_id"],
            "Config": {
                "Labels": dict(record["labels"]),
                "Env": ["POSTGRES_USER=cc_synthetic", "POSTGRES_PASSWORD=synthetic"],
            },
            "State": {"Running": False},
            "Mounts": [
                {
                    "Type": "volume",
                    "Name": record["volume"],
                    "Destination": record["mount"],
                }
            ],
        }
        self.foreign = False

    def inspect(self, kind, name):
        return copy.deepcopy(self.volume if kind == "volume" else self.container)

    def call(self, *args, **kwargs):
        if args[0] == "info":
            return self.daemon
        if args[0] == "ps":
            return ("foreign-container\n" if self.foreign else "") + (
                self.record["container"] if self.container else ""
            )
        if args[0] == "stop":
            self.container["State"]["Running"] = False
        elif args[0] == "rm":
            self.removals.append(("container", args[1]))
            self.container = None
        elif args[:2] == ("volume", "rm"):
            self.removals.append(("volume", args[2]))
            self.volume = None
        return ""


@pytest.fixture
def managed(tmp_path):
    record = dict(
        schema=1,
        origin="cc.resources.run",
        id="a" * 32,
        project=str(tmp_path / "project"),
        task="TASK-179",
        owner="tester",
        endpoint=Engine.endpoint,
        daemon=Engine.daemon,
        name="cc-test-owned",
        container="c" * 64,
        volume="cc-test-volume",
        volume_created="2026-10-27T12:00:00Z",
        labels={PREFIX + "run": "a" * 32, PREFIX + "token": "secret"},
        image_id="sha256:123",
        mount="/var/lib/postgresql/data",
        status="retained",
        port="55432",
        expires_at=time.time() - 1,
    )
    engine = Engine(record)
    policy = tmp_path / "policy.json"
    atomic_json(
        policy,
        {
            "automatic_synthetic_cleanup": True,
            "approval": "Owner authorized synthetic cleanup",
        },
    )
    manager = Manager(tmp_path / "state", policy, engine)
    manager.save(record)
    return manager, engine, record


def test_exact_owned_stopped_resources_removed_and_receipt_kept(managed):
    manager, engine, record = managed
    manager.finish(record["id"])
    assert engine.removals == [("container", "c" * 64), ("volume", "cc-test-volume")]
    assert manager.load(record["id"])["status"] == "cleaned"
    manager.finish(record["id"])
    assert len(engine.removals) == 2


@pytest.mark.parametrize(
    "drift",
    [
        "daemon",
        "volume_labels",
        "volume_created",
        "volume_options",
        "container_labels",
        "image",
        "mount",
        "foreign",
        "running",
        "origin",
        "incomplete",
    ],
)
def test_drift_or_live_resources_are_never_deleted(managed, drift):
    manager, engine, record = managed
    if drift == "daemon":
        engine.daemon = "different-daemon"
    elif drift == "volume_labels":
        engine.volume["Labels"] = {}
    elif drift == "volume_created":
        engine.volume["CreatedAt"] = "recreated-volume"
    elif drift == "volume_options":
        engine.volume["Options"] = {"device": "/real/data"}
    elif drift == "container_labels":
        engine.container["Config"]["Labels"] = {}
    elif drift == "image":
        engine.container["Image"] = "sha256:another"
    elif drift == "mount":
        engine.container["Mounts"].append({"Type": "bind", "Source": "/real/data"})
    elif drift == "foreign":
        engine.foreign = True
    elif drift == "running":
        engine.container["State"]["Running"] = True
    elif drift == "origin":
        record["origin"] = "adopted"
    elif drift == "incomplete":
        del record["container"]
    manager.save(record)
    with pytest.raises(Hold):
        manager.finish(record["id"])
    assert engine.removals == []


def test_active_project_lock_protects_even_stopped_container(managed):
    manager, engine, record = managed
    with lock(manager.project_lock(record["project"])):
        with pytest.raises(Hold):
            manager.finish(record["id"])
        assert manager.sweep()[0]["status"] == "hold"
    assert engine.removals == []


def test_labels_without_private_receipt_cannot_authorize_cleanup(managed):
    manager, engine, record = managed
    with pytest.raises(FileNotFoundError):
        manager.finish("b" * 32)
    assert engine.removals == []


def test_revoked_policy_holds_expired_data(managed):
    manager, engine, record = managed
    atomic_json(
        manager.policy, {"automatic_synthetic_cleanup": False, "approval": "revoked"}
    )
    with pytest.raises(Hold):
        manager.sweep()
    assert engine.removals == []


def test_failed_run_retention_and_expiry(managed):
    manager, engine, record = managed
    engine.container["State"]["Running"] = True
    manager.retain(record, "child exit 3")
    retained = manager.load(record["id"])
    assert retained["expires_at"] >= time.time() + 48 * 3600 - 2
    assert not engine.container["State"]["Running"]
    assert manager.sweep()[0]["status"] == "retained"
    assert engine.removals == []
    retained["expires_at"] = time.time() - 1
    manager.save(retained)
    assert manager.sweep()[0]["status"] == "cleaned"


def test_unfinished_expired_run_is_held(managed):
    manager, engine, record = managed
    record["status"] = "creating"
    manager.save(record)
    assert manager.sweep()[0]["status"] == "hold"
    assert engine.removals == []


def test_ownership_is_rechecked_after_stop(managed):
    manager, engine, record = managed
    engine.container["State"]["Running"] = True
    original = engine.call

    def drift(*args, **kwargs):
        result = original(*args, **kwargs)
        if args[0] == "stop":
            engine.foreign = True
        return result

    engine.call = drift
    with pytest.raises(Hold):
        manager.cleanup(record, owned_active=True)
    assert engine.removals == []


@pytest.mark.parametrize("percentage", [85, 99, 100, -1, 101])
def test_capacity_blocks_at_or_above_85_and_invalid_measurement(percentage):
    with pytest.raises(Hold):
        check_capacity(percentage)


def test_capacity_warns_at_70_and_allows_below_85(capsys):
    check_capacity(69)
    assert capsys.readouterr().err == ""
    check_capacity(70)
    assert "70%" in capsys.readouterr().err
    check_capacity(84)


@pytest.mark.parametrize(
    "endpoint", ["tcp://localhost:2375", "ssh://remote", "unix://relative"]
)
def test_remote_and_nonabsolute_endpoints_refused(endpoint):
    with pytest.raises(Hold):
        Docker(endpoint)


def test_port_or_project_override_cannot_target_application_server(
    managed, monkeypatch
):
    manager, engine, record = managed
    record["status"] = "active"
    manager.save(record)
    engine.container["State"]["Running"] = True
    for key, value in {
        "CC_TEST_RUN_ID": record["id"],
        "CC_TEST_TOKEN": "secret",
        "PGHOST": "127.0.0.1",
        "PGPORT": "55432",
        "PGUSER": "cc_synthetic",
        "PGPASSWORD": "synthetic",
    }.items():
        monkeypatch.setenv(key, value)
    manager.validate_environment(record["project"])
    monkeypatch.setenv("PGPORT", "5432")
    with pytest.raises(Hold):
        manager.validate_environment(record["project"])
    monkeypatch.setenv("PGPORT", "55432")
    with pytest.raises(Hold):
        manager.validate_environment("/another-project")


def test_retained_run_prevents_accumulation(managed, tmp_path):
    manager, engine, record = managed
    project = tmp_path / "project"
    project.mkdir()
    record["expires_at"] = time.time() + 3600
    manager.save(record)
    with pytest.raises(Hold, match="already has retained"):
        manager.run(project, "TASK-179", "ops", ["true"])
    assert engine.removals == []


def test_records_are_private_and_path_traversal_is_rejected(managed):
    manager, engine, record = managed
    assert manager.path(record["id"]).stat().st_mode & 0o777 == 0o600
    with pytest.raises(Hold):
        manager.finish("../unknown")


def test_container_inspection_uses_full_ids():
    docker = object.__new__(Docker)

    def call(*args):
        if args[:2] == ("container", "ls"):
            assert "--no-trunc" in args
            return "c" * 64
        return '[{"Id": "' + "c" * 64 + '"}]'

    docker.call = call
    assert docker.inspect("container", "c" * 64)["Id"] == "c" * 64


def test_application_url_override_is_rejected_even_with_valid_pg_environment(
    managed, monkeypatch
):
    manager, engine, record = managed
    record["status"] = "active"
    manager.save(record)
    engine.container["State"]["Running"] = True
    for key, value in {
        "CC_TEST_RUN_ID": record["id"],
        "CC_TEST_TOKEN": "secret",
        "PGHOST": "127.0.0.1",
        "PGPORT": "55432",
        "PGUSER": "cc_synthetic",
        "PGPASSWORD": "synthetic",
        "DATABASE_URL": "postgresql+asyncpg://cc_synthetic:synthetic@127.0.0.1:5432/application",
    }.items():
        monkeypatch.setenv(key, value)
    with pytest.raises(Hold, match="DATABASE_URL"):
        manager.validate_environment(record["project"])
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+asyncpg://cc_synthetic:synthetic@127.0.0.1:55432/test?host=elsewhere",
    )
    with pytest.raises(Hold, match="DATABASE_URL"):
        manager.validate_environment(record["project"])


def test_audit_counts_embedded_databases_without_adopting_or_removing(managed):
    manager, engine, record = managed
    import json

    calls = []

    def read_only(*args, **kwargs):
        calls.append(args)
        if args[0] == "ps":
            return "unmanaged-id"
        if args[:2] == ("container", "inspect"):
            return json.dumps(
                [
                    {
                        "Id": "unmanaged-id",
                        "Name": "/legacy-test-db",
                        "Created": "2026-10-01T00:00:00Z",
                        "State": {"Running": True},
                        "Config": {
                            "Image": "postgres:18",
                            "Env": ["POSTGRES_USER=owner"],
                        },
                    }
                ]
            )
        if args[0] == "exec":
            assert "SELECT json_agg" in args[-1]
            return '["application", "postgres", "test_hidden"]'
        if args[:2] == ("volume", "ls"):
            return "application-volume"
        raise AssertionError(f"Unexpected mutation or command: {args}")

    engine.call = read_only
    report = manager.audit()
    server = report["database_servers"][0]
    assert report["containers_total"] == 1 and report["volumes_total"] == 1
    assert server["database_count"] == 3 and server["test_name_candidates"] == [
        "test_hidden"
    ]
    assert server["unmanaged_test_candidate"] and not server["registered"]
    assert len(manager.records()) == 1
    assert engine.removals == []
