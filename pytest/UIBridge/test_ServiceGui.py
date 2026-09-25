"""
Tests for service-delivered GUI folders over gRPC.

The service side packages its GUI folder (``runtime/gui_server.py``), the
bridge side fetches and extracts it (``adapters/ui_bridge/service_gui.py``),
and the two agree through one descriptor (``runtime/gui_proto.py``). The
tests run a real gRPC server on a loopback port, so the contract is
exercised end to end rather than mocked.
"""

import os
import sys
import zipfile
from concurrent import futures

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__)))))

grpc = pytest.importorskip("grpc")

from MicroserviceBase.adapters.ui_bridge import service_gui  # noqa: E402
from MicroserviceBase.runtime import gui_proto, gui_server  # noqa: E402


def _write(root, rel, text):
    path = os.path.join(root, rel.replace("/", os.sep))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


@pytest.fixture
def gui_dir(tmp_path):
    root = tmp_path / "gui" / "DemoService1.0.0"
    root.mkdir(parents=True)
    _write(str(root), "component.json", '{"component": "bits.demo"}')
    _write(str(root), "DemoService.html", "<p>panel</p>")
    _write(str(root), "assets/style.css", "body { color: red }")
    return str(root)


@pytest.fixture
def served(gui_dir):
    """A gRPC server serving *gui_dir* as folder DemoService1.0.0."""
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=8))
    package = gui_server.add_service_gui(server, gui_dir, "DemoService1.0.0")
    port = server.add_insecure_port("127.0.0.1:0")
    server.start()
    yield package, "127.0.0.1", port
    server.stop(0)


class Test_Package:

    def test_skips_caches_and_build_droppings(self, gui_dir):
        _write(gui_dir, "__pycache__/panel.cpython-313.pyc", "x")
        _write(gui_dir, "panel.log", "noise")
        package = gui_server.GuiPackage(gui_dir, "DemoService1.0.0")
        _checksum, blob, count = package.package()
        names = zipfile.ZipFile(__import__("io").BytesIO(blob)).namelist()
        assert count == 3
        assert sorted(names) == ["DemoService.html", "assets/style.css", "component.json"]

    def test_checksum_is_stable_across_calls(self, gui_dir):
        package = gui_server.GuiPackage(gui_dir, "DemoService1.0.0")
        assert package.package()[0] == package.package()[0]

    def test_checksum_follows_the_content(self, gui_dir):
        package = gui_server.GuiPackage(gui_dir, "DemoService1.0.0")
        before = package.package()[0]
        _write(gui_dir, "DemoService.html", "<p>changed</p>")
        os.utime(os.path.join(gui_dir, "DemoService.html"), (0, 0))   # force a new signature
        assert package.package()[0] != before

    def test_an_empty_folder_offers_nothing(self, tmp_path):
        package = gui_server.GuiPackage(str(tmp_path / "nope"), "X1.0.0")
        assert package.exists() is False


class Test_OverGrpc:

    def test_info_describes_the_folder(self, served):
        _package, host, port = served
        info = service_gui.gui_info(host, port)
        assert info["available"] is True
        assert info["folder"] == "DemoService1.0.0"
        assert info["file_count"] == 3
        assert info["checksum"] and info["size_bytes"] > 0

    def test_fetch_returns_a_usable_zip(self, served):
        _package, host, port = served
        blob, checksum = service_gui.fetch_gui_zip(host, port)
        assert checksum
        names = zipfile.ZipFile(__import__("io").BytesIO(blob)).namelist()
        assert "component.json" in names and "assets/style.css" in names

    def test_a_current_caller_downloads_nothing(self, served):
        _package, host, port = served
        checksum = service_gui.gui_info(host, port)["checksum"]
        blob, echoed = service_gui.fetch_gui_zip(host, port, known_checksum=checksum)
        assert blob is None
        assert echoed == checksum

    def test_a_stale_checksum_downloads_again(self, served):
        _package, host, port = served
        blob, _ = service_gui.fetch_gui_zip(host, port, known_checksum="stale")
        assert blob

    def test_large_packages_arrive_in_chunks(self, tmp_path):
        # Two chunks' worth of incompressible data, to exercise the stream.
        root = tmp_path / "BigService1.0.0"
        root.mkdir()
        with open(root / "blob.bin", "wb") as fh:
            fh.write(os.urandom(gui_proto.CHUNK_BYTES * 2 + 1024))
        server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
        gui_server.add_service_gui(server, str(root), "BigService1.0.0")
        port = server.add_insecure_port("127.0.0.1:0")
        server.start()
        try:
            blob, _ = service_gui.fetch_gui_zip("127.0.0.1", port)
            assert len(blob) > gui_proto.CHUNK_BYTES   # more than one chunk
            assert zipfile.ZipFile(__import__("io").BytesIO(blob)).namelist() == ["blob.bin"]
        finally:
            server.stop(0)

    def test_a_service_without_the_contract_says_so(self):
        server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
        port = server.add_insecure_port("127.0.0.1:0")
        server.start()
        try:
            with pytest.raises(service_gui.ServiceGuiError) as exc:
                service_gui.gui_info("127.0.0.1", port)
            assert "does not offer its GUI" in str(exc.value)
            # An ordinary answer, not a fault: the GUI words it differently.
            assert exc.value.unavailable is True
            with pytest.raises(service_gui.ServiceGuiError) as exc:
                service_gui.fetch_gui_zip("127.0.0.1", port)
            assert exc.value.unavailable is True
        finally:
            server.stop(0)

    def test_an_unreachable_service_is_a_fault_not_unavailable(self):
        with pytest.raises(service_gui.ServiceGuiError) as exc:
            service_gui.gui_info("127.0.0.1", 1, timeout=1)
        assert exc.value.unavailable is False

    def test_served_from_the_async_server_servicerunner_uses(self, gui_dir):
        import asyncio

        async def run():
            server = grpc.aio.server()
            gui_server.add_service_gui(server, gui_dir, "DemoService1.0.0")
            port = server.add_insecure_port("127.0.0.1:0")
            await server.start()
            try:
                info = await asyncio.to_thread(service_gui.gui_info, "127.0.0.1", port)
                blob, _ = await asyncio.to_thread(service_gui.fetch_gui_zip, "127.0.0.1", port)
                return info, blob
            finally:
                await server.stop(0)

        info, blob = asyncio.run(run())
        assert info["available"] and info["file_count"] == 3
        assert zipfile.ZipFile(__import__("io").BytesIO(blob)).namelist()


