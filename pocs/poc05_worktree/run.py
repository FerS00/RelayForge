"""Comprueba creación, aislamiento y limpieza de un worktree descartable."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.evidence import Evidence  # noqa: E402


def git(repo: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, timeout=60, check=False)
    output = (result.stdout + result.stderr).decode("utf-8", errors="replace")
    if check and result.returncode:
        raise RuntimeError(f"git {args[0]} falló: {output.strip()}")
    return output.strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--runtime", type=Path)
    args = parser.parse_args(argv)
    repo = args.repo.resolve()
    evidence = Evidence("poc05_worktree")
    if not (repo / ".relayforge-sandbox").is_file():
        message = "--repo debe contener .relayforge-sandbox; se rechaza operar sobre otro repositorio"
        evidence.verdict("FAIL", [{"id": "C0", "description": "repositorio sandbox", "passed": False,
                                   "evidence": message}])
        print(message, file=sys.stderr)
        return 2
    runtime = (args.runtime or Path(os.environ.get("RELAYFORGE_POC_RUNTIME", r"C:\RF\poc"))).resolve()
    slug = f"poc05-{time.strftime('%Y%m%d-%H%M%S')}"
    branch = f"poc/wt-{time.strftime('%Y%m%d-%H%M%S')}"
    worktree = runtime / slug / "JOB-000001"
    initial_status = git(repo, "status", "--porcelain")
    base = git(repo, "rev-parse", "HEAD")
    steps = [{"step": 1, "name": "detectar cambios del principal", "ok": True,
              "warning": initial_status or None}]
    created = False
    long_ok = False
    diff_paths: list[str] = []
    submodule_ok: bool | None = None
    cleanup_ok = False
    try:
        runtime.mkdir(parents=True, exist_ok=True)
        git(repo, "worktree", "add", "-b", branch, str(worktree), "HEAD")
        created = True
        steps.append({"step": 2, "name": "crear worktree", "ok": True})
        git(worktree, "config", "core.longpaths", "true")
        steps.append({"step": 3, "name": "configurar core.longpaths", "ok": True})
        if (worktree / ".gitmodules").is_file():
            git(worktree, "-c", "protocol.file.allow=always", "submodule", "update", "--init", "--recursive")
            submodule_ok = (worktree / "vendor/sub").exists()
            steps.append({"step": 4, "name": "inicializar submódulos", "ok": submodule_ok})
        else:
            steps.append({"step": 4, "name": "submódulos", "ok": True, "note": "no hay .gitmodules"})
        attrs = worktree / ".gitattributes"
        if attrs.is_file() and "filter=lfs" in attrs.read_text(encoding="utf-8", errors="replace"):
            if subprocess.run(["git", "lfs", "version"], capture_output=True, check=False).returncode == 0:
                git(worktree, "lfs", "pull")
                steps.append({"step": 5, "name": "git lfs pull", "ok": True})
            else:
                steps.append({"step": 5, "name": "git lfs pull", "ok": False, "note": "LFS no disponible"})
        else:
            steps.append({"step": 5, "name": "LFS", "ok": True, "note": "sin atributos LFS"})
        ops = worktree / "calc/ops.py"
        ops.write_text(ops.read_text(encoding="utf-8") + "\n# modificación de prueba worktree\n", encoding="utf-8", newline="\n")
        nested = worktree / "long-path"
        while len(str(nested / "deep" / "fixture.txt")) <= 270:
            nested = nested / ("segment-" + "x" * 16)
        target = nested / "deep" / "fixture.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("long path fixture\n", encoding="utf-8", newline="\n")
        long_ok = len(str(target)) > 260 and target.is_file()
        git(worktree, "add", "-N", ".")
        diff_paths = git(worktree, "diff", "--name-only", base).splitlines()
        diff = git(worktree, "diff", base)
        evidence.write_text("changes.diff", diff)
        steps.append({"step": 6, "name": "simular cambios y ruta larga", "ok": long_ok})
        steps.append({"step": 7, "name": "capturar diff", "ok": bool(diff_paths)})
        main_unchanged = git(repo, "status", "--porcelain") == initial_status
        steps.append({"step": 8, "name": "principal intacto", "ok": main_unchanged})
        git(repo, "worktree", "lock", str(worktree), "--reason", "poc05 lifecycle")
        git(repo, "worktree", "unlock", str(worktree))
        git(repo, "worktree", "remove", "--force", str(worktree))
        git(repo, "worktree", "prune")
        listed = str(worktree).casefold() in git(repo, "worktree", "list", "--porcelain").casefold()
        cleanup_ok = not worktree.exists() and not listed
        steps.append({"step": 9, "name": "lock, unlock, remove y prune", "ok": cleanup_ok})
        criteria = [
            {"id": "C1", "description": "worktree creado", "passed": created, "evidence": str(worktree)},
            {"id": "C2", "description": "repositorio principal intacto", "passed": main_unchanged,
             "evidence": "git status pre/post"},
            {"id": "C3", "description": "diff contiene los dos archivos", "passed":
             "calc/ops.py" in diff_paths and any(path.endswith("fixture.txt") for path in diff_paths),
             "evidence": ", ".join(diff_paths)},
            {"id": "C4", "description": "ruta supera 260 caracteres", "passed": long_ok,
             "evidence": f"{len(str(target))} caracteres"},
            {"id": "C5", "description": "limpieza completa", "passed": cleanup_ok,
             "evidence": "ruta y worktree list comprobados"},
            {"id": "C6", "description": "submódulo inicializado", "passed": submodule_ok,
             "evidence": "submódulo presente" if submodule_ok else "no aplica"},
        ]
        evidence.write_json("steps.json", steps)
        passed = all(item["passed"] is True for item in criteria if item["id"] != "C6") and submodule_ok is not False
        evidence.verdict("PASS" if passed else "FAIL", criteria)
        return 0 if passed else 1
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        steps.append({"step": "error", "name": "ejecución", "ok": False, "error": str(exc)})
        evidence.write_json("steps.json", steps)
        if created and worktree.exists():
            git(repo, "worktree", "remove", "--force", str(worktree), check=False)
        evidence.verdict("FAIL", [{"id": "C0", "description": "ejecución", "passed": False,
                                   "evidence": str(exc)}])
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
