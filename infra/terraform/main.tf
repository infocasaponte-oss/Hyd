# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
# Applies the HYDRA Kubernetes manifests to an existing cluster (HYDRA CLUSTER profile).
# Secrets are not part of the manifests: create hydra-secrets / hydra-postgres out of band
# (see infra/kubernetes/00-namespace.yaml) so they never land in the Terraform state.
terraform {
  required_version = ">= 1.6"
  required_providers {
    kubernetes = { source = "hashicorp/kubernetes", version = ">= 2.30" }
  }
}

variable "kubeconfig" {
  type    = string
  default = "~/.kube/config"
}

variable "enable_dra" {
  description = "Apply the DRA ResourceClaimTemplate (needs resource.k8s.io/v1, Kubernetes >= 1.34)."
  type        = bool
  default     = false
}

provider "kubernetes" {
  config_path = var.kubeconfig
}

locals {
  files = [for f in fileset("${path.module}/../kubernetes", "*.yaml") : f
           if var.enable_dra || f != "30-dra-gpu-claim.yaml"]
  docs = flatten([
    for f in local.files : [
      for d in split("\n---\n", file("${path.module}/../kubernetes/${f}")) :
      yamldecode(d) if length(regexall("(?m)^[a-zA-Z]", d)) > 0
    ]
  ])
  namespaces = { for d in local.docs : d.metadata.name => d if d.kind == "Namespace" }
  resources = { for d in local.docs : "${d.kind}/${try(d.metadata.namespace, "_")}/${d.metadata.name}" => d
                if d.kind != "Namespace" }
}

# Namespaces first: namespaced manifests fail if their namespace does not exist yet.
resource "kubernetes_manifest" "namespace" {
  for_each = local.namespaces
  manifest = each.value
}

resource "kubernetes_manifest" "hydra" {
  for_each   = local.resources
  manifest   = each.value
  depends_on = [kubernetes_manifest.namespace]
}
