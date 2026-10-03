"""POC de cancelación de árboles con Windows Job Objects."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import psutil

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.binaries import locate  # noqa: E402
from common.evidence import Evidence  # noqa: E402
from common.procs import JobObject, alive_descendants, spawn_in_job  # noqa: E402


CHILD_CODE = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c','import time; time.sleep(300)']); time.sleep(300)"
ROOT_CODE = "import subprocess,sys,time; code=sys.argv[1]; [subprocess.Popen([sys.executable,'-c',code]) for _ in range(2)]; time.sleep(300)"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=10)
    parser.add_argument("--real", choices=("claude", "codex", "agy"))
    parser.add_argument("--repo", type=Path)
    args = parser.parse_args(argv)
    evidence = Evidence("poc06_cancel")
    evidence.record_versions()
    if args.real:
        if args.repo is None:
            parser.error("--real requiere --repo")
        if not (args.repo / ".relayforge-sandbox").is_file():
            evidence.verdict("FAIL", [{"id": "C0", "description": "repositorio sandbox", "passed": False,
                                       "evidence": "--repo debe contener .relayforge-sandbox"}])
            return 2
        result = _real_run(args.real, args.repo.resolve(), evidence)
        evidence.verdict("PASS" if result else "FAIL", [{"id": "C2", "description": "sin procesos supervivientes",
                                                           "passed": result, "evidence": "árbol vigilado"}])
        return 0 if result else 1
    if sys.platform != "win32":
        evidence.verdict("FAIL", [{"id": "C0", "description": "Windows Job Objects disponibles", "passed": False,
                                   "evidence": "NotImplementedError: solo Windows"}])
        return 1
    iterations = []
    for index in range(args.iterations):
        with JobObject() as job:
            proc = spawn_in_job([sys.executable, "-c", ROOT_CODE, CHILD_CODE], job, Path.cwd(),
                                evidence.dir / f"tree-{index}.out", evidence.dir / f"tree-{index}.err")
            root_ctime = psutil.Process(proc.pid).create_time()
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline and len(alive_descendants(proc.pid, root_ctime)) + 1 < 5:
                time.sleep(0.05)
            children = alive_descendants(proc.pid, root_ctime)
            count = len(children) + 1
            tracked = {pid: psutil.Process(pid).create_time() for pid in children}
            job.terminate()
            clean = _tracked_processes_gone(proc.pid, root_ctime, tracked, 5)
        for name in (f"tree-{index}.out", f"tree-{index}.err"):
            path = evidence.dir / name
            evidence.write_text(name, path.read_text(encoding="utf-8", errors="replace") if path.exists() else "")
        iterations.append({"iteration": index + 1, "process_count": count, "clean": clean})
        if not clean or count < 5:
            break
    evidence.write_json("iterations.json", iterations)
    passed = len(iterations) == args.iterations and all(row["clean"] and row["process_count"] >= 5 for row in iterations)
    evidence.verdict("PASS" if passed else "FAIL", [{"id": "C1", "description": "sin supervivientes en todas las iteraciones",
                                                       "passed": passed, "evidence": f"{len(iterations)}/{args.iterations}"}])
    return 0 if passed else 1


def _real_run(agent: str, repo: Path, evidence: Evidence) -> bool:
    binary = locate(agent)
    if binary.path is None:
        evidence.verdict("FAIL", [{"id": "C0", "description": "binario encontrado", "passed": False,
                                   "evidence": f"{agent} no localizado"}])
        raise SystemExit(3)
    if agent == "claude":
        command = [str(binary.path), "-p", "--output-format", "stream-json"]
    elif agent == "codex":
        command = [str(binary.path), "exec", "--json", "-C", str(repo), "-s", "workspace-write", "-"]
    else:
        command = [str(binary.path), "--mode", "plan", "--add-dir", str(repo), "--output-format", "stream-json", "-p",
                   "Audita este repositorio sin modificarlo; explica su estructura con detalle."]
    prompt = evidence.write_text("real-prompt.txt", "Analiza el repositorio en profundidad y describe el código.\n")
    with JobObject() as job:
        proc = spawn_in_job(command, job, repo, evidence.dir / "agent.out", evidence.dir / "agent.err", prompt)
        time.sleep(15)
        created = psutil.Process(proc.pid).create_time()
        children = alive_descendants(proc.pid, created)
        tracked = {pid: psutil.Process(pid).create_time() for pid in children}
        job.terminate()
        clean = _tracked_processes_gone(proc.pid, created, tracked, 5)
    for name in ("agent.out", "agent.err"):
        path = evidence.dir / name
        evidence.write_text(name, path.read_text(encoding="utf-8", errors="replace") if path.exists() else "")
    return clean


def _tracked_processes_gone(root_pid: int, root_created: float, children: dict[int, float], timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    tracked = {root_pid: root_created, **children}
    while time.monotonic() < deadline:
        alive = False
        for pid, created in tracked.items():
            try:
                process = psutil.Process(pid)
                if abs(process.create_time() - created) < 0.01 and process.is_running():
                    alive = True
            except psutil.NoSuchProcess:
                pass
        if not alive:
            return True
        time.sleep(0.05)
    return False


if __name__ == "__main__":
    raise SystemExit(main())
