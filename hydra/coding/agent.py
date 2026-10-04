# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Code agent: baseline tests, model patch, verification and artifacts in a task workspace."""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from hydra.artifacts.task_store import ArtifactRecord, ArtifactStore
from hydra.coding.context import CodeContextSelector
from hydra.verification.code import (
    VerificationPolicy,
    VerificationReport,
    build_verification_report,
    changed_python_paths,
    extract_targeted_test,
)
from hydra.core.durable_events import JsonlEventStore
from hydra.coding.patching import PatchTool
from hydra.providers.local_llm import LocalLLM
from hydra.tools.oci_sandbox import OciSandbox
from hydra.tools.task_workspace import ConfinedRoot as Workspace
from hydra.coding.workspace_hash import workspace_sha256
from hydra.tools.task_workspace import TaskWorkspace, TaskWorkspaceManager as WorkspaceManager


@dataclass
class CodeAgentResult:
    accepted: bool
    answer: str
    artifacts: list[ArtifactRecord]
    workspace: TaskWorkspace
    verification: VerificationReport | None = None


def extract_unified_diff(text: str) -> str:
    fence = chr(96) * 3
    candidate = text.strip()
    if candidate.startswith(fence):
        first_newline = candidate.find(chr(10))
        closing = candidate.rfind(fence)
        if first_newline < 0 or closing <= first_newline:
            raise ValueError("Malformed fenced diff")
        candidate = candidate[first_newline + 1 : closing].strip()
    if "--- " not in candidate or "+++ " not in candidate or "@@" not in candidate:
        raise ValueError("Model did not return a valid unified diff")
    return candidate + chr(10)


SandboxFactory = Callable[[Path], OciSandbox]


