# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Stable ten-label criteria shared by training, calibration and observation."""
CRITERIA = {
    "chat": "Write a conversational or creative response; no code or external search needed.",
    "coding": "Write, debug or explain software code; do not execute an environment action.",
    "reasoning": "Solve a logical or mathematical problem from the supplied facts.",
    "research": "Find or compare external evidence and cite sources.",
    "vision": "Interpret an attached image, screenshot or photographed document.",
    "tool_use": "Perform an actual operation using environment tools.",
    "abstain": "Required question, input or context is missing; ask for clarification.",
    "security": "Assess malicious commands, threats, exploits or exposed credentials.",
    "privacy": "Assess or handle personal information and sharing restrictions.",
    "high_risk_review": "Review authorization for a consequential or irreversible action; do not execute it.",
}
