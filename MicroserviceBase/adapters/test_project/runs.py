"""Running a test project's tests -- runner-neutral.

The runner adapter plans the process (:meth:`TestProjectRunner.run_plan`)
and reads what it left behind (:meth:`TestProjectRunner.read_results`);
this module does everything in between, the same for every runner:

* one folder per run, ``<project>/results/<run id>/``, holding the
  runner's own output, ``console.log`` and ``run.json`` (what was run,
  when, and the outcome) -- so the history survives a bridge restart;
* the console output of live runs, kept in memory for polling with a
  cursor;
* stopping: first politely (the plan's ``stop_file``), then by force.

One run per project at a time: two runs against one bench would fight
over it.
"""

from __future__ import annotations

import collections
import datetime as _dt
import json
import os
import re
import subprocess
import sys
import threading
import time
from dataclasses import asdict
from typing import Dict, List, Optional, Tuple

from ...ports.test_project import RunOptions, TestProjectError
from .engine import _abs_root, _layout, _load_manifest, _safe_join, get_runner, run_settings_of

RESULTS_DIR = "results"
RUN_FILE = "run.json"
CONSOLE_FILE = "console.log"
STOP_GRACE_S = 30.0
_MAX_LINES = 5000
_MAX_BATCH = 2000
_RUN_ID_RE = re.compile(r"^\d{8}-\d{6}(?:-\d+)?_[A-Za-z0-9._-]+$")
_ARTIFACT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _now() -> str:
    return _dt.datetime.now().replace(microsecond=0).isoformat()


def _stem(target: str) -> str:
    base = os.path.basename(target.rstrip("/")) if target else "project"
    for suffix in (".flow.json", ".robot", ".json"):
        if base.lower().endswith(suffix):
            base = base[: -len(suffix)]
            break
    return re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("_") or "run"


class _Run:
    def __init__(self, root: str, run_id: str, out_dir: str, record: dict) -> None:
        self.root = root
        self.id = run_id
        self.out_dir = out_dir
        self.record = record
        self.lines: collections.deque = collections.deque(maxlen=_MAX_LINES)
        self.total = 0
        self.proc: Optional[subprocess.Popen] = None
        self.stop_file = ""
        self.stop_requested = False
        self.lock = threading.Lock()


