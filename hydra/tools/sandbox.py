# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Code sandbox. HYDRA -> isolated ephemeral container -> python. Never host Python.

Per execution: create ephemeral container, mount limited workspace read-only,
block network, limit CPU, limit RAM, limit PIDs, timeout, destroy container.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import sys
import tempfile
import time
import uuid
from abc import ABC, abstractmethod
from pathlib import Path

from pydantic import BaseModel

MAX_OUTPUT = 64 * 1024
DEFAULT_SANDBOX_IMAGE = "hydra-sandbox:py312-v3"


class SandboxResult(BaseModel):
    stdout: str
    stderr: str
    exit_code: int
    duration_ms: float
    timed_out: bool = False


class Sandbox(ABC):
    @abstractmethod
    async def execute_python(self, code: str, timeout: int = 10, workdir: Path | None = None) -> SandboxResult:
        """Run ``code``; ``workdir`` (a task working copy) is mounted read-only as the cwd."""


async def _run(cmd: list[str], stdin: bytes, timeout: int, cwd: str | None = None,
               env: dict | None = None, on_timeout=None) -> SandboxResult:
    started = time.perf_counter()
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
        env=env,
    )
    timed_out = False
    try:
        out, err = await asyncio.wait_for(proc.communicate(stdin), timeout=timeout)
    except asyncio.TimeoutError:
        timed_out = True
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        if on_timeout:
            await on_timeout()
        out, err = await proc.communicate()
    return SandboxResult(
        stdout=out[:MAX_OUTPUT].decode("utf-8", "replace"),
        stderr=(err[:MAX_OUTPUT].decode("utf-8", "replace") + ("\n[timeout]" if timed_out else "")),
        exit_code=proc.returncode if proc.returncode is not None else -1,
        duration_ms=(time.perf_counter() - started) * 1000,
        timed_out=timed_out,
    )


class DockerSandbox(Sandbox):
    def __init__(
        self,
        image: str = DEFAULT_SANDBOX_IMAGE,
        workspace: Path | None = None,
        cpus: str = "1",
        memory: str = "256m",
        pids: int = 64,
        workspace_source: str | None = None,
    ) -> None:
        self.image = image
        self.workspace = workspace
        self.workspace_source = workspace_source
        self.cpus = cpus
        self.memory = memory
        self.pids = pids

    def command(self, name: str, workdir: Path | None = None) -> list[str]:
        cmd = [
            "docker", "run", "--rm", "-i", "--name", name,
            "--network", "none",
            "--cpus", self.cpus,
            "--memory", self.memory, "--memory-swap", self.memory,
            "--pids-limit", str(self.pids),
            "--read-only", "--tmpfs", "/tmp:rw,size=64m",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--user", "65534:65534",
            "-e", "PYTHONDONTWRITEBYTECODE=1",
        ]
        source = str(workdir.resolve()) if workdir is not None else (
            self.workspace_source or (str(self.workspace.resolve()) if self.workspace else None))
        if source:
            cmd += ["-v", f"{source}:/workspace:ro", "-w", "/workspace"]
        return [*cmd, self.image, "python", "-I", "-"]

    async def execute_python(self, code: str, timeout: int = 10, workdir: Path | None = None) -> SandboxResult:
        name = f"hydra-sbx-{uuid.uuid4().hex[:12]}"

        async def destroy():
            p = await asyncio.create_subprocess_exec(
                "docker", "rm", "-f", name,
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            )
            await p.wait()

        return await _run(self.command(name, workdir), code.encode(), timeout, on_timeout=destroy)


class SubprocessSandbox(Sandbox):
    """Development fallback: isolated interpreter in a throwaway directory.

    It is NOT a security boundary (no network or syscall isolation). Use
    DockerSandbox for anything that runs model-generated code in production.
    """

    async def execute_python(self, code: str, timeout: int = 10, workdir: Path | None = None) -> SandboxResult:
        env = {"PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"}
        if os.name == "nt":
            env["SYSTEMROOT"] = os.environ.get("SYSTEMROOT", r"C:\Windows")
        if workdir is not None:
            return await _run([sys.executable, "-I", "-"], code.encode(), timeout, cwd=str(workdir), env=env)
        with tempfile.TemporaryDirectory(prefix="hydra-sbx-") as tmp:
            return await _run([sys.executable, "-I", "-"], code.encode(), timeout, cwd=tmp, env=env)


def build_sandbox(backend: str, image: str, workspace: Path | None,
                  workspace_source: str | None = None) -> Sandbox:
    if backend == "docker":
        return DockerSandbox(image=image, workspace=workspace, workspace_source=workspace_source)
    if backend == "subprocess":
        return SubprocessSandbox()
    raise ValueError(f"unknown sandbox backend: {backend}")