class CodeAgent:
    def __init__(
        self,
        llm: LocalLLM,
        workspace_manager: WorkspaceManager,
        artifacts: ArtifactStore,
        events: JsonlEventStore,
        sandbox_factory: SandboxFactory | None = None,
        context_selector: CodeContextSelector | None = None,
        verification_policy: VerificationPolicy | None = None,
    ):
        self.llm = llm
        self.workspace_manager = workspace_manager
        self.artifacts = artifacts
        self.events = events
        self.sandbox_factory = sandbox_factory or OciSandbox
        self.context_selector = context_selector or CodeContextSelector()
        self.verification_policy = verification_policy or VerificationPolicy()

    async def run(
        self,
        *,
        task_id: UUID,
        trace_id: str,
        goal: str,
        source: str | Path,
        max_tokens: int,
    ) -> CodeAgentResult:
        workspace = self.workspace_manager.create(task_id, source)
        sandbox = self.sandbox_factory(workspace.root)
        records: list[ArtifactRecord] = []

        preflight = await sandbox.preflight()
        if not preflight.ok:
            self.events.append(
                event_type="hydra.code.sandbox_unavailable",
                aggregate_id=task_id,
                producer="hydra.code_agent",
                trace_id=trace_id,
                payload={
                    "exit_code": preflight.exit_code,
                    "image": getattr(sandbox, "image", None),
                },
            )
            return CodeAgentResult(
                False,
                "Sandbox unavailable; coding task was not executed.",
                records,
                workspace,
            )

        before = await sandbox.pytest(".")
        records.append(self.artifacts.put_text(
            task_id=task_id, kind="tests-before", text=before.output,
            metadata={"exit_code": before.exit_code},
        ))

        if before.ok:
            self.events.append(
                event_type="hydra.code.baseline_passing",
                aggregate_id=task_id,
                producer="hydra.code_agent",
                trace_id=trace_id,
                payload={"reason": "verification_baseline_already_passed"},
            )
            return CodeAgentResult(
                False,
                "Baseline tests already pass; a fix cannot be demonstrated.",
                records,
                workspace,
            )

        baseline_workspace_hash = workspace_sha256(workspace.root)
        targeted_target = extract_targeted_test(before.output, workspace.root)
        context_files = self.context_selector.select(
            workspace.root,
            before.output[-20_000:],
        )
        source_context = self.context_selector.render(context_files)
        prompt = (
            "You are HYDRA CodeAgent. Diagnose the task using the bounded source context "
            "and pytest output below. Return only one unified diff in a diff fenced block. "
            "Do not include shell commands. Do not modify tests unless explicitly requested. "
            "Never reference files outside the provided workspace.\n\n"
            f"TASK:\n{goal}\n\n"
            f"SOURCE CONTEXT:\n{source_context}\n\n"
            f"PYTEST:\n{before.output[-20_000:]}"
        )
        proposal = await self.llm.chat(
            [{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=max_tokens,
        )
        records.append(self.artifacts.put_text(
            task_id=task_id,
            kind="model-patch-proposal",
            text=proposal,
            metadata={"context_paths": [item.path for item in context_files]},
        ))
        diff = extract_unified_diff(proposal)

        patcher = PatchTool(Workspace(workspace.root))
        try:
            applied = patcher.apply(diff)
        except ValueError as exc:
            workspace = self.workspace_manager.create(task_id, source)
            self.events.append(
                event_type="hydra.code.patch_rejected",
                aggregate_id=task_id,
                producer="hydra.code_agent",
                trace_id=trace_id,
                payload={"reason": "patch_policy_rejected", "detail": str(exc)},
            )
            return CodeAgentResult(
                False,
                "Patch rejected by HYDRA patch policy.",
                records,
                workspace,
            )

        if not applied.ok:
            workspace = self.workspace_manager.create(task_id, source)
            self.events.append(
                event_type="hydra.code.patch_rejected",
                aggregate_id=task_id,
                producer="hydra.code_agent",
                trace_id=trace_id,
                payload={"reason": "git_apply_failed"},
            )
            return CodeAgentResult(False, "Patch could not be applied.", records, workspace)

        changed_python = changed_python_paths(diff)
        if targeted_target is not None:
            targeted = await sandbox.pytest(targeted_target)
        else:
            targeted = await sandbox.pytest(".")

        after = await sandbox.pytest(".")
        syntax = await sandbox.py_compile(changed_python)
        ruff = await sandbox.ruff_check(changed_python)
        mypy = await sandbox.mypy_check(changed_python)
        final_workspace_hash = workspace_sha256(workspace.root)

        records.append(self.artifacts.put_text(
            task_id=task_id,
            kind="tests-targeted",
            text=targeted.output,
            metadata={
                "exit_code": targeted.exit_code,
                "target": targeted_target,
            },
        ))
        records.append(self.artifacts.put_text(
            task_id=task_id, kind="tests-after", text=after.output,
            metadata={"exit_code": after.exit_code},
        ))
        records.append(self.artifacts.put_text(
            task_id=task_id, kind="syntax-check", text=syntax.output,
            metadata={
                "exit_code": syntax.exit_code,
                "paths": changed_python,
            },
        ))
        records.append(self.artifacts.put_text(
            task_id=task_id,
            kind="ruff-check",
            text=ruff.output,
            metadata={
                "exit_code": ruff.exit_code,
                "paths": changed_python,
            },
        ))
        records.append(self.artifacts.put_text(
            task_id=task_id,
            kind="mypy-check",
            text=mypy.output,
            metadata={
                "exit_code": mypy.exit_code,
                "paths": changed_python,
            },
        ))
        records.append(self.artifacts.put_text(
            task_id=task_id, kind="applied-patch", text=diff
        ))

        report = build_verification_report(
            baseline=before,
            targeted_target=targeted_target,
            targeted=targeted,
            full_suite=after,
            syntax=syntax,
            ruff=ruff,
            mypy=mypy,
            policy=self.verification_policy,
        )
        report_text = json.dumps(
            {
                "baseline_failed": report.baseline_failed,
                "targeted_target": report.targeted_target,
                "targeted_passed": report.targeted_passed,
                "full_suite_passed": report.full_suite_passed,
                "syntax_passed": report.syntax_passed,
                "ruff_passed": report.ruff_passed,
                "mypy_passed": report.mypy_passed,
                "analysis_mode": report.analysis_mode.value,
                "improvement_demonstrated": report.improvement_demonstrated,
                "verified": report.verified,
                "baseline_workspace_sha256": baseline_workspace_hash,
                "final_workspace_sha256": final_workspace_hash,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        records.append(self.artifacts.put_text(
            task_id=task_id,
            kind="verification-report",
            text=report_text,
            metadata={
                "verified": report.verified,
                "baseline_workspace_sha256": baseline_workspace_hash,
                "final_workspace_sha256": final_workspace_hash,
            },
        ))

        if not report.verified:
            workspace = self.workspace_manager.create(task_id, source)
            self.events.append(
                event_type="hydra.code.patch_rejected",
                aggregate_id=task_id,
                producer="hydra.code_agent",
                trace_id=trace_id,
                payload={
                    "reason": "verification_report_failed",
                    "targeted_passed": report.targeted_passed,
                    "full_suite_passed": report.full_suite_passed,
                    "syntax_passed": report.syntax_passed,
                    "ruff_passed": report.ruff_passed,
                    "mypy_passed": report.mypy_passed,
                    "analysis_mode": report.analysis_mode.value,
                },
            )
            return CodeAgentResult(
                False,
                "Patch rejected: verification report did not pass.",
                records,
                workspace,
                report,
            )

        records.append(self.artifacts.put_text(
            task_id=task_id, kind="verified-patch", text=diff,
            metadata={
                "baseline_workspace_sha256": baseline_workspace_hash,
                "final_workspace_sha256": final_workspace_hash,
            },
        ))
        self.events.append(
            event_type="hydra.code.patch_verified",
            aggregate_id=task_id,
            producer="hydra.code_agent",
            trace_id=trace_id,
            payload={
                "artifact_ids": [str(r.artifact_id) for r in records],
                "baseline_workspace_sha256": baseline_workspace_hash,
                "final_workspace_sha256": final_workspace_hash,
            },
        )
        return CodeAgentResult(
            True,
            "Patch verified in isolated task workspace.",
            records,
            workspace,
            report,
        )
