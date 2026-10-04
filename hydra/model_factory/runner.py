# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""External tool execution (llama.cpp, ollama, mlx_lm, optimum, llm-compressor...)."""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
import signal
import subprocess
from pathlib import Path

from pydantic import BaseModel


class CommandResult(BaseModel):
    cmd: list[str]
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


class ToolMissing(RuntimeError):
    pass


class CommandRunner:
    """Runs external commands. Tests inject a fake runner; production uses real processes."""

    async def run(self, cmd: list[str], cwd: Path | None = None, timeout: float = 24 * 3600,
                  stdin: bytes | None = None) -> CommandResult:
        async def tail(stream, limit):
            data = bytearray()
            while chunk := await stream.read(8192):
                data.extend(chunk)
                if len(data) > limit:
                    del data[:-limit]
            return bytes(data).decode(errors="replace")

        async def terminate_tree():
            if os.name == "nt":
                killer = await asyncio.create_subprocess_exec(
                    "taskkill", "/PID", str(proc.pid), "/T", "/F",
                    stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
                await killer.wait()
            else:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            if proc.returncode is None:
                proc.kill()
            await proc.wait()

        proc = await asyncio.create_subprocess_exec(
            *cmd, cwd=str(cwd) if cwd else None,
            **({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt"
               else {"start_new_session": True}),
            stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        readers = [asyncio.create_task(tail(proc.stdout, 50000)),
                   asyncio.create_task(tail(proc.stderr, 20000))]
        async def communicate():
            if stdin is not None:
                try:
                    proc.stdin.write(stdin)
                    await proc.stdin.drain()
                except (BrokenPipeError, ConnectionResetError):
                    pass
                finally:
                    proc.stdin.close()
            await proc.wait()
            return await asyncio.gather(*readers)
        try:
            out, err = await asyncio.wait_for(communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            await terminate_tree()
            await asyncio.gather(*readers, return_exceptions=True)
            return CommandResult(cmd=cmd, returncode=-9, stdout="", stderr="timeout")
        except asyncio.CancelledError:
            await terminate_tree()
            for reader in readers:
                reader.cancel()
            await asyncio.gather(*readers, return_exceptions=True)
            raise
        return CommandResult(cmd=cmd, returncode=proc.returncode or 0,
                             stdout=out, stderr=err)


class ToolLocator:
    """Finds the external toolchain: llama.cpp binaries/scripts, ollama, python modules."""

    def __init__(self, llamacpp_dir: Path | None = None) -> None:
        env = os.environ.get("HYDRA_LLAMACPP_DIR")
        self.llamacpp_dir = llamacpp_dir or (Path(env) if env else None)

    def binary(self, name: str) -> str | None:
        candidates = [name, f"{name}.exe"]
        if self.llamacpp_dir:
            for sub in ("", "build/bin", "bin", "build/bin/Release"):
                for c in candidates:
                    p = self.llamacpp_dir / sub / c
                    if p.exists():
                        return str(p)
        return shutil.which(name)

    def llamacpp_script(self, name: str = "convert_hf_to_gguf.py") -> str | None:
        if self.llamacpp_dir and (self.llamacpp_dir / name).exists():
            return str(self.llamacpp_dir / name)
        return None

    @staticmethod
    def python_module(module: str) -> bool:
        import importlib.util

        return importlib.util.find_spec(module) is not None

    def require_binary(self, name: str) -> str:
        path = self.binary(name)
        if path is None:
            raise ToolMissing(f"'{name}' not found (install llama.cpp and set HYDRA_LLAMACPP_DIR)")
        return path

    def availability(self) -> dict[str, bool]:
        return {
            "llama-quantize": self.binary("llama-quantize") is not None,
            "llama-imatrix": self.binary("llama-imatrix") is not None,
            "llama-perplexity": self.binary("llama-perplexity") is not None,
            "llama-server": self.binary("llama-server") is not None,
            "convert_hf_to_gguf.py": self.llamacpp_script() is not None,
            "ollama": self.binary("ollama") is not None,
            "mlx_lm": self.python_module("mlx_lm"),
            "optimum": self.python_module("optimum"),
            "llmcompressor": self.python_module("llmcompressor"),
            "awq": self.python_module("awq"),
            "gptqmodel": self.python_module("gptqmodel"),
            "transformers": self.python_module("transformers"),
            "peft": self.python_module("peft"),
            "huggingface_hub": self.python_module("huggingface_hub"),
        }

    @staticmethod
    def python() -> str:
        return sys.executable
