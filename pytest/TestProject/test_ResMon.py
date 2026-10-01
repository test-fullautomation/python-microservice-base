"""
Tests for the resource monitor of test runs (``adapters/test_project/resmon.py``)
and its use by the run manager: every run records RAM / CPU of its processes
and leaves ``resources.html`` with a verdict per process.
"""

import json
import os
import subprocess
import sys
import time

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from MicroserviceBase.adapters import test_project as tp  # noqa: E402
from MicroserviceBase.adapters.test_project import resmon  # noqa: E402

psutil = pytest.importorskip("psutil")

STEADY = "import time; x = bytearray(20 * 2**20); time.sleep(6)"
LEAKY = "import time\nkeep = []\nfor i in range(60):\n    keep.append(bytearray(2 * 2**20)); time.sleep(0.1)\n"


def _record(tmp_path, **procs):
    started = {k: subprocess.Popen([sys.executable, "-c", code]) for k, code in procs.items()}
    out, report = tmp_path / "r.jsonl", tmp_path / "r.html"
    argv = ["record", "--out", str(out), "--report", str(report), "--interval", "0.2",
            "--min-steady", "2s", "--title", "unit"]
    for label, proc in started.items():
        argv += ["--pid", f"{label}={proc.pid}"]
    assert resmon.main(argv) == 0
    for proc in started.values():
        proc.wait(timeout=30)
    return out, report


class Test_Monitor:

    def test_records_until_the_processes_end_and_judges_them(self, tmp_path):
        out, report = _record(tmp_path, steady=STEADY, leaky=LEAKY)
        meta, samples, exits, end = resmon.load(str(out))
        assert meta["processes"].keys() == {"steady", "leaky"} and meta["interval"] == 0.2
        assert len(samples) > 10 and set(exits) == {"steady", "leaky"}
        assert end["reason"] == "all processes ended"
        first = samples[0]["p"]["steady"]
        assert {"rss", "priv", "cpu", "thr", "h", "n"} <= set(first) and first["priv"] > 15
        res = resmon.analyse(meta, samples, min_steady=2)
        assert res["steady"]["verdict"] == "STABLE", res["steady"]["why"]
        assert res["leaky"]["verdict"] == "GROWING", res["leaky"]["why"]
        assert res["leaky"]["priv"]["growth_mb"] > 50
        page = report.read_text(encoding="utf-8")
        assert "v-GROWING" in page and "v-STABLE" in page
        # The chart's data, for the page's own script: every sample, per process.
        data = json.loads(page.split('<script type="application/json" id="rm-data">')[1].split('</script>')[0])
        assert len(data["t"]) == len(samples) and {p["label"] for p in data["procs"]} == {"steady", "leaky"}
        assert all(len(p[k]) == len(samples) for p in data["procs"] for k in ("priv", "rss", "cpu", "thr", "h"))

    def test_report_again_from_the_data(self, tmp_path):
        out, _ = _record(tmp_path, steady=STEADY)
        again = tmp_path / "again.html"
        assert resmon.main(["report", str(out), "-o", str(again), "--min-steady", "2s"]) == 0
        assert "v-STABLE" in again.read_text(encoding="utf-8")
        # Without enough time after the warm-up: no verdict either way.
        assert resmon.main(["report", str(out), "-o", str(again)]) == 0
        assert "v-SHORT" in again.read_text(encoding="utf-8")

    def test_a_line_cut_by_a_crash_is_skipped(self, tmp_path):
        out, _ = _record(tmp_path, steady=STEADY)
        with open(out, "a", encoding="utf-8") as fh:
            fh.write('{"t": 1, "p": {"steady": {"rss"')
        meta, samples, _, _ = resmon.load(str(out))
        assert samples and all("p" in s for s in samples)

    def test_trend_ignores_the_warm_up(self):
        meta = {"started": 0}
        # A warm-up climbing to 100 MB in 500 s (inside the 10 min left out), then flat.
        samples = [{"t": t, "p": {"a": {"rss": v, "priv": v, "cpu": 1, "thr": 5, "h": 50}}}
                   for t in range(0, 10000, 10) for v in [min(100.0, t / 5)]]
        res = resmon.analyse(meta, samples)["a"]
        assert res["verdict"] == "STABLE" and abs(res["priv"]["slope_mb_h"]) < 1, res


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "bench_tests"
    root.mkdir()
    tp.init_project(str(root), "robotframework-aio")
    path = root / "testsuites" / "wait.robot"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("*** Test Cases ***\nWaits\n    Sleep    2s\n", encoding="utf-8")
    return root


def _wait(root, run_id, timeout=90):
    deadline = time.time() + timeout
    while time.time() < deadline:
        st = tp.RUNS.status(str(root), run_id)
        if st["run_state"] == "done":
            return st
        time.sleep(0.2)
    raise AssertionError(f"run {run_id} did not finish")


class Test_RunResources:

    def test_off_unless_the_run_asks(self, project):
        st = _wait(project, tp.RUNS.start(str(project), "testsuites/wait.robot")["id"])
        assert st["verdict"] == "pass" and st["options"]["resources"] is False
        assert not any(a["name"] == "resources.html" for a in st["artifacts"])
        assert not (project / "results" / st["id"] / "resources.jsonl").exists()

    def test_a_run_that_asks_records_its_resources(self, project):
        tp.set_run_settings(str(project), {"env": {"MM_RESMON_INTERVAL": "0.3"}})
        st = _wait(project, tp.RUNS.start(str(project), "testsuites/wait.robot", resources=True)["id"])
        assert st["verdict"] == "pass" and st["options"]["resources"] is True
        assert {"name": "resources.html", "label": "Resources", "primary": False} in st["artifacts"]
        out_dir = project / "results" / st["id"]
        meta = json.loads((out_dir / "resources.jsonl").read_text(encoding="utf-8").splitlines()[0])
        assert list(meta["processes"]) == ["wait"] and meta["interval"] == 0.3
        assert tp.RUNS.artifact_path(str(project), st["id"], "resources.html").endswith("resources.html")

    def test_not_for_a_dry_run(self, project):
        st = _wait(project, tp.RUNS.start(str(project), "testsuites/wait.robot", dryrun=True, resources=True)["id"])
        assert st["options"]["resources"] is False
        assert not (project / "results" / st["id"] / "resources.jsonl").exists()
