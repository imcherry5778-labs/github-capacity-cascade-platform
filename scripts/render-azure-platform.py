#!/usr/bin/env python3
"""Credential-free P6 input renderer. It never calls Kubernetes/Azure APIs."""
import argparse
import ipaddress
import json
from pathlib import Path
import re
import subprocess
import uuid

ROOT = Path(__file__).resolve().parents[1]
REPO = "https://github.com/imcherry5778-labs/github-capacity-cascade-platform.git"
CHART = "oci://code.forgejo.org/forgejo-helm/forgejo"
FIELDS = {"source_revision", "hostname", "dns_zone", "subscription_id", "tenant_id",
          "foundation_resource_group", "key_vault_name", "forgejo_secrets_client_id",
          "cert_manager_client_id", "postgresql_fqdn", "database_name", "pvc_size",
          "istio_revision", "ingress_ip", "acme_email", "acme_environment"}


def pins():
    return dict(line.split("=", 1) for line in (ROOT / "versions.env").read_text().splitlines()
                if line and not line.startswith("#"))


def validate(data):
    if set(data) != FIELDS or not all(isinstance(v, str) for v in data.values()):
        raise ValueError("exact non-secret input fields required; passwords/tokens are not accepted")
    patterns = {
        "source_revision": r"[0-9a-f]{40}",
        "hostname": r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+",
        "dns_zone": r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?",
        "foundation_resource_group": r"[a-zA-Z0-9_-][a-zA-Z0-9_.()-]{0,89}",
        "key_vault_name": r"[a-zA-Z][a-zA-Z0-9-]{1,22}[a-zA-Z0-9]",
        "postgresql_fqdn": r"[a-z0-9][a-z0-9-]+\.postgres\.database\.azure\.com",
        "database_name": r"[a-z][a-z0-9_]{0,62}",
        "pvc_size": r"[1-9][0-9]*Gi",
        "istio_revision": r"asm-1-[0-9]+",
        "acme_email": r"[^\s@]+@[^\s@]+\.[^\s@]+",
        "acme_environment": r"staging|production",
    }
    for name, pattern in patterns.items():
        if not re.fullmatch(pattern, data[name]):
            raise ValueError(f"invalid {name}")
    for name in ("subscription_id", "tenant_id", "forgejo_secrets_client_id", "cert_manager_client_id"):
        if str(uuid.UUID(data[name])) != data[name]:
            raise ValueError(f"canonical UUID required: {name}")
    if not data["hostname"].endswith("." + data["dns_zone"]):
        raise ValueError("hostname must be below the existing delegated project zone")
    if int(data["istio_revision"].rsplit("-", 1)[1]) < 22:
        raise ValueError("selected Telemetry v1 requires asm-1-22 or later; regional support must be revalidated")
    ip = ipaddress.IPv4Address(data["ingress_ip"])
    if not ip.is_global:
        raise ValueError("ingress_ip must be the verified public managed gateway IPv4 address")
    return data


def resource(api, kind, name, namespace=None, **fields):
    metadata = {"name": name}
    if namespace:
        metadata["namespace"] = namespace
    return {"apiVersion": api, "kind": kind, "metadata": metadata, **fields}


