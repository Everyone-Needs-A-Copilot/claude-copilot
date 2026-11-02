"""MySQL uses the same private receipts and identity checks as PostgreSQL."""

import os

import pytest

from cc.core.docker_resources import Hold, PREFIX, PROFILES
from .test_docker_resources import managed  # Shared unchanged ownership fixture.


@pytest.fixture
def mysql_managed(managed, monkeypatch):
    manager, engine, record = managed
    record.update(
        engine="mysql",
        profile="mysql",
        database="h3_testing",
        mount="/var/lib/mysql",
        status="active",
    )
    engine.container["Mounts"][0]["Destination"] = record["mount"]
    engine.container["State"]["Running"] = True
    engine.container["Config"]["Env"] = [
        "MYSQL_USER=cc_synthetic",
        "MYSQL_PASSWORD=synthetic",
    ]
    manager.save(record)
    for key in (
        "DATABASE_URL",
        "TEST_DATABASE_URL",
        "DB_URL",
        "OPS_M1_TEST_SERVER",
        "ASK_TEST_DATABASE_URL",
        "SESSION_TEST_DATABASE_URL",
    ):
        monkeypatch.delenv(key, raising=False)
    values = {
        "CC_TEST_RUN_ID": record["id"],
        "CC_TEST_TOKEN": "secret",
        "DB_CONNECTION": "mysql-test",
        "DB_HOST": "127.0.0.1",
        "DB_PORT": "55432",
        "DB_DATABASE": "h3_testing",
        "DB_USERNAME": "cc_synthetic",
        "DB_PASSWORD": "synthetic",
        "DB_TEST_HOST": "127.0.0.1",
        "DB_TEST_PORT": "55432",
        "DB_TEST_DATABASE": "h3_testing",
        "DB_TEST_USERNAME": "cc_synthetic",
        "DB_TEST_PASSWORD": "synthetic",
        "MYSQL_HOST": "127.0.0.1",
        "MYSQL_TCP_PORT": "55432",
        "MYSQL_DATABASE": "h3_testing",
        "MYSQL_USER": "cc_synthetic",
        "MYSQL_PWD": "synthetic",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    return manager, engine, record


def test_mysql_uses_clean_upstream_image_and_dedicated_data_mount():
    assert PROFILES["mysql"] == ("mysql:8.4", "/var/lib/mysql", "h3_testing")


def test_mysql_environment_accepts_owned_server(mysql_managed):
    manager, _, record = mysql_managed
    manager.validate_environment(record["project"])


@pytest.mark.parametrize(
    "key,value",
    [
        ("DB_HOST", "application-db"),
        ("DB_PORT", "3306"),
        ("DB_DATABASE", "application"),
        ("DB_PASSWORD", "wrong"),
        ("DB_CONNECTION", "mysql"),
        ("DB_TEST_HOST", "application-db"),
        ("DB_TEST_PORT", "3306"),
        ("DB_TEST_DATABASE", "application"),
        ("DB_TEST_USERNAME", "root"),
        ("MYSQL_HOST", "application-db"),
        ("MYSQL_TCP_PORT", "3306"),
        ("MYSQL_PWD", "wrong"),
        ("CC_TEST_TOKEN", "wrong"),
    ],
)
def test_mysql_application_overrides_refused(mysql_managed, monkeypatch, key, value):
    manager, engine, record = mysql_managed
    monkeypatch.setenv(key, value)
    with pytest.raises(Hold):
        manager.validate_environment(record["project"])
    assert not engine.removals


@pytest.mark.parametrize(
    "url",
    [
        "mysql://cc_synthetic:synthetic@127.0.0.1:3306/h3_testing",
        "mysql://root:synthetic@127.0.0.1:55432/h3_testing",
        "mysql://cc_synthetic:synthetic@127.0.0.1:55432/application",
        "mysql://cc_synthetic:synthetic@127.0.0.1:55432/h3_testing?host=application",
        "postgresql://cc_synthetic:synthetic@127.0.0.1:55432/h3_testing",
    ],
)
@pytest.mark.parametrize("key", ["DATABASE_URL", "TEST_DATABASE_URL", "DB_URL"])
def test_mysql_url_overrides_refused(mysql_managed, monkeypatch, key, url):
    manager, engine, record = mysql_managed
    monkeypatch.setenv(key, url)
    with pytest.raises(Hold, match=key):
        manager.validate_environment(record["project"])
    assert not engine.removals


def test_mysql_exact_urls_allowed(mysql_managed, monkeypatch):
    manager, _, record = mysql_managed
    for key in ("DATABASE_URL", "TEST_DATABASE_URL", "DB_URL"):
        monkeypatch.setenv(
            key, "mysql://cc_synthetic:synthetic@127.0.0.1:55432/h3_testing"
        )
    manager.validate_environment(record["project"])


def test_mysql_cleanup_refuses_live_run_then_cleans_exact_owned_stopped_resources(
    mysql_managed,
):
    manager, engine, record = mysql_managed
    with pytest.raises(Hold, match="Running"):
        manager.finish(record["id"])
    assert not engine.removals
    engine.container["State"]["Running"] = False
    manager.finish(record["id"])
    assert engine.removals == [
        ("container", record["container"]),
        ("volume", record["volume"]),
    ]
    assert manager.load(record["id"])["status"] == "cleaned"


def test_mysql_foreign_volume_consumer_holds_cleanup(mysql_managed):
    manager, engine, record = mysql_managed
    engine.container["State"]["Running"] = False
    engine.foreign = True
    with pytest.raises(Hold, match="Another container"):
        manager.finish(record["id"])
    assert not engine.removals
