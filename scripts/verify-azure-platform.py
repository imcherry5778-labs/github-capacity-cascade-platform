#!/usr/bin/env python3
"""P5-W4 targeted render/negative checks. No cluster, cloud identity or Azure API."""
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("azure_renderer", ROOT / "scripts/render-azure-platform.py")
renderer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(renderer)
PIN = renderer.pins()
HELM = str(ROOT / ".tmp/bin/helm")


def run(*args):
    return subprocess.check_output(args, text=True, timeout=120)


def fixture():
    # Parser-only data; this full SHA does not prove a deployable merged source.
    return dict(source_revision="a" * 40, hostname="forgejo.platform.example.com", dns_zone="platform.example.com",
                subscription_id="00000000-0000-0000-0000-000000000000", tenant_id="00000000-0000-0000-0000-000000000000",
                foundation_resource_group="test-foundation", key_vault_name="test-vault",
                forgejo_secrets_client_id="11111111-1111-1111-1111-111111111111",
                cert_manager_client_id="22222222-2222-2222-2222-222222222222",
                postgresql_fqdn="test-postgresql.postgres.database.azure.com", database_name="forgejo",
                pvc_size="10Gi", istio_revision="asm-1-30", ingress_ip="20.1.2.3",
                acme_email="operator@example.com", acme_environment="staging")


