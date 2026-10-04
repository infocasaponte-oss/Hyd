# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""The HYDRA Base source registry must agree with the licence policy."""
import json
from pathlib import Path

from hydra.training.base_data_policy import admit_source, attribution_notice

REGISTRY = json.loads((Path(__file__).resolve().parents[1] / "config" / "base_sources.json").read_text(encoding="utf-8"))
TARGET_DOMAINS = {"code", "chemistry", "education", "robotics", "automation", "3d-printing", "drones", "legal"}


def test_every_admitted_source_and_extra_licence_passes_the_policy():
    for source in REGISTRY["admitted"]:
        for lic in [source["license"], *source.get("also", [])]:
            assert admit_source(lic).allowed, (source["name"], lic)
        assert source["filter"] and source["url"].startswith("https://")


def test_every_rejected_source_is_rejected_by_the_policy():
    for source in REGISTRY["rejected"]:
        assert not admit_source(source["license"]).allowed, source["name"]


def test_target_domains_and_spanish_are_covered():
    covered = {d for s in REGISTRY["admitted"] for d in s["domains"]}
    assert TARGET_DOMAINS <= covered
    assert any("es" in s["languages"] for s in REGISTRY["admitted"])


def test_registry_produces_a_release_notice():
    notice = attribution_notice({"name": s["name"], "license": s["license"], "url": s["url"]}
                                for s in REGISTRY["admitted"])
    assert "CC-BY-4.0" in notice and "es-public-sector-reuse" in notice and "eu-reuse-2011-833" in notice


def test_local_inventory_agrees_with_the_policy():
    inventory = REGISTRY["local_inventory"]
    for item in inventory["admitted"]:
        for lic in [item["license"], *item.get("also", [])]:
            assert admit_source(lic).allowed, item["path"]
    for item in inventory["rejected"]:
        assert not admit_source(item["license"]).allowed, item["path"]
