"""
Tests for test projects (adapters/test_project): the runner-neutral engine
and the Robot Framework AIO adapter.

Covers initialization, planning vs applying, the per-file status model
(create / update / unchanged / modified / keep), protection of local
edits, generation from .proto files and from reflection descriptors,
proto discovery, advisories, path safety, and the bridge endpoints that
do not need a live Consul.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
sys.path.insert(0, REPO)

from MicroserviceBase.adapters import test_project as tp  # noqa: E402

HELLO_PROTO = os.path.join(REPO, "examples", "hello_service", "proto", "hello.proto")
HELLO_FQN = "hello.v1.HelloService"
CONSUL = "http://127.0.0.1:8501"

RESOURCE = "resources/hello/hello_service.resource"
PROTO = "proto/hello/hello.proto"
SUITE = "testsuites/hello_smoke.robot"
CONFIG = "testsuites/config/robot_config.jsonp"


def _read(root, rel):
    with open(os.path.join(root, *rel.split("/")), encoding="utf-8") as fh:
        return fh.read()


def _write(root, rel, text):
    path = os.path.join(root, *rel.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def _statuses(plan):
    return {f["path"]: f["status"] for f in plan["files"]}


def _export(root, proto_file=HELLO_PROTO, **kwargs):
    files, warnings = tp.collect_proto_set(proto_file)
    return tp.export_service(
        str(root), "hello", consul_addr=CONSUL, grpc_services=[HELLO_FQN],
        proto_files=files, source={"kind": "proto", "path": proto_file},
        warnings=warnings, **kwargs)


def _descriptors(proto_file):
    from google.protobuf import descriptor_pb2
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "set.pb")
        subprocess.run(
            [sys.executable, "-m", "grpc_tools.protoc",
             f"--proto_path={os.path.dirname(proto_file)}",
             f"--descriptor_set_out={out}", proto_file],
            check=True, capture_output=True)
        fds = descriptor_pb2.FileDescriptorSet()
        with open(out, "rb") as fh:
            fds.ParseFromString(fh.read())
    return list(fds.file)


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "bench_tests"
    root.mkdir()
    tp.init_project(str(root), "robotframework-aio", consul_addr=CONSUL)
    return root


class Test_Init:

    def test_creates_manifest_layout_and_aio_config(self, project):
        manifest = json.loads(_read(project, tp.MANIFEST_NAME))
        assert manifest["runner"] == "robotframework-aio"
        assert manifest["services"] == {}
        for folder in ("testsuites", "resources", "proto"):
            assert (project / folder).is_dir()
        config = _read(project, CONFIG)
        assert '"CONSUL_ADDR" : "http://127.0.0.1:8501"' in config
        assert '"Project"       : "bench_tests"' in config

    def test_describe_reports_initialized(self, project):
        d = tp.describe(str(project))
        assert d["initialized"] is True
        assert d["runner_name"] == "Robot Framework AIO"
        assert d["layout"]["suites"] == "testsuites"

    def test_init_twice_is_rejected(self, project):
        with pytest.raises(tp.TestProjectError, match="already a test project"):
            tp.init_project(str(project), "robotframework-aio")

    def test_existing_files_are_not_touched(self, tmp_path):
        root = tmp_path / "existing"
        _write(root, CONFIG, "// mine\n")
        _write(root, "testsuites/old.robot", "*** Test Cases ***\n")
        before = tp.describe(str(root))
        assert before["initialized"] is False
        assert before["detected"] == {"robot_suites": 1, "aio_config": True}
        result = tp.init_project(str(root), "robotframework-aio")
        assert CONFIG in result["kept"]
        assert _read(root, CONFIG) == "// mine\n"

    def test_missing_folder_is_rejected(self, tmp_path):
        with pytest.raises(tp.TestProjectError, match="does not exist"):
            tp.init_project(str(tmp_path / "nope"), "robotframework-aio")

    def test_unknown_runner_is_rejected(self, tmp_path):
        with pytest.raises(tp.TestProjectError, match="No adapter for test runner"):
            tp.init_project(str(tmp_path), "pytest")


class Test_ExportFromProto:

    def test_plan_writes_nothing(self, project):
        plan = _export(project)
        assert plan["applied"] is False
        assert _statuses(plan) == {RESOURCE: "create", PROTO: "create",
                                   SUITE: "create", CONFIG: "keep"}
        assert not (project / "resources" / "hello").exists()
        assert json.loads(_read(project, tp.MANIFEST_NAME))["services"] == {}

    def test_apply_writes_files_and_records_hashes(self, project):
        result = _export(project, apply=True)
        assert sorted(result["written"]) == sorted([RESOURCE, PROTO, SUITE])
        resource = _read(project, RESOURCE)
        assert "Hello Service Open Connection" in resource
        assert "Hello Service Greet" in resource
        assert _read(project, PROTO) == open(HELLO_PROTO, encoding="utf-8").read()

        suite = _read(project, SUITE)
        assert "Library           RobotFramework_TestsuitesManagement    WITH NAME    testsuites" in suite
        assert "Resource          ../resources/hello/hello_service.resource" in suite
        assert "${PROTO_DIR}        ${CURDIR}/../proto/hello" in suite
        assert "    testsuites.testsuite_setup" in suite
        assert "Hello Service Open Connection    hello_service" in suite

        entry = json.loads(_read(project, tp.MANIFEST_NAME))["services"]["hello"]
        assert entry["grpc_services"] == [HELLO_FQN]
        assert entry["source"]["kind"] == "proto"
        assert entry["files"][RESOURCE]["role"] == "generated"
        assert len(entry["files"][RESOURCE]["sha256"]) == 64
        assert entry["files"][SUITE] == {"role": "starter"}
        assert result["run_hint"] == "python -m robot -d results testsuites/hello_smoke.robot"

    def test_reexport_is_unchanged_even_on_another_day(self, project):
        _export(project, apply=True)
        text = _read(project, RESOURCE)
        _write(project, RESOURCE, re.sub(r"(\.\.\.\s+Generated:\s+)\S+", r"\g<1>1999-01-01", text))
        plan = _export(project)
        assert _statuses(plan) == {RESOURCE: "unchanged", PROTO: "unchanged",
                                   SUITE: "keep", CONFIG: "keep"}

    def test_api_change_is_an_update_with_diff(self, project, tmp_path):
        _export(project, apply=True)
        changed = tmp_path / "src" / "hello.proto"
        changed.parent.mkdir()
        changed.write_text(open(HELLO_PROTO, encoding="utf-8").read().replace(
            "service HelloService {",
            "service HelloService {\n  rpc Ping (EchoRequest) returns (EchoResponse);", 1),
            encoding="utf-8")
        plan = _export(project, proto_file=str(changed))
        rows = {f["path"]: f for f in plan["files"]}
        assert rows[RESOURCE]["status"] == "update"
        assert "+Hello Service Ping" in rows[RESOURCE]["diff"]
        assert rows[PROTO]["status"] == "update"

        result = _export(project, proto_file=str(changed), apply=True)
        assert RESOURCE in result["written"]
        assert "Hello Service Ping" in _read(project, RESOURCE)

    def test_local_edit_is_protected_unless_overwrite_is_allowed(self, project):
        _export(project, apply=True)
        edited = _read(project, RESOURCE) + "\nMy Local Keyword\n    No Operation\n"
        _write(project, RESOURCE, edited)

        plan = _export(project)
        row = {f["path"]: f for f in plan["files"]}[RESOURCE]
        assert row["status"] == "modified"
        assert "-My Local Keyword" in row["diff"]

        kept = _export(project, apply=True)
        assert RESOURCE in kept["skipped"]
        assert _read(project, RESOURCE) == edited
        # still recognised as edited on the next plan
        assert _statuses(_export(project))[RESOURCE] == "modified"

        forced = _export(project, apply=True, overwrite_modified=True)
        assert RESOURCE in forced["written"]
        assert "My Local Keyword" not in _read(project, RESOURCE)

    def test_file_not_written_by_the_tool_counts_as_modified(self, project):
        _write(project, RESOURCE, "*** Keywords ***\nHand Written\n    No Operation\n")
        assert _statuses(_export(project))[RESOURCE] == "modified"

    def test_starter_suite_is_never_overwritten(self, project):
        _export(project, apply=True)
        _write(project, SUITE, "*** Test Cases ***\nMine\n    No Operation\n")
        result = _export(project, apply=True, overwrite_modified=True)
        assert SUITE not in result["written"]
        assert _read(project, SUITE).startswith("*** Test Cases ***\nMine")

    def test_starter_files_can_be_skipped(self, project):
        plan = _export(project, create_starter=False)
        assert set(_statuses(plan)) == {RESOURCE, PROTO}

    def test_stale_generated_file_is_reported_not_deleted(self, project):
        _export(project, apply=True)
        stale = "resources/hello/old_service.resource"
        _write(project, stale, "*** Keywords ***\n")
        manifest = json.loads(_read(project, tp.MANIFEST_NAME))
        manifest["services"]["hello"]["files"][stale] = {"role": "generated", "sha256": "0" * 64}
        _write(project, tp.MANIFEST_NAME, json.dumps(manifest))

        result = _export(project, apply=True)
        assert any(stale in a for a in result["advisories"])
        assert (project / "resources" / "hello" / "old_service.resource").exists()


class Test_ExportFromReflection:

    def test_generates_resource_without_protos(self, project):
        result = tp.export_service(
            str(project), "hello", consul_addr=CONSUL, grpc_services=[HELLO_FQN],
            file_descriptors=_descriptors(HELLO_PROTO),
            source={"kind": "reflection", "path": "127.0.0.1:1"}, apply=True)
        assert sorted(result["written"]) == sorted([RESOURCE, SUITE])
        resource = _read(project, RESOURCE)
        assert "Source proto: hello.proto (server reflection)" in resource
        assert "Hello Service Greet" in resource
        assert "${PROTO_DIR}        ${EMPTY}" in _read(project, SUITE)
        assert not (project / "proto" / "hello").exists()

    def test_same_keywords_as_the_proto_path(self, project, tmp_path):
        from_proto = _export(project)
        other = tmp_path / "other"
        other.mkdir()
        tp.init_project(str(other), "robotframework-aio", consul_addr=CONSUL)
        tp.export_service(
            str(other), "hello", consul_addr=CONSUL, grpc_services=[HELLO_FQN],
            file_descriptors=_descriptors(HELLO_PROTO), apply=True)
        _export(project, apply=True)
        keywords = lambda text: [l for l in text.splitlines() if l.startswith("Hello Service")]
        assert keywords(_read(project, RESOURCE)) == keywords(_read(other, RESOURCE))
        assert from_proto["status"] == "ok"

    def test_unknown_grpc_service_is_an_error(self, project):
        with pytest.raises(tp.TestProjectError, match="were found"):
            tp.export_service(
                str(project), "hello", consul_addr=CONSUL,
                grpc_services=["nope.v1.Missing"],
                file_descriptors=_descriptors(HELLO_PROTO))


class Test_ProtoDiscovery:

    def test_locates_the_declaring_file(self):
        found = tp.locate_service_proto([HELLO_FQN], [os.path.join(REPO, "examples")])
        assert found and found.endswith("hello.proto")
        assert HELLO_FQN in tp.proto_services(found)

    def test_file_paths_are_accepted_as_search_entries(self):
        assert tp.locate_service_proto([HELLO_FQN], [HELLO_PROTO]) == os.path.abspath(HELLO_PROTO)

    def test_all_copies_are_reported_in_search_order(self, tmp_path):
        text = open(HELLO_PROTO, encoding="utf-8").read()
        for folder in ("b_client", "a_service"):
            (tmp_path / folder).mkdir()
            (tmp_path / folder / "hello.proto").write_text(text, encoding="utf-8")
        matches = tp.find_service_protos([HELLO_FQN], [str(tmp_path)])
        assert [os.path.basename(os.path.dirname(m)) for m in matches] == ["a_service", "b_client"]
        assert tp.locate_service_proto([HELLO_FQN], [str(tmp_path)]) == matches[0]
        # an explicit earlier search path wins
        first = tp.find_service_protos([HELLO_FQN], [str(tmp_path / "b_client"), str(tmp_path)])
        assert os.path.basename(os.path.dirname(first[0])) == "b_client"
        assert len(first) == 2

    def test_unknown_service_is_not_found(self):
        assert tp.locate_service_proto(["nope.v1.Missing"], [os.path.join(REPO, "examples")]) is None

    def test_exclusion_callback_is_honoured(self):
        assert tp.locate_service_proto([HELLO_FQN], [HELLO_PROTO]) is not None
        assert tp.locate_service_proto(
            [HELLO_FQN], [os.path.dirname(HELLO_PROTO)], is_excluded=lambda p: True) is None

    def test_collects_local_imports_transitively(self, tmp_path):
        (tmp_path / "common").mkdir()
        (tmp_path / "common" / "types.proto").write_text(
            'syntax = "proto3";\npackage common;\nimport "common/units.proto";\nmessage T {}\n')
        (tmp_path / "common" / "units.proto").write_text('syntax = "proto3";\npackage common;\n')
        (tmp_path / "svc.proto").write_text(
            'syntax = "proto3";\npackage x.v1;\nimport "common/types.proto";\n'
            'import "google/protobuf/empty.proto";\n// import "commented/out.proto";\n'
            'import "missing.proto";\nservice S { rpc A (common.T) returns (common.T); }\n')
        files, warnings = tp.collect_proto_set(str(tmp_path / "svc.proto"))
        assert set(files) == {"svc.proto", "common/types.proto", "common/units.proto"}
        assert len(warnings) == 1 and "missing.proto" in warnings[0]


class Test_Safety:

    @pytest.mark.parametrize("name", ["../x", "a/b", "a\\b", "", ".hidden", "x y"])
    def test_unsafe_service_names_are_rejected(self, project, name):
        with pytest.raises(tp.TestProjectError):
            _export_named(project, name)

    def test_layout_cannot_escape_the_project(self, project):
        manifest = json.loads(_read(project, tp.MANIFEST_NAME))
        manifest["layout"]["resources"] = "../outside"
        _write(project, tp.MANIFEST_NAME, json.dumps(manifest))
        with pytest.raises(tp.TestProjectError, match="escapes the test project"):
            _export(project)

    def test_uninitialized_folder_is_rejected(self, tmp_path):
        with pytest.raises(tp.TestProjectError, match="not a test project"):
            _export(tmp_path)

    def test_nothing_to_generate_from(self, project):
        with pytest.raises(tp.TestProjectError, match="Nothing to generate"):
            tp.export_service(str(project), "hello", consul_addr=CONSUL, grpc_services=[HELLO_FQN])


def _export_named(root, name):
    files, _ = tp.collect_proto_set(HELLO_PROTO)
    return tp.export_service(str(root), name, consul_addr=CONSUL,
                             grpc_services=[HELLO_FQN], proto_files=files)


class Test_Advisories:

    def test_config_without_consul_addr(self, project):
        _write(project, CONFIG, '{ "Project": "x", "WelcomeString": "x", "TargetName": "x" }\n')
        plan = _export(project)
        assert any("does not define CONSUL_ADDR" in a for a in plan["advisories"])

    def test_config_pointing_at_another_consul(self, project):
        _write(project, CONFIG, _read(project, CONFIG).replace(CONSUL, "http://10.0.0.9:8500"))
        plan = _export(project)
        assert any("points suites at Consul http://10.0.0.9:8500" in a for a in plan["advisories"])


class Test_BridgeEndpoints:

    @pytest.fixture
    def client(self):
        pytest.importorskip("fastapi")
        pytest.importorskip("httpx")
        from fastapi.testclient import TestClient
        from MicroserviceBase.adapters.ui_bridge.fastapi_bridge import FastAPIBridge
        bridge = FastAPIBridge(host="localhost", port=1112, allowed_origins="*")
        return TestClient(bridge._build_app() or bridge._app)

    def test_describe_then_init(self, client, tmp_path):
        d = client.post("/api/test-project/describe", json={"root": str(tmp_path)}).json()
        assert d["status"] == "ok" and d["initialized"] is False
        assert {"id": "robotframework-aio", "name": "Robot Framework AIO"} in d["runners"]

        r = client.post("/api/test-project/init",
                        json={"root": str(tmp_path), "consul_addr": CONSUL}).json()
        assert r["status"] == "ok" and r["initialized"] is True
        assert CONFIG in r["created"]

        again = client.post("/api/test-project/init", json={"root": str(tmp_path)}).json()
        assert again["status"] == "error" and "already a test project" in again["error"]

    def test_export_rejects_unsafe_name_before_any_lookup(self, client, tmp_path):
        r = client.post("/api/test-project/export",
                        json={"root": str(tmp_path), "consul_name": "../evil"}).json()
        assert r["status"] == "error" and "Invalid service name" in r["error"]

    def test_tree_and_file(self, client, project):
        _export(project, apply=True)
        tree = client.post("/api/test-project/tree", json={"root": str(project)}).json()
        assert tree["status"] == "ok" and tree["services"][0]["name"] == "hello"
        f = client.post("/api/test-project/file", json={"root": str(project), "path": SUITE}).json()
        assert f["status"] == "ok" and "Hello Service Open Connection" in f["content"]
        bad = client.post("/api/test-project/file", json={"root": str(project), "path": "../x"}).json()
        assert bad["status"] == "error"

    def test_save_check_and_new_suite(self, client, project):
        _export(project, apply=True)
        root = str(project)
        opened = client.post("/api/test-project/file", json={"root": root, "path": SUITE}).json()
        saved = client.post("/api/test-project/file/save", json={
            "root": root, "path": SUITE, "content": opened["content"] + "\n",
            "expected_sha256": opened["sha256"]}).json()
        assert saved["status"] == "ok"
        stale = client.post("/api/test-project/file/save", json={
            "root": root, "path": SUITE, "content": "x", "expected_sha256": opened["sha256"]}).json()
        assert stale["status"] == "error" and stale["code"] == "conflict"
        check = client.post("/api/test-project/file/check", json={
            "path": "a.robot", "content": "*** Settings ***\nBogus    1\n"}).json()
        assert check["status"] == "ok"
        new = client.post("/api/test-project/suite", json={"root": root, "name": "api2", "service": "hello"}).json()
        assert new["status"] == "ok" and new["path"] == "testsuites/api2.robot"


class Test_ProjectView:

    def _entries(self, tree):
        return {f["path"]: f for f in tree["files"]}

    def test_roles_states_and_kinds(self, project):
        _export(project, apply=True)
        _write(project, "resources/mine.resource", "*** Keywords ***\n")
        tree = tp.project_tree(str(project))
        files = self._entries(tree)
        assert files[tp.MANIFEST_NAME]["role"] == "manifest"
        assert (files[RESOURCE]["role"], files[RESOURCE]["state"], files[RESOURCE]["kind"]) == ("generated", "ok", "resource")
        assert (files[PROTO]["kind"], files[PROTO]["service"]) == ("proto", "hello")
        assert (files[SUITE]["role"], files[SUITE]["kind"]) == ("starter", "suite")
        assert (files["resources/mine.resource"]["role"], files["resources/mine.resource"]["state"]) == ("yours", "yours")
        assert tree["services"][0]["files"] == {"ok": 4, "edited": 0, "missing": 0}
        assert tree["run_hint"] == "python -m robot -d results testsuites"
        assert tree["runner_name"] == "Robot Framework AIO"

    def test_edited_and_missing_generated_files(self, project):
        _export(project, apply=True)
        _write(project, RESOURCE, _read(project, RESOURCE) + "\n# local change\n")
        os.remove(os.path.join(project, *PROTO.split("/")))
        tree = tp.project_tree(str(project))
        files = self._entries(tree)
        assert files[RESOURCE]["state"] == "edited"
        assert files[PROTO]["state"] == "missing"
        assert tree["services"][0]["files"] == {"ok": 2, "edited": 1, "missing": 1}

    def test_generation_date_alone_is_not_an_edit(self, project):
        _export(project, apply=True)
        _write(project, RESOURCE, re.sub(r"(\.\.\.\s+Generated:\s+)\S+", r"\g<1>1999-01-01",
                                         _read(project, RESOURCE)))
        assert self._entries(tp.project_tree(str(project)))[RESOURCE]["state"] == "ok"

    def test_not_a_project(self, tmp_path):
        with pytest.raises(tp.TestProjectError, match="not a test project"):
            tp.project_tree(str(tmp_path))

    def test_read_file(self, project):
        _export(project, apply=True)
        f = tp.read_project_file(str(project), SUITE)
        assert f["path"] == SUITE and f["content"] == _read(project, SUITE)

    def test_read_file_refuses_escape_binary_missing_and_large(self, project, monkeypatch):
        from MicroserviceBase.adapters.test_project import engine
        with pytest.raises(tp.TestProjectError, match="escapes"):
            tp.read_project_file(str(project), "../outside.txt")
        with pytest.raises(tp.TestProjectError, match="No such file"):
            tp.read_project_file(str(project), "nope.robot")
        (project / "blob.bin").write_bytes(b"abc\x00def")
        with pytest.raises(tp.TestProjectError, match="binary"):
            tp.read_project_file(str(project), "blob.bin")
        monkeypatch.setattr(engine, "_PREVIEW_MAX_BYTES", 10)
        with pytest.raises(tp.TestProjectError, match="previews are limited"):
            tp.read_project_file(str(project), tp.MANIFEST_NAME)


class Test_Editing:

    @pytest.fixture
    def exported(self, project):
        _export(project, apply=True)
        _write(project, "resources/mine.resource", "*** Keywords ***\nMine\n    No Operation\n")
        return project

    def test_read_reports_hash_role_and_editability(self, exported):
        root = str(exported)
        assert tp.read_project_file(root, SUITE)["editable"] is True            # starter
        assert tp.read_project_file(root, "resources/mine.resource")["role"] == "yours"
        assert tp.read_project_file(root, RESOURCE)["editable"] is False        # generated
        assert tp.read_project_file(root, tp.MANIFEST_NAME)["editable"] is False
        f = tp.read_project_file(root, SUITE)
        import hashlib
        assert f["sha256"] == hashlib.sha256(open(os.path.join(root, *SUITE.split("/")), "rb").read()).hexdigest()

    def test_save_updates_file_and_hash(self, exported):
        root = str(exported)
        before = tp.read_project_file(root, SUITE)
        new = before["content"].replace("No Operation", "Log    edited")
        saved = tp.write_project_file(root, SUITE, new, expected_sha256=before["sha256"])
        assert saved["problems"] == []
        assert _read(exported, SUITE) == new
        assert saved["sha256"] == tp.read_project_file(root, SUITE)["sha256"] != before["sha256"]
        # the starter stays a starter: exports keep it
        assert _statuses(_export(exported))[SUITE] == "keep"

    def test_concurrent_change_is_a_conflict_unless_forced(self, exported):
        root = str(exported)
        opened = tp.read_project_file(root, SUITE)
        _write(exported, SUITE, opened["content"] + "\n# changed by someone else\n")
        with pytest.raises(tp.TestProjectConflict, match="changed on disk"):
            tp.write_project_file(root, SUITE, "mine\n", expected_sha256=opened["sha256"])
        tp.write_project_file(root, SUITE, "*** Test Cases ***\nMine\n    No Operation\n",
                              expected_sha256=opened["sha256"], force=True)
        assert _read(exported, SUITE).startswith("*** Test Cases ***\nMine")

    def test_generated_files_and_manifest_are_read_only(self, exported):
        root = str(exported)
        with pytest.raises(tp.TestProjectError, match="generated by exports"):
            tp.write_project_file(root, RESOURCE, "x")
        with pytest.raises(tp.TestProjectError, match="maintained by the tool"):
            tp.write_project_file(root, tp.MANIFEST_NAME, "{}")

    def test_save_refuses_escape_missing_and_bad_new_files(self, exported):
        root = str(exported)
        with pytest.raises(tp.TestProjectError, match="escapes"):
            tp.write_project_file(root, "../evil.robot", "x", create=True)
        with pytest.raises(tp.TestProjectError, match="No such file"):
            tp.write_project_file(root, "testsuites/nope.robot", "x")
        with pytest.raises(tp.TestProjectError, match="already exists"):
            tp.write_project_file(root, SUITE, "x", create=True)
        with pytest.raises(tp.TestProjectError, match=r"\.robot or \.resource"):
            tp.write_project_file(root, "testsuites/notes.txt", "x", create=True)

    def test_syntax_problems_are_reported_with_lines(self):
        pytest.importorskip("robot")
        suite = "*** Settings ***\nNot A Setting    x\n\n*** Test Cases ***\nT\n    No Operation\n"
        problems = tp.check_syntax("testsuites/x.robot", suite)
        assert problems and problems[0]["line"] == 2 and "Not A Setting" in problems[0]["message"]
        resource = "*** Test Cases ***\nT\n    No Operation\n"
        assert tp.check_syntax("resources/x.resource", resource)
        assert tp.check_syntax("testsuites/x.robot", "*** Test Cases ***\nT\n    No Operation\n") == []
        assert tp.check_syntax("README.md", "*** anything") == []

    def test_create_suite_wired_to_a_service(self, exported):
        pytest.importorskip("robot")
        created = tp.create_suite(str(exported), "power_checks", service="hello")
        assert created["created"] is True and created["path"] == "testsuites/power_checks.robot"
        assert created["problems"] == []
        text = _read(exported, created["path"])
        assert "Resource          ../resources/hello/hello_service.resource" in text
        assert "    Hello Service Open Connection    hello_service" in text
        assert "${PROTO_DIR}        ${CURDIR}/../proto/hello" in text
        assert "Power Checks Works" in text
        tree = {f["path"]: f for f in tp.project_tree(str(exported))["files"]}
        assert tree[created["path"]]["role"] == "yours"

    def test_create_suite_without_service_and_bad_input(self, exported):
        root = str(exported)
        plain = tp.create_suite(root, "smoke-2.robot")
        assert plain["path"] == "testsuites/smoke-2.robot"
        assert "testsuites.testsuite_setup" in _read(exported, plain["path"])
        with pytest.raises(tp.TestProjectError, match="already exists"):
            tp.create_suite(root, "smoke-2")
        with pytest.raises(tp.TestProjectError, match="Invalid suite name"):
            tp.create_suite(root, "has space")
        with pytest.raises(tp.TestProjectError, match="has not been exported"):
            tp.create_suite(root, "x", service="other")
