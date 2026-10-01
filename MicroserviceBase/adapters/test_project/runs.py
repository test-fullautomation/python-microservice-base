"""Running a test project's tests -- runner-neutral.

The runner adapter plans the process (:meth:`TestProjectRunner.run_plan`)
and reads what it left behind (:meth:`TestProjectRunner.read_results`);
this module does everything in between, the same for every runner:

* one folder per run, ``<project>/results/<run id>/``, holding the
  runner's own output, ``console.log`` and ``run.json`` (what was run,
  when, and the outcome) -- so the history survives a bridge restart;
* the console output of live runs, kept in memory for polling with a
  cursor;
* stopping: first politely (the plan's ``stop_file``), then by force;
* the run's resources, when the run asks for them (``resources``): a
  separate process (``resmon.py``) samples RAM and CPU of every process of
  the run into ``resources.jsonl`` and, when they have ended, writes
  ``resources.html`` -- a long run's proof that the runner stays flat.
  ``MM_RESMON_INTERVAL`` in the run settings' environment sets the seconds
  between samples (default 5).

One run per project at a time: two runs against one bench would fight
over it. A *group* run is one run of several processes started together
(:class:`~MicroserviceBase.ports.test_project.RunGroup`): each member gets
its own folder, ``<run id>/<member>/``, the console interleaves their
lines tagged ``[member]``, and the run's verdict combines theirs.
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

from ...ports.test_project import POSITION_FILE, RunOptions, TestProjectError
from .engine import (_abs_root, _layout, _load_manifest, _safe_join, find_group, get_runner,
                     run_settings_of)

RESULTS_DIR = "results"
RUN_FILE = "run.json"
CONSOLE_FILE = "console.log"
RESOURCES_DATA = "resources.jsonl"
RESOURCES_REPORT = "resources.html"
_RESMON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resmon.py")
RESMON_INTERVAL_S = 5.0
STOP_GRACE_S = 30.0
_MAX_LINES = 5000
_MAX_BATCH = 2000
_RUN_ID_RE = re.compile(r"^\d{8}-\d{6}(?:-\d+)?_[A-Za-z0-9._-]+$")
_ARTIFACT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_MEMBER_LINE_RE = re.compile(r"^\[([A-Za-z0-9_-]+)\] ?(.*)$")
# The run's verdict from its members': a broken process first, then a
# failure, then "nothing was tested".
_VERDICT_ORDER = ("error", "fail", "unknown", "pass", "skip")


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
        # Members of a group run finish on their own threads; one writer of
        # run.json at a time.
        self.save_lock = threading.Lock()
        # Group runs: one _Member per process; tags[i] is the member index
        # of lines[i].
        self.members: List["_Member"] = []
        self.tags: collections.deque = collections.deque(maxlen=_MAX_LINES)
        self.console = None
        self.monitor: Optional[subprocess.Popen] = None
        self.monitor_interval = 0.0


class _Member:
    def __init__(self, index: int, member_id: str, out_dir: str, record: dict) -> None:
        self.index = index
        self.id = member_id
        self.out_dir = out_dir
        self.record = record
        self.proc: Optional[subprocess.Popen] = None
        self.stop_file = ""


class RunManager:
    """Live runs of every project, keyed by ``(root, run id)``."""

    def __init__(self) -> None:
        self._runs: Dict[Tuple[str, str], _Run] = {}
        self._lock = threading.Lock()

    # ---- start -----------------------------------------------------------

    def start(self, root: str, target: str = "", *, variables: Optional[dict] = None,
              dryrun: bool = False, resources: bool = False) -> dict:
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

        run_id, out_dir = self._reserve(root, target)

        options = RunOptions(variables={str(k): str(v) for k, v in (variables or {}).items()},
                             dryrun=bool(dryrun), resources=bool(resources) and not dryrun)
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

        try:
            run.proc = self._spawn(plan.argv, plan.cwd, self._merged_env(plan.env))
        except OSError as exc:
            record.update(state="done", verdict="error", ended_at=_now(),
                          message=f"Could not start {plan.argv[0]}: {exc}")
            self._save(run)
            raise TestProjectError(record["message"]) from exc

        with self._lock:
            self._runs[(root, run_id)] = run
        if options.resources:
            self._start_monitor(run, {_stem(target) or "robot": run.proc.pid}, settings.env)
        self._save(run)
        threading.Thread(target=self._pump, args=(run, runner), name=f"run-{run_id}",
                         daemon=True).start()
        return self._public(run)

    def _reserve(self, root: str, target: str) -> Tuple[str, str]:
        """A new run folder -- unless the project already has a run going."""
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
        return run_id, out_dir

    @staticmethod
    def _merged_env(*changes: dict) -> dict:
        env = dict(os.environ)
        for change in changes:
            for key, value in change.items():
                if value is None:
                    env.pop(key, None)
                else:
                    env[key] = value
        return env

    @staticmethod
    def _spawn(argv, cwd, env) -> subprocess.Popen:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
        return subprocess.Popen(
            argv, cwd=cwd, env=env,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
            creationflags=flags,
        )

    # ---- group runs --------------------------------------------------------

    def start_group(self, root: str, group_id: str, *, dryrun: bool = False,
                    resources: bool = False) -> dict:
        """Start every member of a run group at once."""
        root = _abs_root(root)
        manifest = _load_manifest(root)
        if manifest is None:
            raise TestProjectError(f"{root} is not a test project.")
        runner = get_runner(manifest["runner"])
        layout = _layout(runner, manifest)
        group = find_group(manifest, group_id)
        if len(group.members) < 2:
            raise TestProjectError(f"Run group {group.id!r} needs at least two members.")
        for m in group.members:
            _safe_join(root, m.target)
            if not runner.can_run(m.target):
                raise TestProjectError(f"{runner.display_name} cannot run {m.target} (member {m.id}).")

        run_id, out_dir = self._reserve(root, group.id)
        settings = run_settings_of(manifest)
        # The runner's defaults for a group run, unless the run settings or
        # the group's own environment say otherwise.
        shared = {k: v for k, v in runner.group_env(out_dir).items() if k not in (settings.env or {})}
        shared.update({k: v.replace("${RUN_DIR}", out_dir).replace("${PROJECT_DIR}", root)
                       for k, v in group.env.items()})
        members: List[_Member] = []
        plans = []
        try:
            for i, m in enumerate(group.members):
                m_dir = os.path.join(out_dir, m.id)
                os.makedirs(m_dir)
                options = RunOptions(variables=dict(m.variables), dryrun=bool(dryrun))
                plan = runner.run_plan(root, layout, m.target, settings, options, m_dir)
                plans.append(plan)
                members.append(_Member(i, m.id, m_dir, {
                    "id": m.id, "target": m.target, "variables": dict(m.variables),
                    "argv": plan.argv, "state": "running", "returncode": None,
                    "verdict": "", "counts": {}, "message": "", "tests": [], "elapsed_s": 0.0,
                    "artifacts": [asdict(a) for a in plan.artifacts]}))
        except TestProjectError as exc:
            self._abandon(out_dir, run_id, group, str(exc))
            raise

        record = {
            "id": run_id,
            "group": group.id,
            "target": "",
            "target_label": group.title or group.id,
            "runner": runner.runner_id,
            "runner_name": runner.display_name,
            "options": {"variables": {}, "dryrun": bool(dryrun), "resources": bool(resources) and not dryrun},
            "argv": [],
            "env": dict(group.env),
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
            "artifacts": [],
            "members": [m.record for m in members],
        }
        run = _Run(root, run_id, out_dir, record)
        run.members = members
        run.console = open(os.path.join(out_dir, CONSOLE_FILE), "w", encoding="utf-8")
        started = []
        for member, plan in zip(members, plans):
            member.stop_file = plan.stop_file
            try:
                member.proc = self._spawn(plan.argv, plan.cwd, self._merged_env(plan.env, shared))
                started.append(member)
            except OSError as exc:
                for other in started:
                    self._kill(other.proc)
                for other in members:
                    other.record.update(state="done", verdict=other.record["verdict"] or "error")
                member.record["message"] = f"Could not start {plan.argv[0]}: {exc}"
                record.update(state="done", verdict="error", ended_at=_now(),
                              message=f"{member.id}: {member.record['message']}")
                run.console.close()
                run.console = None
                self._save(run)
                raise TestProjectError(record["message"]) from exc

        with self._lock:
            self._runs[(root, run_id)] = run
        if resources and not dryrun:
            self._start_monitor(run, {m.id: m.proc.pid for m in members}, settings.env)
        self._save(run)
        for member in members:
            threading.Thread(target=self._pump_member, args=(run, member, runner),
                             name=f"run-{run_id}-{member.id}", daemon=True).start()
        return self._public(run)

    @staticmethod
    def _abandon(out_dir: str, run_id: str, group, message: str) -> None:
        """Record a group run that could not be planned, so the folder explains itself."""
        record = {"id": run_id, "group": group.id, "target": "", "target_label": group.title or group.id,
                  "started_at": _now(), "started_ts": time.time(), "ended_at": _now(),
                  "state": "done", "verdict": "error", "message": message, "members": []}
        try:
            with open(os.path.join(out_dir, RUN_FILE), "w", encoding="utf-8") as fh:
                json.dump(record, fh, indent=2, ensure_ascii=False)
        except OSError:
            pass

    def _pump_member(self, run: _Run, member: _Member, runner) -> None:
        own = open(os.path.join(member.out_dir, CONSOLE_FILE), "w", encoding="utf-8")
        try:
            for line in member.proc.stdout:
                line = line.rstrip("\r\n")
                tagged = f"[{member.id}] {line}"
                with run.lock:
                    run.lines.append(tagged)
                    run.tags.append(member.index)
                    run.total += 1
                    if run.console is not None:
                        run.console.write(tagged + "\n")
                        run.console.flush()
                own.write(line + "\n")
                own.flush()
        finally:
            own.close()
        returncode = member.proc.wait()
        try:
            result = runner.read_results(member.out_dir, None if run.stop_requested else returncode)
            outcome = {"verdict": result.verdict, "counts": result.counts,
                       "tests": result.tests, "message": result.message}
        except Exception as exc:   # noqa: BLE001 -- never leave a member "running"
            outcome = {"verdict": "error", "counts": {}, "tests": [],
                       "message": f"The results could not be read: {exc}"}
        with run.lock:
            member.record.update(outcome, state="done", returncode=returncode,
                                 elapsed_s=round(time.time() - run.record["started_ts"], 1))
            finished = all(m.record["state"] == "done" for m in run.members)
        if member.stop_file:
            try:
                os.remove(member.stop_file)
            except OSError:
                pass
        if finished:
            self._finish_group(run)
        else:
            self._save(run)

    def _finish_group(self, run: _Run) -> None:
        self._end_monitor(run)
        with run.lock:
            records = [m.record for m in run.members]
            verdicts = [r["verdict"] or "error" for r in records]
            verdict = next((v for v in _VERDICT_ORDER if v in verdicts), "error")
            counts: Dict[str, int] = {}
            tests = []
            for r in records:
                for k, v in (r.get("counts") or {}).items():
                    counts[k] = counts.get(k, 0) + int(v)
                tests += [dict(t, member=r["id"]) for t in r.get("tests") or []]
            messages = [f"{r['id']}: {r['message']}" for r in records if r.get("message")]
            run.record.update(state="done", verdict=verdict, counts=counts, tests=tests,
                              message=" | ".join(messages), ended_at=_now(),
                              returncode=max((r["returncode"] or 0) for r in records),
                              elapsed_s=round(time.time() - run.record["started_ts"], 1))
            if run.console is not None:
                run.console.close()
                run.console = None
        self._save(run)

    # ---- resources -----------------------------------------------------

    def _start_monitor(self, run: _Run, pids: Dict[str, int], env: Optional[dict]) -> None:
        """Watch the run's processes from a process of its own (resmon.py)."""
        try:
            interval = float((env or {}).get("MM_RESMON_INTERVAL", RESMON_INTERVAL_S))
        except (TypeError, ValueError):
            interval = RESMON_INTERVAL_S
        if interval <= 0:
            interval = RESMON_INTERVAL_S
        argv = [sys.executable, _RESMON, "record",
                "--out", os.path.join(run.out_dir, RESOURCES_DATA),
                "--report", os.path.join(run.out_dir, RESOURCES_REPORT),
                "--interval", str(interval), "--title", run.record.get("target_label") or run.id]
        for label, pid in pids.items():
            argv += ["--pid", f"{label}={pid}"]
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
        try:
            with open(os.path.join(run.out_dir, "resmon.log"), "w", encoding="utf-8") as log:
                run.monitor = subprocess.Popen(argv, cwd=run.out_dir, stdin=subprocess.DEVNULL,
                                               stdout=log, stderr=subprocess.STDOUT, creationflags=flags)
        except OSError:
            return
        run.monitor_interval = interval
        with run.lock:
            run.record["artifacts"] = list(run.record.get("artifacts") or []) + [
                {"name": RESOURCES_REPORT, "label": "Resources", "primary": False}]

    def _end_monitor(self, run: _Run) -> None:
        """The run's processes have ended: give the monitor its last sample and
        the report. Without a report, the run does not offer one."""
        if run.monitor is None:
            return
        try:
            run.monitor.wait(timeout=run.monitor_interval + 30)
        except subprocess.TimeoutExpired:
            pass
        if not os.path.isfile(os.path.join(run.out_dir, RESOURCES_REPORT)):
            with run.lock:
                run.record["artifacts"] = [a for a in run.record.get("artifacts") or []
                                           if a.get("name") != RESOURCES_REPORT]

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
        self._end_monitor(run)
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
        path = os.path.join(run.out_dir, RUN_FILE)
        with run.save_lock:
            # The snapshot is taken in turn with the writes: a writer that
            # waited here writes the state as it is now, never an older one
            # over a newer one (two members of a group finishing together).
            with run.lock:
                data = dict(run.record)
                if run.members:
                    data["members"] = [dict(m.record) for m in run.members]
            try:
                # Written aside and moved into place: a reader never sees half a file.
                with open(path + ".tmp", "w", encoding="utf-8") as fh:
                    json.dump(data, fh, indent=2, ensure_ascii=False)
                os.replace(path + ".tmp", path)
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
            out = self._public_locked(run)
            out.update(lines=batch, next=start + len(batch), dropped=max(0, first - int(since or 0)))
            if run.members:
                tags = list(run.tags)[start - first:start - first + _MAX_BATCH]
                out["member_lines"] = [[tag, line[len(run.members[tag].id) + 3:]]
                                       for tag, line in zip(tags, batch)]
        self._add_positions(out, run.out_dir, [m.id for m in run.members])
        return out

    @staticmethod
    def _add_positions(out: dict, out_dir: str, member_ids: List[str]) -> None:
        """Where each process is in its flow (POSITION_FILE), when the runner writes it:
        ``position`` for a run, ``member_positions`` (by member index) for a group run."""
        def read(folder):
            try:
                with open(os.path.join(folder, POSITION_FILE), encoding="utf-8") as fh:
                    return json.load(fh)
            except (OSError, ValueError):
                return None
        if member_ids:
            found = [read(os.path.join(out_dir, m)) for m in member_ids]
            if any(found):
                out["member_positions"] = found
        else:
            found = read(out_dir)
            if found:
                out["position"] = found

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
            for m in record.get("members") or []:
                if m.get("state") != "done":
                    m.update(state="done", verdict=m.get("verdict") or "error")
        out = self._public_record(record)
        batch = lines[start:start + _MAX_BATCH]
        out.update(lines=batch, next=min(len(lines), start + _MAX_BATCH), dropped=0)
        if record.get("group"):
            index = {m.get("id"): i for i, m in enumerate(record.get("members") or [])}
            member_lines = []
            for line in batch:
                match = _MEMBER_LINE_RE.match(line)
                if match and match.group(1) in index:
                    member_lines.append([index[match.group(1)], match.group(2)])
            out["member_lines"] = member_lines
        self._add_positions(out, os.path.join(root, RESULTS_DIR, run_id),
                            [m.get("id") for m in record.get("members") or [] if m.get("id")])
        return out

    def stop(self, root: str, run_id: str, *, force: bool = False) -> dict:
        root = _abs_root(root)
        run = self._runs.get((root, run_id))
        if run is None or run.record["state"] == "done":
            raise TestProjectError("That run is not running.")
        if run.members:
            return self._stop_group(run, force)
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

    def _stop_group(self, run: _Run, force: bool) -> dict:
        """Stop every member: gracefully first; a second Stop (or force) kills."""
        again = run.stop_requested
        with run.lock:
            run.stop_requested = True
            run.record["state"] = "stopping"
        for member in run.members:
            if member.proc is None or member.proc.poll() is not None:
                continue
            if force or again or not member.stop_file:
                self._kill(member.proc)
                continue
            try:
                with open(member.stop_file, "w", encoding="utf-8") as fh:
                    fh.write(_now())
            except OSError:
                self._kill(member.proc)
                continue

            def later(proc=member.proc):
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
                try:
                    item = self._stored(root, run_id, 10 ** 9)
                except TestProjectError as exc:
                    # One unreadable record must not hide the rest of the history.
                    item = self._public_record({"id": run_id, "target_label": run_id, "state": "done",
                                                "verdict": "error", "message": str(exc)})
                item.pop("lines", None)
                item.pop("next", None)
                item.pop("dropped", None)
            item.pop("tests", None)
            item.pop("member_lines", None)
            if item.get("members"):
                item["members"] = [{k: v for k, v in m.items() if k != "tests"}
                                   for m in item["members"]]
            runs.append(item)
        return {"status": "ok", "root": root, "runs": runs}

    def _read_record(self, root: str, run_id: str) -> dict:
        if not _RUN_ID_RE.match(str(run_id)):
            raise TestProjectError(f"Invalid run id {run_id!r}.")
        path = os.path.join(root, RESULTS_DIR, run_id, RUN_FILE)
        try:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        except OSError:
            raise TestProjectError(f"No run {run_id} in this project.") from None
        except ValueError as exc:
            raise TestProjectError(f"The record of run {run_id} ({RUN_FILE}) cannot be read: {exc}") from None

    # ---- files -----------------------------------------------------------

    def artifact_path(self, root: str, run_id: str, name: str, member: str = "") -> str:
        """Absolute path of a file a run left behind, checked to stay inside it.
        ``member``: the folder of one member of a group run."""
        root = _abs_root(root)
        if _load_manifest(root) is None:
            raise TestProjectError(f"{root} is not a test project.")
        if not _RUN_ID_RE.match(str(run_id)) or not _ARTIFACT_RE.match(str(name)):
            raise TestProjectError("Invalid run file.")
        if member and not _ARTIFACT_RE.match(str(member)):
            raise TestProjectError("Invalid run file.")
        path = os.path.join(root, RESULTS_DIR, run_id, *([member] if member else []), name)
        if not os.path.isfile(path):
            raise TestProjectError(f"{name} does not exist for run {run_id}.")
        return path

    # ---- shapes ----------------------------------------------------------

    def _public(self, run: _Run) -> dict:
        with run.lock:
            return self._public_locked(run)

    def _public_locked(self, run: _Run) -> dict:
        """:meth:`_public` for a caller that holds ``run.lock``."""
        record = dict(run.record)
        if run.members:
            record["members"] = [dict(m.record) for m in run.members]
        if record["state"] != "done":
            elapsed = round(time.time() - record["started_ts"], 1)
            record["elapsed_s"] = elapsed
            for m in record.get("members") or []:
                if m.get("state") != "done":
                    m["elapsed_s"] = elapsed
        return self._public_record(record)

    @staticmethod
    def _public_record(record: dict) -> dict:
        out = {k: v for k, v in record.items() if k != "started_ts"}
        out["status"] = "ok"
        out["run_state"] = out.pop("state", "done")
        return out


RUNS = RunManager()