def static():
    data = fixture()
    output = renderer.render(data)
    assert output == renderer.render(data), "deterministic render required"
    for key, value in [("source_revision", "main"), ("source_revision", "a" * 7),
                       ("source_revision", "A" * 40), ("hostname", "forgejo.other.example.com"),
                       ("hostname", "127.0.0.1"), ("ingress_ip", "10.0.0.1"),
                       ("postgresql_fqdn", "localhost"), ("pvc_size", "0Gi"),
                       ("istio_revision", "asm-1-21"), ("acme_environment", "prod")]:
        try:
            renderer.render(data | {key: value})
        except ValueError:
            pass
        else:
            raise AssertionError(f"must refuse invalid {key}")
    try:
        renderer.render(data | {"password": "forbidden-input"})
    except ValueError:
        pass
    else:
        raise AssertionError("credential input must be rejected")
    # Actual CLI cannot silently render arbitrary/test SHA or unmerged/dirty source.
    try:
        renderer.check_source(data["source_revision"])
    except (ValueError, subprocess.CalledProcessError):
        pass
    else:
        raise AssertionError("CLI must refuse a source SHA outside the selected clean checkout")

    cluster, project, app = output["argocd-application.json"]["items"]
    assert cluster["stringData"] == {"name": "stable-in-cluster", "server": "https://kubernetes.default.svc",
                                     "namespaces": "forgejo", "clusterResources": "false", "config": "{}"}
    ps, application = project["spec"], app["spec"]
    assert ps["sourceRepos"] == [renderer.CHART, renderer.REPO]
    assert ps["destinations"] == [{"server": "https://kubernetes.default.svc", "namespace": "forgejo"}]
    assert ps["clusterResourceWhitelist"] == []
    assert application["syncPolicy"] == {"automated": {"prune": False, "selfHeal": True}}
    assert [s["targetRevision"] for s in application["sources"]] == [PIN["FORGEJO_CHART_VERSION"], data["source_revision"], data["source_revision"]]
    assert [(s.get("path"), s.get("ref")) for s in application["sources"]] == [(".", None), (None, "values"), ("platform/azure/stable", None)]
    issuer, cert = output["tls.json"]["items"]
    assert issuer["kind"] == "ClusterIssuer" and cert["metadata"]["namespace"] == "aks-istio-ingress"
    assert cert["spec"]["issuerRef"]["name"] == issuer["metadata"]["name"]
    solver = issuer["spec"]["acme"]["solvers"][0]
    assert solver["selector"] == {"dnsNames": [data["hostname"]]}
    assert solver["dns01"]["azureDNS"] == {
        "subscriptionID": data["subscription_id"], "resourceGroupName": data["foundation_resource_group"],
        "hostedZoneName": data["dns_zone"], "environment": "AzurePublicCloud", "managedIdentity": {"clientID": data["cert_manager_client_id"]}}
    assert output["cert-manager-values.json"]["global"]["rbac"]["aggregateClusterRoles"] is False
    assert output["cert-manager-values.json"]["extraArgs"] == ["--issuer-ambient-credentials=false", "--cluster-issuer-ambient-credentials=true"]
    assert output["mesh-config.json"]["metadata"]["namespace"] == "aks-istio-system"
    mesh = json.loads(output["mesh-config.json"]["data"]["mesh"])
    assert set(json.loads(mesh["accessLogFormat"])) == {"status", "detail", "duration_ms", "cluster"}
    assert output["dns-record.json"]["record_name"] == "forgejo"

    with tempfile.TemporaryDirectory(prefix="p5-static-") as temp:
        directory = Path(temp)
        for chart, version, digest in [(PIN["FORGEJO_CHART"], PIN["FORGEJO_CHART_VERSION"], PIN["FORGEJO_CHART_DIGEST"]),
                                       (PIN["CERT_MANAGER_CHART"], PIN["CERT_MANAGER_VERSION"], PIN["CERT_MANAGER_CHART_DIGEST"])]:
            pulled = subprocess.run([HELM, "pull", chart, "--version", version, "--destination", temp],
                                    text=True, capture_output=True, check=True, timeout=120)
            assert "Digest: " + digest in pulled.stderr, "selected chart OCI digest mismatch"
        for name, value in output.items():
            (directory / name).write_text(json.dumps(value))
        manifest = run(HELM, "template", "azure-stable", str(ROOT / "platform/azure/stable"),
                       "--namespace", "forgejo", "-f", str(directory / "stable-values.json"))
        # The producer schema must track the selected stable patch and reject the old drill A.
        stale_values = output["stable-values.json"] | {
            "producer_image": "code.forgejo.org/forgejo/forgejo:" + PIN["FORGEJO_UPGRADE_FROM_IMAGE_TAG"] + "@" + PIN["FORGEJO_UPGRADE_FROM_IMAGE_DIGEST"]}
        (directory / "stale-values.json").write_text(json.dumps(stale_values))
        stale = subprocess.run([HELM, "template", "azure-stable", str(ROOT / "platform/azure/stable"),
                                "--namespace", "forgejo", "-f", str(directory / "stale-values.json")],
                               text=True, capture_output=True, timeout=120)
        assert stale.returncode != 0 and "producer_image" in stale.stderr, "old producer patch must fail schema validation"
        documents = [json.loads("\n".join(line for line in chunk.splitlines() if not line.startswith("#")))
                     for chunk in manifest.split("---") if chunk.strip()]
        assert len(documents) == 7 and all(d["metadata"]["namespace"] == "forgejo" for d in documents)
        whitelist = {(x["group"], x["kind"]) for x in ps["namespaceResourceWhitelist"]}
        assert whitelist == {("", k) for k in ("Secret", "PersistentVolumeClaim", "Service", "ServiceAccount")} | {
            ("apps", "Deployment"), ("networking.istio.io", "Gateway"), ("networking.istio.io", "VirtualService"),
            ("telemetry.istio.io", "Telemetry"), ("secrets-store.csi.x-k8s.io", "SecretProviderClass")}
        assert all((d["apiVersion"].split("/")[0] if "/" in d["apiVersion"] else "", d["kind"]) in whitelist for d in documents)
        by_kind = {d["kind"]: d for d in documents}
        spc = by_kind["SecretProviderClass"]
        assert {x["secretName"]: {key["key"] for key in x["data"]} for x in spc["spec"]["secretObjects"]} == {
            "forgejo-admin": {"username", "password"}, "forgejo-db": {"password"}}
        assert spc["spec"]["parameters"]["clientID"] == data["forgejo_secrets_client_id"]
        producer = by_kind["Deployment"]
        pod = producer["spec"]["template"]["spec"]
        assert producer["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"] == "-10"
        assert producer["spec"]["replicas"] == 1 and pod["serviceAccountName"] == "forgejo-secrets"
        assert pod["volumes"] == [{"name": "secrets", "csi": {"driver": "secrets-store.csi.k8s.io", "readOnly": True,
                                                             "volumeAttributes": {"secretProviderClass": "forgejo-secrets"}}}]
        assert pod["containers"][0]["volumeMounts"][0]["name"] == "secrets"
        assert not any(x in json.dumps(pod) for x in ("secretKeyRef", "envFrom", '"secret":'))
        gateway = by_kind["Gateway"]
        assert gateway["apiVersion"] == by_kind["VirtualService"]["apiVersion"] == "networking.istio.io/v1beta1"
        assert gateway["spec"]["selector"] == {"istio": "aks-istio-ingressgateway-external"}
        server = gateway["spec"]["servers"][0]
        assert server["tls"] == {"mode": "SIMPLE", "credentialName": cert["spec"]["secretName"]}
        assert server["hosts"] == cert["spec"]["dnsNames"] == [data["hostname"]]
        assert by_kind["VirtualService"]["spec"]["http"][0]["directResponse"]["status"] == 404

        forgejo = run(HELM, "template", "forgejo", PIN["FORGEJO_CHART"], "--version", PIN["FORGEJO_CHART_VERSION"],
                      "--namespace", "forgejo", "-f", str(ROOT / "platform/forgejo/values-common.yaml"),
                      "-f", str(ROOT / "platform/forgejo/values-azure.yaml"), "-f", str(directory / "forgejo-runtime-values.json"))
        assert re.findall(r"^kind: (.+)$", forgejo, re.M).count("Deployment") == 1
        assert set(re.findall(r"^kind: (.+)$", forgejo, re.M)) == {"Deployment", "PersistentVolumeClaim", "Secret", "Service"}
        for required in ("replicas: 1", "type: Recreate", "serviceAccountName: forgejo", 'storageClassName: "managed-csi"',
                         "https://" + data["hostname"] + "/", data["postgresql_fqdn"] + ":5432", "SSL_MODE=verify-full",
                         "secretKeyRef:", "name: forgejo-db", "name: forgejo-admin", "DISABLE_REGISTRATION=true", "DISABLE_SSH=true"):
            assert required in forgejo, f"Forgejo render missing {required}"
        assert 'optional: true' not in forgejo and '127.0.0.1:13000' not in forgejo
        images = re.findall(r'^\s+image:\s*"?([^"\s]+)', forgejo, re.M)
        assert images and set(images) == {output["stable-values.json"]["producer_image"]}
        assert set(re.findall(r'^  type: (ClusterIP|NodePort|LoadBalancer)$', forgejo, re.M)) == {"ClusterIP"}
        assert not re.search(r'^  name: (forgejo-admin|forgejo-db)$', forgejo, re.M), "chart must consume, not generate credential secrets"

        cert_render = run(HELM, "template", "cert-manager", PIN["CERT_MANAGER_CHART"], "--version", PIN["CERT_MANAGER_VERSION"],
                          "--namespace", "cert-manager", "-f", str(directory / "cert-manager-values.json"))
        assert 'azure.workload.identity/use: "true"' in cert_render
        assert data["cert_manager_client_id"] in cert_render and 'serviceAccountName: cert-manager' in cert_render
        assert 'aggregationRule:' not in cert_render and 'rbac.authorization.k8s.io/aggregate-to-' not in cert_render

        # Existing static entrypoint already fetches/checksums the exact Core source.
        base = (ROOT / ".tmp/rendered/argocd-core.yaml").read_bytes()
        assert hashlib.sha256(base).hexdigest() == PIN["ARGOCD_CORE_SHA256"]
        (directory / "core.yaml").write_bytes(base)
        kustomization = (ROOT / "platform/azure/argocd/kustomization.yaml").read_text()
        url = f'https://raw.githubusercontent.com/argoproj/argo-cd/{PIN["ARGOCD_COMMIT"]}/manifests/core-install.yaml'
        assert url in kustomization
        (directory / "kustomization.yaml").write_text(kustomization.replace(url, "core.yaml"))
        core = run(str(ROOT / ".tmp/bin/kubectl"), "kustomize", str(directory))
        clusterrole = next(chunk for chunk in core.split("\n---\n") if '\nkind: ClusterRole\n' in chunk and '\n  name: argocd-application-controller\n' in chunk)
        assert "'*'" not in clusterrole and 'resources:\n  - namespaces' in clusterrole
        assert 'resources:\n  - selfsubjectaccessreviews' in clusterrole
        assert 'resource.respectRBAC: strict' in core
        assert not re.search(r'^  name: argocd-(server|dex-server)$', core, re.M)

    rbac = json.loads((ROOT / "platform/azure/argocd/forgejo-rbac.json").read_text())
    role, binding = rbac["items"]
    assert role["kind"] == "Role" and role["metadata"]["namespace"] == binding["metadata"]["namespace"] == "forgejo"
    assert all("*" not in json.dumps(rule) for rule in role["rules"])
    assert not any(group in json.dumps(role["rules"]) for group in ("cert-manager.io", "acme.cert-manager.io", "rbac.authorization.k8s.io"))
    assert binding["subjects"] == [{"kind": "ServiceAccount", "name": "argocd-application-controller", "namespace": "argocd"}]
    assert binding["roleRef"]["name"] == role["metadata"]["name"]
    monitoring = json.loads((ROOT / "platform/azure/monitoring.json").read_text())
    assert monitoring["metadata"] == {"name": "ama-metrics-prometheus-config", "namespace": "kube-system"}
    assert "names: [forgejo, aks-istio-ingress]" in monitoring["data"]["prometheus-config"]
    assert "forgejo-http;http" in monitoring["data"]["prometheus-config"]
    # No credential fields in committed runtime inputs/Helm templates. Secret reference keys are allowed.
    for source in (ROOT / "platform/azure/stable/templates").glob("*.yaml"):
        value = json.loads(source.read_text())
        assert '"secretKeyRef"' not in json.dumps(value)
        assert '"stringData"' not in json.dumps(value) and '"clientSecret"' not in json.dumps(value)
    trace = json.loads((ROOT / "platform/azure/tracing-collector.json").read_text())
    assert trace["exporters"]["azuremonitor"]["connection_string"] == "${env:APPLICATIONINSIGHTS_CONNECTION_STRING}"
    assert set(trace["service"]["pipelines"]) == {"traces"} and "processors" not in trace
    preflight = (ROOT / "docs/p5-preflight.md").read_text()
    for marker in ("supported", "allowed", "blocked", "not verified", "REVALIDATE", "DEFERRED", "DECIDED",
                   "Cost model", "quota", "soft-delete", "bootstrap → foundation → environment → platform → runtime validation",
                   "platform → environment → foundation → bootstrap"):
        assert marker in preflight
    sql = (ROOT / "platform/azure/postgresql-role.sql").read_text()
    assert "CREATE ROLE forgejo LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION" in sql
    assert "GRANT USAGE, CREATE ON SCHEMA public TO forgejo" in sql and not re.search(r"PASSWORD\s+'", sql, re.I)
    print("[azure-platform] PASS credential-free render/negative input/Forgejo chart/Argo RBAC/TLS/CSI order/cert-manager/preflight contract")


if __name__ == "__main__":
    static()
