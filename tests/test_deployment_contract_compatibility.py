# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Legacy imports retain the factory/deployment contracts and JSON representation."""
from hydra.deploy.deployment import Deployment, DeploymentState
from hydra.deploy.deployment_registry import DeploymentRegistry
from hydra.deploy.deployment_resolver import DeploymentResolver
from hydra.model_factory import contracts
from hydra.runtime import deployment, deployment_registry, deployment_resolver, model_factory


def test_factory_symbols_and_json_roundtrip_remain_identical():
    for name in ('BuildState', 'ModelLineage', 'ModelVariant', 'file_sha256', 'lineage_hash'):
        assert getattr(model_factory, name) is getattr(contracts, name)
    fixture = {'variant_id': '00000000-0000-0000-0000-000000000001',
               'lineage': {'lineage_id': '00000000-0000-0000-0000-000000000002',
                           'base_model': 'base', 'base_model_sha256': 'a' * 64,
                           'dataset_id': None, 'dataset_manifest_sha256': None,
                           'training_run_id': None},
               'format': 'gguf', 'quantization': 'Q5_K_M', 'artifact_path': 'model.gguf',
               'artifact_sha256': 'b' * 64, 'state': 'promoted', 'metadata': {}}
    variant = contracts.ModelVariant.model_validate(fixture)
    assert variant.model_dump(mode='json') == fixture
    assert model_factory.ModelVariant.model_validate_json(variant.model_dump_json()) == variant


def test_deployment_types_share_identity_through_legacy_paths():
    assert deployment.Deployment is Deployment
    assert deployment.DeploymentState is DeploymentState
    assert deployment_registry.DeploymentRegistry is DeploymentRegistry
    assert deployment_resolver.DeploymentResolver is DeploymentResolver
