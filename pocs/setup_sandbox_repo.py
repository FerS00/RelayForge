"""Crea repositorios desechables y autocontenidos para las POC."""

from __future__ import annotations

import argparse
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path


MARKER = ".relayforge-sandbox"


def _rmtree(path: Path) -> None:
    def make_writable_and_retry(function, failed_path: str, exc_info) -> None:
        os.chmod(failed_path, stat.S_IWRITE)
        function(failed_path)

    shutil.rmtree(path, onexc=make_writable_and_retry)


def git(args: list[str], cwd: Path, *, check: bool = True, input_text: str | None = None) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, input=input_text, text=True, encoding="utf-8",
                            errors="replace", capture_output=True, check=False)
    if check and result.returncode:
        raise RuntimeError(f"git {args[0]} falló ({result.returncode}): {result.stderr.strip()}")
    return result.stdout.strip()


def setup(path: Path, force: bool = False, with_submodule: bool = False,
          with_lfs: bool = False, dirty: bool = False) -> Path:
    path = path.expanduser().resolve()
    if path.exists():
        if not force:
            raise FileExistsError(f"El directorio ya existe: {path}")
        if not (path / MARKER).is_file():
            raise ValueError("--force solo puede borrar un repositorio con marcador RelayForge")
        _rmtree(path)
    path.mkdir(parents=True)
    (path / MARKER).write_text("sandbox\n", encoding="utf-8", newline="\n")
    (path / "calc").mkdir()
    (path / "tests").mkdir()
    (path / "calc/__init__.py").write_text("from .ops import add, div, sub\n", encoding="utf-8", newline="\n")
    (path / "calc/ops.py").write_text(
        "def add(a, b):\n    return a + b\n\n"
        "def sub(a, b):\n    return a - b\n\n"
        "def div(a, b):\n    return a / b\n", encoding="utf-8", newline="\n")
    (path / "tests/test_ops.py").write_text(
        "from calc.ops import add, div, sub\n\n"
        "def test_basic_operations():\n    assert add(2, 3) == 5\n    assert sub(5, 2) == 3\n    assert div(6, 2) == 3\n",
        encoding="utf-8", newline="\n")
    (path / "README.md").write_text("# RelayForge sandbox\n\nDisposable repository for POC runs.\n",
                                     encoding="utf-8", newline="\n")
    (path / ".gitignore").write_text(".env\n__pycache__/\n*.pyc\n", encoding="utf-8", newline="\n")
    (path / ".env").write_text("API_TOKEN=sk-sandboxFAKE0000000000000000\n", encoding="utf-8", newline="\n")
    git(["init", "-b", "main"], path)
    git(["add", "."], path)
    git(["-c", "user.name=RelayForge POC", "-c", "user.email=poc@relayforge.invalid",
         "commit", "-m", "Initial sandbox"], path)

    if with_submodule:
        bare = path.with_name(f"{path.name}-sub.git")
        if bare.exists():
            raise FileExistsError(f"El repositorio bare ya existe: {bare}")
        bare.mkdir(parents=True)
        git(["init", "--bare", "-b", "main", str(bare)], bare)
        seed = path.with_name(f"{path.name}-sub-seed")
        seed.mkdir()
        (seed / "README.md").write_text("Sandbox submodule\n", encoding="utf-8", newline="\n")
        git(["init", "-b", "main"], seed)
        git(["add", "."], seed)
        git(["-c", "user.name=RelayForge POC", "-c", "user.email=poc@relayforge.invalid",
             "commit", "-m", "Submodule"], seed)
        git(["remote", "add", "origin", str(bare)], seed)
        git(["push", "origin", "main"], seed)
        _rmtree(seed)
        git(["-c", "protocol.file.allow=always", "submodule", "add", str(bare), "vendor/sub"], path)
        git(["add", ".gitmodules", "vendor/sub"], path)
        git(["-c", "user.name=RelayForge POC", "-c", "user.email=poc@relayforge.invalid",
             "commit", "-m", "Add local submodule"], path)

    if with_lfs:
        lfs = subprocess.run(["git", "lfs", "version"], capture_output=True, check=False)
        if lfs.returncode:
            print("LFS no disponible")
        else:
            git(["lfs", "track", "*.bin"], path)
            (path / "assets").mkdir(exist_ok=True)
            (path / "assets/blob.bin").write_bytes(bytes(range(256)) * 4)
            git(["add", ".gitattributes", "assets/blob.bin"], path)
            git(["-c", "user.name=RelayForge POC", "-c", "user.email=poc@relayforge.invalid",
                 "commit", "-m", "Add LFS fixture"], path)
    if dirty:
        with (path / "README.md").open("a", encoding="utf-8", newline="\n") as file:
            file.write("\nUncommitted sandbox change.\n")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    default = Path(os.environ.get("RELAYFORGE_SANDBOX_REPO", r"C:\Dev\relayforge-sandbox-repo"))
    parser.add_argument("--path", type=Path, default=default)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--with-submodule", action="store_true")
    parser.add_argument("--with-lfs", action="store_true")
    parser.add_argument("--dirty", action="store_true")
    args = parser.parse_args(argv)
    try:
        print(setup(args.path, args.force, args.with_submodule, args.with_lfs, args.dirty))
    except (OSError, ValueError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
