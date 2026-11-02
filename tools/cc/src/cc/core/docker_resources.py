"""Own only fresh synthetic Docker resources; never infer deletion authority from names."""

from __future__ import annotations

import contextlib
import datetime
import fcntl
import getpass
import hashlib
import io
import json
import os
import re
import secrets
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

PREFIX = "io.copilot.synthetic."
PROFILES = {
    "ops": ("postgres:18", "/var/lib/postgresql", "ops_dev_local"),
    "convoco": ("pgvector/pgvector:pg16", "/var/lib/postgresql/data", "postgres"),
    "postgres": ("postgres:16-alpine", "/var/lib/postgresql/data", "postgres"),
}
RETENTION = 48 * 3600


class Hold(RuntimeError):
    """Fail closed, leaving resources available for inspection."""


def atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(data, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


@contextlib.contextmanager
def lock(path):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise Hold(
                "A managed run or cleanup is already active for this project."
            ) from exc
        yield
    finally:
        os.close(fd)


class Docker:
    def __init__(self, endpoint=None):
        self.env = {
            k: v
            for k, v in os.environ.items()
            if k
            not in {
                "DOCKER_HOST",
                "DOCKER_CONTEXT",
                "DOCKER_TLS_VERIFY",
                "DOCKER_CERT_PATH",
            }
        }
        if endpoint is None:
            if os.environ.get("DOCKER_HOST"):
                raise Hold(
                    "Unset DOCKER_HOST; select a local Docker context explicitly."
                )
            context = os.environ.get("DOCKER_CONTEXT") or self.raw(["context", "show"])
            context_info = json.loads(self.raw(["context", "inspect", context]))[0]
            endpoint = context_info["Endpoints"]["docker"]["Host"]
        if not endpoint.startswith("unix:///"):
            raise Hold("Managed tests require a local Unix-socket Docker endpoint.")
        self.endpoint = endpoint
        self.daemon = self.call("info", "--format", "{{.ID}}")
        if not self.daemon:
            raise Hold("Docker daemon identity is unavailable.")

    def raw(self, args, *, check=True, timeout=60, include_stderr=False):
        result = subprocess.run(
            ["docker", *args],
            env=self.env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if check and result.returncode:
            # Never print container env or arbitrary stderr that could contain credentials.
            raise Hold(f"Docker {args[0]} failed (exit {result.returncode}).")
        return (result.stdout + (result.stderr if include_stderr else "")).strip()

    def call(self, *args, **kwargs):
        return self.raw(["--host", self.endpoint, *args], **kwargs)

    def inspect(self, kind, name):
        # A daemon/permission failure must not be confused with a missing resource.
        listing = (
            self.call(kind, "ls", "-aq", "--no-trunc")
            if kind == "container"
            else self.call("volume", "ls", "-q")
        )
        if name not in listing.splitlines():
            return None
        return json.loads(self.call(kind, "inspect", name))[0]

    def capacity(self):
        output = self.call(
            "run",
            "--rm",
            "--pull=never",
            "--network=none",
            "--read-only",
            "--log-driver=none",
            "--label",
            PREFIX + "probe=true",
            "alpine:latest",
            "df",
            "-Pk",
            "/",
        )
        try:
            percent = int(output.splitlines()[-1].split()[4].rstrip("%"))
        except (ValueError, IndexError) as exc:
            raise Hold("Could not measure Docker filesystem capacity.") from exc
        check_capacity(percent)
        return percent


def check_capacity(percent):
    if not 0 <= percent <= 100:
        raise Hold("Invalid Docker capacity measurement.")
    if percent >= 85:
        raise Hold(
            f"Docker disk is {percent}% full; new test servers are blocked at 85%."
        )
    if percent >= 70:
        print(
            f"Warning: Docker disk is {percent}% full (warning threshold 70%).",
            file=sys.stderr,
        )


class Manager:
    def __init__(self, state=None, policy=None, docker=None):
        self.state = Path(
            state or Path.home() / ".local/state/copilot/docker-resources"
        )
        self.policy = Path(
            policy or Path.home() / ".config/copilot/docker-resources.json"
        )
        self.docker = docker
        self.state.mkdir(parents=True, exist_ok=True, mode=0o700)

    def authorize(self):
        try:
            policy = json.loads(self.policy.read_text())
        except (OSError, ValueError) as exc:
            raise Hold(
                "Managed synthetic cleanup policy has not been enabled by the owner."
            ) from exc
        if policy.get("automatic_synthetic_cleanup") is not True or not policy.get(
            "approval"
        ):
            raise Hold("Owner approval for managed synthetic cleanup is required.")

    def path(self, run_id):
        if not re.fullmatch(r"[0-9a-f]{32}", run_id):
            raise Hold("Invalid managed run ID.")
        return self.state / (run_id + ".json")

    def save(self, record):
        atomic_json(self.path(record["id"]), record)

    def load(self, run_id):
        return json.loads(self.path(run_id).read_text())

    def project_lock(self, project):
        return self.state / (
            "project-" + hashlib.sha256(project.encode()).hexdigest() + ".lock"
        )

    def connection(self, record):
        docker = self.docker or Docker(record["endpoint"])
        if docker.endpoint != record["endpoint"] or docker.daemon != record["daemon"]:
            raise Hold("Docker endpoint or daemon identity changed.")
        if docker.call("info", "--format", "{{.ID}}") != record["daemon"]:
            raise Hold("Docker daemon identity changed during the operation.")
        return docker

    def verify(self, record):
        docker = self.connection(record)
        if record.get("schema") != 1 or record.get("origin") != "cc.resources.run":
            raise Hold("No supported private creation record.")
        if not record.get("volume_created") or not record.get("container"):
            raise Hold(
                "Incomplete creation receipt; inspect manually without adopting resources."
            )
        volume = docker.inspect("volume", record["volume"])
        container = docker.inspect("container", record["container"])
        if volume:
            if (
                volume.get("Labels") != record["labels"]
                or volume["CreatedAt"] != record["volume_created"]
                or volume.get("Driver") != "local"
                or volume.get("Options")
            ):
                raise Hold("Volume ownership or creation identity changed.")
            consumers = docker.call(
                "ps", "-aq", "--no-trunc", "--filter", "volume=" + record["volume"]
            ).splitlines()
            if set(consumers) - {record["container"]}:
                raise Hold("Another container uses the managed volume; cleanup held.")
        if container:
            mounts = container.get("Mounts", [])
            expected_mount = (
                len(mounts) == 1
                and mounts[0].get("Type") == "volume"
                and mounts[0].get("Name") == record["volume"]
                and mounts[0].get("Destination") == record["mount"]
            )
            if (
                container["Id"] != record["container"]
                or container["Name"] != "/" + record["name"]
                or container["Image"] != record["image_id"]
                or container["Config"].get("Labels") != record["labels"]
                or not expected_mount
                or not volume
            ):
                raise Hold(
                    "Container ownership, image or mounts changed; cleanup held."
                )
        return docker, container, volume

    def cleanup(self, record, *, owned_active=False):
        self.authorize()
        docker, container, volume = self.verify(record)
        if container:
            if container["State"]["Running"] and not owned_active:
                raise Hold(
                    "Running resources are protected; use the owning test session."
                )
            if container["State"]["Running"]:
                docker.call("stop", "--time", "10", record["container"])
            # Recheck volume consumers and all identities immediately before removal.
            docker, container, volume = self.verify(record)
            if container:
                if container["State"]["Running"]:
                    raise Hold("Container restarted; cleanup held.")
                docker.call("rm", record["container"])
        _, _, volume = self.verify(record)
        if volume:
            docker.call("volume", "rm", record["volume"])
        record.update(status="cleaned", cleaned_at=time.time())
        self.save(record)

    def retain(self, record, reason):
        docker, container, _ = self.verify(record)
        if container:
            if container["State"]["Running"]:
                docker.call("stop", "--time", "10", record["container"])
            logs = docker.call(
                "logs",
                "--tail",
                "150",
                record["container"],
                check=False,
                include_stderr=True,
            )
            # Bounded diagnostic log; no environment values or command arguments in receipts.
            record["log_tail"] = logs[-12000:]
        record.update(
            status="retained", reason=reason, expires_at=time.time() + RETENTION
        )
        self.save(record)
        print(f"Test data retained for 48 hours. Run: {record['id']}", file=sys.stderr)

    def run(self, project, task, profile, command):
        self.authorize()
        if not command or not task.strip():
            raise Hold("A task identifier and child command are required.")
        project = str(Path(project).resolve(strict=True))
        with lock(self.project_lock(project)):
            # Bound retained data per checkout as well as concurrent active work.
            for old in self.records():
                if old["project"] == project and old["status"] != "cleaned":
                    if old["status"] == "retained" and old["expires_at"] <= time.time():
                        self.cleanup(old)
                    else:
                        raise Hold(
                            f"Project already has retained or unfinished run {old['id']}. Inspect it before starting another."
                        )
            docker = self.docker or Docker()
            docker.capacity()
            image, mount, database = PROFILES[profile]
            image_id = docker.call("image", "inspect", image, "--format", "{{.Id}}")
            if not image_id.startswith("sha256:"):
                raise Hold(
                    "The pinned local test image is unavailable; no automatic pull is allowed."
                )
            run_id = uuid.uuid4().hex
            now = time.time()
            record = dict(
                schema=1,
                origin="cc.resources.run",
                id=run_id,
                project=project,
                task=task,
                owner=getpass.getuser(),
                profile=profile,
                created_at=now,
                expires_at=now + RETENTION,
                endpoint=docker.endpoint,
                daemon=docker.daemon,
                name="cc-test-" + profile + "-" + run_id,
                volume="cc-test-" + run_id,
                mount=mount,
                image_id=image_id,
                database=database,
                status="creating",
            )
            record["labels"] = {
                PREFIX + "run": run_id,
                PREFIX + "token": secrets.token_hex(24),
                PREFIX + "project": project,
                PREFIX + "task": task,
                PREFIX + "owner": record["owner"],
                PREFIX + "kind": "test-database",
                PREFIX + "expires": str(int(now + RETENTION)),
            }
            self.save(record)  # Journal intent before either resource is created.
            labels = [
                part
                for key, value in record["labels"].items()
                for part in ("--label", key + "=" + value)
            ]
            password = secrets.token_hex(24)
            try:
                if docker.inspect("volume", record["volume"]):
                    raise Hold("Unexpected existing volume: no adoption permitted.")
                docker.call("volume", "create", *labels, record["volume"])
                volume = docker.inspect("volume", record["volume"])
                record["volume_created"] = volume["CreatedAt"]
                self.save(record)
                record["container"] = docker.call(
                    "create",
                    "--pull=never",
                    "--name",
                    record["name"],
                    *labels,
                    "--memory=2g",
                    "--cpus=2",
                    "--shm-size=512m",
                    "--restart=no",
                    "--log-driver=json-file",
                    "--log-opt=max-size=10m",
                    "--log-opt=max-file=3",
                    "--mount",
                    f"type=volume,src={record['volume']},dst={mount}",
                    "-p",
                    "127.0.0.1::5432",
                    "-e",
                    "POSTGRES_USER=cc_synthetic",
                    "-e",
                    "POSTGRES_PASSWORD=" + password,
                    "-e",
                    "POSTGRES_DB=" + database,
                    image_id,
                )
                self.save(record)
                self.verify(record)
                docker.call("start", record["container"])
                deadline = time.monotonic() + 60
                while time.monotonic() < deadline:
                    ready = docker.call(
                        "exec",
                        record["container"],
                        "pg_isready",
                        "-h",
                        "127.0.0.1",
                        "-U",
                        "cc_synthetic",
                        "-d",
                        database,
                        check=False,
                    )
                    if "accepting connections" in ready:
                        break
                    time.sleep(0.5)
                else:
                    raise Hold("Test PostgreSQL readiness timed out after 60 seconds.")
                port = json.loads(docker.call("inspect", record["container"]))[0][
                    "NetworkSettings"
                ]["Ports"]["5432/tcp"]
                if len(port) != 1 or port[0]["HostIp"] != "127.0.0.1":
                    raise Hold("Test PostgreSQL was not bound exclusively to loopback.")
                record.update(port=port[0]["HostPort"], status="active")
                self.save(record)
                url = f"postgresql+asyncpg://cc_synthetic:{password}@127.0.0.1:{record['port']}/{database}"
                env = dict(
                    os.environ,
                    PGHOST="127.0.0.1",
                    PGPORT=record["port"],
                    PGUSER="cc_synthetic",
                    PGPASSWORD=password,
                    PGDATABASE=database,
                    DATABASE_URL=url,
                    TEST_DATABASE_URL=url,
                    OPS_M1_TEST_SERVER=url,
                    CC_TEST_RUN_ID=run_id,
                    CC_TEST_TOKEN=record["labels"][PREFIX + "token"],
                )
                # Never inherit URLs pointing to application servers into managed runs.
                for key in (
                    "ASK_TEST_DATABASE_URL",
                    "SESSION_TEST_DATABASE_URL",
                    "PGSERVICE",
                    "PGSERVICEFILE",
                ):
                    env.pop(key, None)
                print(
                    f"Managed test run {run_id} ({profile}); localhost:{record['port']}",
                    file=sys.stderr,
                )
                child = subprocess.Popen(
                    command, cwd=project, env=env, start_new_session=True
                )
                handlers = {}

                def forward(sig, frame):
                    if child.poll() is None:
                        os.killpg(child.pid, sig)

                try:
                    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
                        handlers[sig] = signal.signal(sig, forward)
                    result = child.wait()
                finally:
                    for sig, handler in handlers.items():
                        signal.signal(sig, handler)
                if result == 0:
                    self.cleanup(record, owned_active=True)
                else:
                    self.retain(record, f"child exit {result}")
                return result if result >= 0 else 128 - result
            except BaseException:
                # Complete identity receipts can be safely stopped; uncertain creation is a hold.
                if (
                    record.get("container")
                    and record.get("volume_created")
                    and record["status"] != "cleaned"
                ):
                    try:
                        self.retain(record, "runner interrupted or failed")
                    except Exception:
                        record["status"] = "hold"
                        self.save(record)
                raise

    def records(self):
        return [
            json.loads(path.read_text())
            for path in sorted(self.state.glob("*.json"))
            if re.fullmatch(r"[0-9a-f]{32}", path.stem)
        ]

    def sweep(self):
        self.authorize()
        results = []
        for record in self.records():
            if record["status"] == "cleaned":
                continue
            if record["expires_at"] > time.time():
                results.append({"id": record["id"], "status": record["status"]})
                continue
            try:
                with lock(self.project_lock(record["project"])):
                    if record["status"] != "retained":
                        raise Hold(
                            "Unfinished run requires inspection; no automatic deletion."
                        )
                    self.cleanup(record)
                results.append({"id": record["id"], "status": "cleaned"})
            except (Hold, OSError, ValueError, subprocess.SubprocessError) as exc:
                results.append(
                    {"id": record["id"], "status": "hold", "reason": str(exc)}
                )
        return results

    def finish(self, run_id):
        record = self.load(run_id)
        if record["status"] == "cleaned":
            return
        with lock(self.project_lock(record["project"])):
            self.cleanup(record)

    def validate_environment(self, project):
        record = self.load(os.environ.get("CC_TEST_RUN_ID", ""))
        _, container, _ = self.verify(record)
        env = (
            dict(item.split("=", 1) for item in container["Config"]["Env"])
            if container
            else {}
        )
        if (
            record["status"] != "active"
            or not container
            or not container["State"]["Running"]
            or record["project"] != str(Path(project).resolve())
            or os.environ.get("CC_TEST_TOKEN") != record["labels"][PREFIX + "token"]
            or os.environ.get("PGHOST") != "127.0.0.1"
            or os.environ.get("PGPORT") != record["port"]
            or os.environ.get("PGUSER") != env.get("POSTGRES_USER")
            or os.environ.get("PGPASSWORD") != env.get("POSTGRES_PASSWORD")
        ):
            raise Hold(
                "Connection settings do not match the active managed test server."
            )
        for key in (
            "DATABASE_URL",
            "TEST_DATABASE_URL",
            "OPS_M1_TEST_SERVER",
            "ASK_TEST_DATABASE_URL",
            "SESSION_TEST_DATABASE_URL",
        ):
            if not os.environ.get(key):
                continue
            url = urlsplit(os.environ[key])
            if (
                url.scheme
                not in {"postgresql", "postgresql+asyncpg", "postgresql+psycopg"}
                or url.hostname != "127.0.0.1"
                or str(url.port) != record["port"]
                or url.username != env.get("POSTGRES_USER")
                or url.password != env.get("POSTGRES_PASSWORD")
                or url.query
                or url.fragment
            ):
                raise Hold(f"{key} does not target the managed synthetic server.")

    def status(self):
        result = []
        for record in self.records():
            item = {
                key: record[key]
                for key in ("id", "project", "task", "owner", "status", "expires_at")
            }
            if record["status"] != "cleaned":
                try:
                    docker, container, _ = self.verify(record)
                    item["running"] = bool(container and container["State"]["Running"])
                    if item["running"]:
                        count = docker.call(
                            "exec",
                            record["container"],
                            "psql",
                            "-U",
                            "cc_synthetic",
                            "-d",
                            "postgres",
                            "-Atc",
                            "SELECT count(*) FROM pg_database WHERE NOT datistemplate",
                        )
                        item["databases"] = int(count)
                except (Hold, OSError, ValueError, subprocess.SubprocessError) as exc:
                    item["hold"] = str(exc)
            result.append(item)
        return result

    def audit(self):
        """Read-only inventory, including databases inside unregistered PostgreSQL."""
        docker = self.docker or Docker()
        ids = docker.call("ps", "-aq", "--no-trunc").splitlines()
        containers = (
            json.loads(docker.call("container", "inspect", *ids)) if ids else []
        )
        known = {r.get("container") for r in self.records() if r["status"] != "cleaned"}
        servers = []
        for container in containers:
            config = container["Config"]
            image = config.get("Image", "").lower()
            env = dict(
                item.split("=", 1) for item in config.get("Env", []) if "=" in item
            )
            postgres = (
                any(word in image for word in ("postgres", "pgvector"))
                or "POSTGRES_USER" in env
            )
            if not postgres and not any(word in image for word in ("mysql", "mariadb")):
                continue
            name = container["Name"].lstrip("/")
            created = datetime.datetime.fromisoformat(
                container["Created"].replace("Z", "+00:00")
            )
            item = {
                "name": name,
                "id": container["Id"],
                "created_at": container["Created"],
                "registered": container["Id"] in known,
                "running": container["State"]["Running"],
                "age_hours": round((time.time() - created.timestamp()) / 3600, 1),
            }
            # A name is a review hint only; never an adoption/deletion rule.
            item["unmanaged_test_candidate"] = not item["registered"] and bool(
                re.search(r"test|^ops-dev-", name)
            )
            if postgres and item["running"]:
                try:
                    names = json.loads(
                        docker.call(
                            "exec",
                            container["Id"],
                            "psql",
                            "-X",
                            "-U",
                            env.get("POSTGRES_USER", "postgres"),
                            "-d",
                            "postgres",
                            "-Atc",
                            "SELECT json_agg(datname ORDER BY datname) FROM pg_database WHERE NOT datistemplate",
                            timeout=15,
                        )
                    )
                    item["database_count"] = len(names)
                    item["test_name_candidates"] = [
                        name
                        for name in names
                        if re.search(r"^test_|^ops_dev_|_test_", name)
                    ]
                except (Hold, ValueError, subprocess.SubprocessError) as exc:
                    item["database_count_hold"] = str(exc)
            servers.append(item)
        return {
            "containers_total": len(ids),
            "volumes_total": len(docker.call("volume", "ls", "-q").splitlines()),
            "database_servers": servers,
            "note": "Unmanaged candidates are review hints only; never automatically removed.",
        }

    def maintain(self):
        """Hourly sweep and capacity audit; keep one bounded current report."""
        report = {"checked_at": time.time()}
        try:
            report["sweep"] = self.sweep()
            with contextlib.redirect_stderr(io.StringIO()) as warnings:
                report["docker_disk_percent"] = (self.docker or Docker()).capacity()
            report["warning"] = warnings.getvalue().strip()
            report["runs"] = self.status()
            report["inventory"] = self.audit()
        except (Hold, OSError, ValueError, subprocess.SubprocessError) as exc:
            report["hold"] = str(exc)
        atomic_json(self.state / "maintenance.json", report)
        return report