class RunManager:
    """Live runs of every project, keyed by ``(root, run id)``."""

    def __init__(self) -> None:
        self._runs: Dict[Tuple[str, str], _Run] = {}
        self._lock = threading.Lock()

    # ---- start -----------------------------------------------------------

    def start(self, root: str, target: str = "", *, variables: Optional[dict] = None,
              dryrun: bool = False) -> dict:
        root = _abs_root(root)
        manifest = _load_manifest(root)
        if manifest is None:
            raise TestProjectError(f"{root} is not a test project.")
        runner = get_runner(manifest["runner"])
        layout = _layout(runner, manifest)
        target = str(target or "").replace("\\", "/").strip("/")
        if target:
            _safe_join(root, target)
        if not runner.can_run(target):
            raise TestProjectError(
                f"{runner.display_name} cannot run {target or 'this project'}.")

        with self._lock:
            live = [r for (r_root, _), r in self._runs.items()
                    if r_root == root and r.record["state"] in ("running", "stopping")]
            if live:
                raise TestProjectError(
                    f"A run is already in progress in this project ({live[0].record['target_label']}). "
                    "Stop it or wait for it to finish.")
            run_id = self._new_id(root, target)
            out_dir = os.path.join(root, RESULTS_DIR, run_id)
            os.makedirs(out_dir)

        options = RunOptions(variables={str(k): str(v) for k, v in (variables or {}).items()},
                             dryrun=bool(dryrun))
        settings = run_settings_of(manifest)
        plan = runner.run_plan(root, layout, target, settings, options, out_dir)

        record = {
            "id": run_id,
            "target": target,
            "target_label": target or f"{layout.get('suites', 'all suites')} (all)",
            "runner": runner.runner_id,
            "runner_name": runner.display_name,
            "options": asdict(options),
            "argv": plan.argv,
            "started_at": _now(),
            "started_ts": time.time(),
            "ended_at": "",
            "elapsed_s": 0.0,
            "state": "running",
            "returncode": None,
            "verdict": "",
            "counts": {},
            "message": "",
            "tests": [],
            "artifacts": [asdict(a) for a in plan.artifacts],
        }
        run = _Run(root, run_id, out_dir, record)
        run.stop_file = plan.stop_file

        env = dict(os.environ)
        for key, value in plan.env.items():
            if value is None:
                env.pop(key, None)
            else:
                env[key] = value
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
        try:
            run.proc = subprocess.Popen(
                plan.argv, cwd=plan.cwd, env=env,
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", bufsize=1,
                creationflags=flags,
            )
        except OSError as exc:
            record.update(state="done", verdict="error", ended_at=_now(),
                          message=f"Could not start {plan.argv[0]}: {exc}")
            self._save(run)
            raise TestProjectError(record["message"]) from exc

        with self._lock:
            self._runs[(root, run_id)] = run
        self._save(run)
        threading.Thread(target=self._pump, args=(run, runner), name=f"run-{run_id}",
                         daemon=True).start()
        return self._public(run)

    @staticmethod
    def _new_id(root: str, target: str) -> str:
        stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        base = f"{stamp}_{_stem(target)}"
        run_id, n = base, 1
        while os.path.exists(os.path.join(root, RESULTS_DIR, run_id)):
            n += 1
            run_id = f"{stamp}-{n}_{_stem(target)}"
        return run_id

    # ---- the process -----------------------------------------------------

    def _pump(self, run: _Run, runner) -> None:
        console = open(os.path.join(run.out_dir, CONSOLE_FILE), "w", encoding="utf-8")
        try:
            for line in run.proc.stdout:
                line = line.rstrip("\r\n")
                with run.lock:
                    run.lines.append(line)
                    run.total += 1
                console.write(line + "\n")
                console.flush()
        finally:
            console.close()
        returncode = run.proc.wait()
        try:
            result = runner.read_results(run.out_dir, None if run.stop_requested else returncode)
            outcome = {"verdict": result.verdict, "counts": result.counts,
                       "tests": result.tests, "message": result.message}
        except Exception as exc:   # noqa: BLE001 -- never leave a run "running"
            outcome = {"verdict": "error", "counts": {}, "tests": [],
                       "message": f"The results could not be read: {exc}"}
        with run.lock:
            run.record.update(outcome, state="done", returncode=returncode, ended_at=_now(),
                              elapsed_s=round(time.time() - run.record["started_ts"], 1))
        if run.stop_file:
            try:
                os.remove(run.stop_file)
            except OSError:
                pass
        self._save(run)

    def _save(self, run: _Run) -> None:
        with run.lock:
            data = dict(run.record)
        try:
            with open(os.path.join(run.out_dir, RUN_FILE), "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2, ensure_ascii=False)
        except OSError:
            pass

    # ---- status / stop ---------------------------------------------------

    def status(self, root: str, run_id: str, since: int = 0) -> dict:
        root = _abs_root(root)
        run = self._runs.get((root, run_id))
        if run is None:
            return self._stored(root, run_id, since)
        with run.lock:
            first = run.total - len(run.lines)
            start = max(int(since or 0), first)
            batch = list(run.lines)[start - first:start - first + _MAX_BATCH]
            out = self._public(run)
            out.update(lines=batch, next=start + len(batch), dropped=max(0, first - int(since or 0)))
        return out

    def _stored(self, root: str, run_id: str, since: int) -> dict:
        record = self._read_record(root, run_id)
        lines: List[str] = []
        path = os.path.join(root, RESULTS_DIR, run_id, CONSOLE_FILE)
        if os.path.isfile(path):
            with open(path, encoding="utf-8", errors="replace") as fh:
                lines = fh.read().splitlines()
        start = max(0, int(since or 0))
        if record.get("state") in ("running", "stopping"):
            # Run by a bridge that is gone: nobody is watching it any more.
            record.update(state="done", verdict=record.get("verdict") or "error",
                          message=record.get("message") or "The bridge restarted during this run.")
        out = self._public_record(record)
        out.update(lines=lines[start:start + _MAX_BATCH], next=min(len(lines), start + _MAX_BATCH),
                   dropped=0)
        return out

    def stop(self, root: str, run_id: str, *, force: bool = False) -> dict:
        root = _abs_root(root)
        run = self._runs.get((root, run_id))
        if run is None or run.record["state"] == "done":
            raise TestProjectError("That run is not running.")
        proc = run.proc
        if force or not run.stop_file or run.stop_requested:
            self._kill(proc)
            with run.lock:
                run.stop_requested = True
                run.record["state"] = "stopping"
            return self._public(run)
        with run.lock:
            run.stop_requested = True
            run.record["state"] = "stopping"
        try:
            with open(run.stop_file, "w", encoding="utf-8") as fh:
                fh.write(_now())
        except OSError:
            self._kill(proc)
            return self._public(run)

        def later():
            try:
                proc.wait(timeout=STOP_GRACE_S)
            except subprocess.TimeoutExpired:
                self._kill(proc)
        threading.Thread(target=later, daemon=True).start()
        return self._public(run)

    @staticmethod
    def _kill(proc: subprocess.Popen) -> None:
        if proc.poll() is not None:
            return
        if sys.platform == "win32":
            # The run may have started children of its own (libraries,
            # helper tools); take the whole tree.
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if proc.poll() is None:
            proc.kill()

    # ---- history ---------------------------------------------------------

    def list(self, root: str, limit: int = 30) -> dict:
        root = _abs_root(root)
        if _load_manifest(root) is None:
            raise TestProjectError(f"{root} is not a test project.")
        base = os.path.join(root, RESULTS_DIR)
        found = []
        if os.path.isdir(base):
            for d in os.listdir(base):
                path = os.path.join(base, d, RUN_FILE)
                if _RUN_ID_RE.match(d) and os.path.isfile(path):
                    # Ids have one-second resolution; the recorded start
                    # orders runs started within the same second.
                    try:
                        with open(path, encoding="utf-8") as fh:
                            started = float(json.load(fh).get("started_ts") or 0)
                    except (OSError, ValueError, TypeError, AttributeError):
                        started = 0.0
                    found.append((d[:15], started, d))
        ids = [entry[-1] for entry in sorted(found, reverse=True)][: max(1, int(limit))]
        runs = []
        for run_id in ids:
            live = self._runs.get((root, run_id))
            if live is not None:
                item = self._public(live)
            else:
                item = self._stored(root, run_id, 10 ** 9)
                item.pop("lines", None)
                item.pop("next", None)
                item.pop("dropped", None)
            item.pop("tests", None)
            runs.append(item)
        return {"status": "ok", "root": root, "runs": runs}

    def _read_record(self, root: str, run_id: str) -> dict:
        if not _RUN_ID_RE.match(str(run_id)):
            raise TestProjectError(f"Invalid run id {run_id!r}.")
        path = os.path.join(root, RESULTS_DIR, run_id, RUN_FILE)
        try:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            raise TestProjectError(f"No run {run_id} in this project.") from None

    # ---- files -----------------------------------------------------------

    def artifact_path(self, root: str, run_id: str, name: str) -> str:
        """Absolute path of a file a run left behind, checked to stay inside it."""
        root = _abs_root(root)
        if _load_manifest(root) is None:
            raise TestProjectError(f"{root} is not a test project.")
        if not _RUN_ID_RE.match(str(run_id)) or not _ARTIFACT_RE.match(str(name)):
            raise TestProjectError("Invalid run file.")
        path = os.path.join(root, RESULTS_DIR, run_id, name)
        if not os.path.isfile(path):
            raise TestProjectError(f"{name} does not exist for run {run_id}.")
        return path

    # ---- shapes ----------------------------------------------------------

    def _public(self, run: _Run) -> dict:
        record = dict(run.record)
        if record["state"] != "done":
            record["elapsed_s"] = round(time.time() - record["started_ts"], 1)
        return self._public_record(record)

    @staticmethod
    def _public_record(record: dict) -> dict:
        out = {k: v for k, v in record.items() if k != "started_ts"}
        out["status"] = "ok"
        out["run_state"] = out.pop("state", "done")
        return out


RUNS = RunManager()