def render(data):
    d, p = validate(data), pins()
    stable = {k: d[k] for k in ("hostname", "tenant_id", "forgejo_secrets_client_id", "key_vault_name")}
    stable["producer_image"] = "code.forgejo.org/forgejo/forgejo:" + p["FORGEJO_IMAGE_TAG"] + "@" + p["FORGEJO_UPGRADE_TO_IMAGE_DIGEST"]
    forgejo = {
        "image": {"digest": p["FORGEJO_UPGRADE_TO_IMAGE_DIGEST"]},
        "persistence": {"size": d["pvc_size"]},
        "gitea": {"config": {
            "server": {"DOMAIN": d["hostname"], "ROOT_URL": "https://" + d["hostname"] + "/"},
            "database": {"HOST": d["postgresql_fqdn"] + ":5432", "NAME": d["database_name"]},
            "metrics": {"ENABLED": True},
        }},
    }
    allowed = [("", k) for k in ("Secret", "PersistentVolumeClaim", "Service", "ServiceAccount")]
    allowed += [("apps", "Deployment"), ("networking.istio.io", "Gateway"),
                ("networking.istio.io", "VirtualService"), ("telemetry.istio.io", "Telemetry"),
                ("secrets-store.csi.x-k8s.io", "SecretProviderClass")]
    project = resource("argoproj.io/v1alpha1", "AppProject", "forgejo-azure", "argocd", spec={
        "sourceRepos": [CHART, REPO],
        "destinations": [{"server": "https://kubernetes.default.svc", "namespace": "forgejo"}],
        "clusterResourceWhitelist": [],
        "namespaceResourceWhitelist": [{"group": group, "kind": kind} for group, kind in allowed],
    })
    application = resource("argoproj.io/v1alpha1", "Application", "forgejo-azure", "argocd", spec={
        "project": "forgejo-azure",
        "destination": {"server": "https://kubernetes.default.svc", "namespace": "forgejo"},
        "sources": [
            {"repoURL": CHART, "path": ".", "targetRevision": p["FORGEJO_CHART_VERSION"], "helm": {
                "releaseName": "forgejo", "valueFiles": ["$values/platform/forgejo/values-common.yaml", "$values/platform/forgejo/values-azure.yaml"], "valuesObject": forgejo}},
            {"repoURL": REPO, "targetRevision": d["source_revision"], "ref": "values"},
            {"repoURL": REPO, "targetRevision": d["source_revision"], "path": "platform/azure/stable", "helm": {"releaseName": "azure-stable", "valuesObject": stable}},
        ],
        "syncPolicy": {"automated": {"prune": False, "selfHeal": True}},
    })
    # In-cluster config uses controller ServiceAccount, without a stored bearer token.
    cluster = resource("v1", "Secret", "stable-in-cluster", "argocd", type="Opaque", stringData={
        "name": "stable-in-cluster", "server": "https://kubernetes.default.svc", "namespaces": "forgejo",
        "clusterResources": "false", "config": "{}",
    })
    cluster["metadata"]["labels"] = {"argocd.argoproj.io/secret-type": "cluster"}
    issuer = resource("cert-manager.io/v1", "ClusterIssuer", "forgejo-dns01", spec={"acme": {
        "server": {"staging": "https://acme-staging-v02.api.letsencrypt.org/directory", "production": "https://acme-v02.api.letsencrypt.org/directory"}[d["acme_environment"]],
        "email": d["acme_email"], "privateKeySecretRef": {"name": "forgejo-acme-account"},
        "solvers": [{"selector": {"dnsNames": [d["hostname"]]}, "dns01": {"azureDNS": {
            "subscriptionID": d["subscription_id"], "resourceGroupName": d["foundation_resource_group"],
            "hostedZoneName": d["dns_zone"], "environment": "AzurePublicCloud",
            "managedIdentity": {"clientID": d["cert_manager_client_id"]},
        }}}],
    }})
    certificate = resource("cert-manager.io/v1", "Certificate", "forgejo-tls", "aks-istio-ingress", spec={
        "secretName": "forgejo-tls", "dnsNames": [d["hostname"]],
        "issuerRef": {"name": "forgejo-dns01", "kind": "ClusterIssuer", "group": "cert-manager.io"},
        "privateKey": {"rotationPolicy": "Always"},
    })
    namespaces = [resource("v1", "Namespace", ns) for ns in ("argocd", "cert-manager", "forgejo")]
    namespaces[-1]["metadata"]["labels"] = {"istio.io/rev": d["istio_revision"]}
    cert_values = {"crds": {"enabled": True}, "global": {"rbac": {"aggregateClusterRoles": False}},
                   "podLabels": {"azure.workload.identity/use": "true"},
                   "serviceAccount": {"name": "cert-manager", "annotations": {"azure.workload.identity/client-id": d["cert_manager_client_id"]}},
                   "extraArgs": ["--issuer-ambient-credentials=false", "--cluster-issuer-ambient-credentials=true"]}
    record = {"record_name": d["hostname"][:-(len(d["dns_zone"]) + 1)], "zone": d["dns_zone"],
              "resource_group": d["foundation_resource_group"], "subscription_id": d["subscription_id"],
              "record_type": "A", "body": {"properties": {"TTL": 300, "ARecords": [{"ipv4Address": d["ingress_ip"]}]}}}
    mesh = resource("v1", "ConfigMap", "istio-shared-configmap-" + d["istio_revision"], "aks-istio-system", data={
        "mesh": json.dumps({"accessLogFile": "/dev/stdout", "accessLogEncoding": "JSON",
                            "accessLogFormat": '{"status":"%RESPONSE_CODE%","detail":"%RESPONSE_CODE_DETAILS%","duration_ms":"%DURATION%","cluster":"%UPSTREAM_CLUSTER%"}',
                            "defaultConfig": {"holdApplicationUntilProxyStarts": True}})
    })
    return {"namespaces.json": {"apiVersion": "v1", "kind": "List", "items": namespaces},
            "argocd-application.json": {"apiVersion": "v1", "kind": "List", "items": [cluster, project, application]},
            "tls.json": {"apiVersion": "v1", "kind": "List", "items": [issuer, certificate]},
            "cert-manager-values.json": cert_values, "forgejo-runtime-values.json": forgejo,
            "stable-values.json": stable, "dns-record.json": record, "mesh-config.json": mesh}


def check_source(revision):
    def git(*args):
        return subprocess.check_output(["git", "-C", str(ROOT), *args], text=True).strip()
    if git("rev-parse", "HEAD") != revision:
        raise ValueError("render from checkout of the exact selected source_revision")
    if git("status", "--porcelain"):
        raise ValueError("clean source checkout required")
    subprocess.run(["git", "-C", str(ROOT), "merge-base", "--is-ancestor", revision, "origin/main"], check=True)
    # Fresh fetch + independent actual GitHub merged-state review remain the P6 operator gate.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    data = validate(json.loads(args.input.read_text()))
    check_source(data["source_revision"])
    outputs = render(data)
    args.output.mkdir(parents=True, exist_ok=False)
    for name, value in outputs.items():
        (args.output / name).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    print("Rendered credential-free source; no Azure/Kubernetes action performed.")


if __name__ == "__main__":
    main()