class Test_ServiceRunner:
    """The real runtime: ServiceRunner.start() (no Consul -- that is serve_forever)."""

    @staticmethod
    def _start(gui_dir, check):
        import asyncio

        from MicroserviceBase.runtime.server import ServiceRunner
        from MicroserviceBase.runtime.settings import BaseServiceSettings

        async def run():
            settings = BaseServiceSettings(service_name="gui-runner-test", service_host="127.0.0.1",
                                           grpc_port=0, gui="DemoService1.0.0", gui_dir=gui_dir)
            runner = ServiceRunner(servicers=[], settings=settings)
            port = await runner.start()
            try:
                return await asyncio.to_thread(check, port)
            finally:
                await runner._server.stop(0)
        return asyncio.run(run())

    def test_serves_the_gui_folder(self, gui_dir):
        info = self._start(gui_dir, lambda port: service_gui.gui_info("127.0.0.1", port))
        assert info["available"] and info["folder"] == "DemoService1.0.0"

    def test_every_service_reflection_lists_can_be_described(self, gui_dir):
        # ServiceGui lives in a private descriptor pool: listing it in
        # reflection would make it undescribable, and a client walking the
        # list (the GUI's actions view) would fail on it.
        from grpc_reflection.v1alpha import reflection_pb2, reflection_pb2_grpc

        def check(port):
            with grpc.insecure_channel(f"127.0.0.1:{port}") as ch:
                stub = reflection_pb2_grpc.ServerReflectionStub(ch)

                def ask(req):
                    return next(iter(stub.ServerReflectionInfo(iter([req]), timeout=10)))
                listed = [s.name for s in ask(reflection_pb2.ServerReflectionRequest(
                    list_services="")).list_services_response.service]
                kinds = {n: ask(reflection_pb2.ServerReflectionRequest(
                    file_containing_symbol=n)).WhichOneof("message_response") for n in listed}
            return listed, kinds

        listed, kinds = self._start(gui_dir, check)
        assert gui_proto.FULL_SERVICE_NAME not in listed
        assert all(k == "file_descriptor_response" for k in kinds.values()), kinds


class Test_Extract:

    def test_files_land_in_the_named_folder(self, served, tmp_path):
        _package, host, port = served
        blob, _ = service_gui.fetch_gui_zip(host, port)
        count = service_gui.extract_package(blob, "DemoService1.0.0", str(tmp_path))
        target = tmp_path / "DemoService1.0.0"
        assert count == 3
        assert (target / "component.json").read_text(encoding="utf-8") == '{"component": "bits.demo"}'
        assert (target / "assets" / "style.css").exists()

    def test_a_second_fetch_overwrites_in_place(self, served, tmp_path):
        _package, host, port = served
        blob, _ = service_gui.fetch_gui_zip(host, port)
        service_gui.extract_package(blob, "DemoService1.0.0", str(tmp_path))
        service_gui.extract_package(blob, "DemoService1.0.0", str(tmp_path))
        assert (tmp_path / "DemoService1.0.0" / "component.json").exists()

    def test_folder_names_that_escape_are_refused(self, served, tmp_path):
        _package, host, port = served
        blob, _ = service_gui.fetch_gui_zip(host, port)
        for bad in ("../evil", "a/b", "..", "/abs"):
            with pytest.raises(service_gui.ServiceGuiError):
                service_gui.extract_package(blob, bad, str(tmp_path))

    def test_zip_slip_members_are_refused(self, tmp_path):
        import io
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("../escaped.txt", "nope")
        with pytest.raises(service_gui.ServiceGuiError) as exc:
            service_gui.extract_package(buf.getvalue(), "Demo1.0.0", str(tmp_path))
        assert "outside the folder" in str(exc.value)
        assert not (tmp_path.parent / "escaped.txt").exists()

    def test_garbage_is_not_unpacked(self, tmp_path):
        with pytest.raises(service_gui.ServiceGuiError):
            service_gui.extract_package(b"not a zip at all", "Demo1.0.0", str(tmp_path))

    def test_services_dir_honours_the_env_override(self, monkeypatch, tmp_path):
        monkeypatch.setenv(service_gui.SERVICES_DIR_ENV, str(tmp_path))
        assert service_gui.services_dir() == str(tmp_path)
