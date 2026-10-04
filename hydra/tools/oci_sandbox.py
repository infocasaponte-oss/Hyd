# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Verification sandbox: py_compile, ruff, mypy and pytest on a task workspace in a fixed OCI container
(network disabled, read-only root, dropped capabilities, bounded memory/CPU/PIDs, cleanup on timeout or
cancellation). Complements ``hydra.tools.sandbox``, which runs model-written Python snippets."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from hydra.tools.sandbox import DEFAULT_SANDBOX_IMAGE  # one image for both sandboxes


@dataclass(frozen=True)
class SandboxLimits:
    memory: str = "1g"
    cpus: float = 2.0
    pids: int = 128
    timeout_seconds: int = 120


@dataclass(frozen=True)
class SandboxResult:
    ok: bool
    output: str
    exit_code: int




class OciSandbox:
    """
    Host-controlled Docker-compatible sandbox.

    The model never receives Docker access. HYDRA invokes a fixed container
    command with network disabled and the task workspace as the only writable mount.
    """

    def __init__(
        self,
        workspace: str | Path,
        *,
        image: str = DEFAULT_SANDBOX_IMAGE,
        runtime: str = "docker",
        limits: SandboxLimits | None = None,
    ):
        self.workspace = Path(workspace).resolve()
        self.image = image
        self.runtime = runtime
        self.limits = limits or SandboxLimits()

    async def preflight(self) -> SandboxResult:
        try:
            proc = await asyncio.create_subprocess_exec(
                self.runtime,
                "image",
                "inspect",
                self.image,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        except FileNotFoundError:
            return SandboxResult(False, "sandbox runtime unavailable", 127)

        stdout, _ = await proc.communicate()
        output = stdout.decode("utf-8", errors="replace")[-10_000:]
        if proc.returncode != 0:
            return SandboxResult(
                False,
                output or f"sandbox image unavailable: {self.image}",
                proc.returncode,
            )
        return SandboxResult(True, output, 0)

    async def py_compile(self, paths: list[str]) -> SandboxResult:
        if not paths:
            return SandboxResult(True, "no Python files changed", 0)

        relative_paths: list[str] = []
        for raw in paths:
            target_path = (self.workspace / raw).resolve()
            if self.workspace not in target_path.parents:
                raise ValueError("Sandbox compile target escape rejected")
            if not target_path.is_file():
                return SandboxResult(False, f"compile target missing: {raw}", 2)
            relative_paths.append(str(target_path.relative_to(self.workspace)))

        cmd = [
            self.runtime, "run", "--rm",
            "--network", "none",
            "--read-only",
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "--memory", self.limits.memory,
            "--cpus", str(self.limits.cpus),
            "--pids-limit", str(self.limits.pids),
            "--user", "65532:65532",
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=128m",
            "--mount", f"type=bind,src={self.workspace},dst=/workspace,rw",
            "--workdir", "/workspace",
            self.image,
            "python", "-m", "py_compile", *relative_paths,
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        except FileNotFoundError:
            return SandboxResult(False, "sandbox runtime unavailable", 127)
        try:
            stdout, _ = await asyncio.wait_for(
                proc.communicate(), timeout=self.limits.timeout_seconds
            )
        except TimeoutError:
            proc.kill()
            await proc.wait()
            return SandboxResult(False, "sandbox timeout", 124)

        output = stdout.decode("utf-8", errors="replace")[-50_000:]
        return SandboxResult(proc.returncode == 0, output, proc.returncode)

    def _relative_targets(self, paths: list[str]) -> list[str]:
        relative_paths: list[str] = []
        for raw in paths:
            target_path = (self.workspace / raw).resolve()
            if self.workspace not in target_path.parents:
                raise ValueError("Sandbox analysis target escape rejected")
            if not target_path.is_file():
                raise ValueError(f"Sandbox analysis target missing: {raw}")
            relative_paths.append(str(target_path.relative_to(self.workspace)))
        return relative_paths

    async def _analysis_command(self, argv: list[str]) -> SandboxResult:
        cmd = [
            self.runtime, "run", "--rm",
            "--network", "none",
            "--read-only",
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "--memory", self.limits.memory,
            "--cpus", str(self.limits.cpus),
            "--pids-limit", str(self.limits.pids),
            "--user", "65532:65532",
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=128m",
            "--mount", f"type=bind,src={self.workspace},dst=/workspace,rw",
            "--workdir", "/workspace",
            self.image,
            *argv,
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        except FileNotFoundError:
            return SandboxResult(False, "sandbox runtime unavailable", 127)
        try:
            stdout, _ = await asyncio.wait_for(
                proc.communicate(), timeout=self.limits.timeout_seconds
            )
        except TimeoutError:
            proc.kill()
            await proc.wait()
            return SandboxResult(False, "sandbox timeout", 124)
        output = stdout.decode("utf-8", errors="replace")[-50_000:]
        return SandboxResult(proc.returncode == 0, output, proc.returncode)

    async def ruff_check(self, paths: list[str]) -> SandboxResult:
        if not paths:
            return SandboxResult(True, "no Python files changed", 0)
        targets = self._relative_targets(paths)
        return await self._analysis_command(["ruff", "check", *targets])

    async def mypy_check(self, paths: list[str]) -> SandboxResult:
        if not paths:
            return SandboxResult(True, "no Python files changed", 0)
        targets = self._relative_targets(paths)
        return await self._analysis_command(
            ["mypy", "--follow-imports=skip", "--ignore-missing-imports", *targets]
        )

    async def pytest(self, target: str = ".", *, read_only: bool = False) -> SandboxResult:
        target_path = (self.workspace / target).resolve()
        if target_path != self.workspace and self.workspace not in target_path.parents:
            raise ValueError("Sandbox target escape rejected")
        relative = target_path.relative_to(self.workspace).as_posix() or "."
        # Prefix prevents a filename beginning with '-' from becoming a pytest option.
        relative = "./" + relative
        container = "hydra-test-" + uuid4().hex

        cmd = [
            self.runtime, "run", "--rm", "--name", container,
            "--network", "none",
            "--read-only",
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "--memory", self.limits.memory,
            "--cpus", str(self.limits.cpus),
            "--pids-limit", str(self.limits.pids),
            "--user", "65532:65532",
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=128m",
            "--mount", f"type=bind,src={self.workspace},dst=/workspace,{'readonly' if read_only else 'rw'}",
            "--workdir", "/workspace",
            self.image,
            "python", "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider", relative,
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        except FileNotFoundError:
            return SandboxResult(False, "sandbox runtime unavailable", 127)
        try:
            stdout, _ = await asyncio.wait_for(
                proc.communicate(), timeout=self.limits.timeout_seconds
            )
        except (TimeoutError, asyncio.CancelledError) as exc:
            proc.kill()
            await proc.wait()
            # Killing the CLI alone does not stop its container. Remove this exact
            # task container, never another job, before returning or cancelling.
            try:
                cleanup = await asyncio.create_subprocess_exec(
                    self.runtime, "rm", "-f", container,
                    stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
                try:
                    await asyncio.wait_for(cleanup.wait(), timeout=10)
                except TimeoutError:
                    cleanup.kill()
                    await cleanup.wait()
            except OSError:
                pass
            if isinstance(exc, asyncio.CancelledError):
                raise
            return SandboxResult(False, "sandbox timeout", 124)

        output = stdout.decode("utf-8", errors="replace")[-50_000:]
        return SandboxResult(proc.returncode == 0, output, proc.returncode)
