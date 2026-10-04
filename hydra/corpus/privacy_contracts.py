# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from enum import StrEnum

from pydantic import BaseModel, Field


class PrivacyScanStatus(StrEnum):
    NOT_SCANNED = "not_scanned"
    CLEAR = "clear"
    FLAGGED = "flagged"
    INCOMPLETE = "incomplete"


class PrivacyScanResult(BaseModel):
    status: PrivacyScanStatus = PrivacyScanStatus.NOT_SCANNED
    scanner_version: str = "hydra-privacy-v1"
    finding_types: list[str] = Field(default_factory=list)
    artifacts_scanned: int = 0
    bytes_scanned: int = 0


