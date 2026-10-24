# P6 비용 없는 실행 준비

이 문서는 `575b7827ac0d9fedebba82abbf3374454c0d712c`를 baseline으로 한 준비 절차다.
P6 paid execution/P7 승인이나 runtime 완료 evidence가 아니다.
[Aggregate preflight](p5-preflight.md)의 resource inventory, RBAC, DNS 및 teardown contract를 그대로 사용한다.

## 유지하는 account evidence

다음은 이번 mission에서 전달된 기존 evidence이며 account/quota/RP 전체 조사를 반복하지 않았다.

| 항목 | 기존 결과 / 후보 |
| --- | --- |
| Subscription | Azure subscription 1, Enabled / PAYG |
| Region | Korea Central |
| 필수 RP | 이전 조사 대상 7개 모두 Registered; 전체 source RP inventory와 동일 개수라고 일반화하지 않음 |
| PostgreSQL quota | total cores 0/384, standardDDSv5Family 0/192 |
| AKS / managed Istio | 1.36.4 / asm-1-30 후보 |
| System pool | Standard_D4s_v4 × 2 후보 |
| 비용 | $15.81–$35.59 추정, 세전 $50 / 당일 최대 10시간 검토 예산 |
| DNS | imcherry5778.xyz apex / forgejo.imcherry5778.xyz hostname 후보; Gabia NS → Azure NS 4개 |

비용과 후보는 배포 승인이 아니다. 실제 유료 실행 직전 current cost/resource/RBAC/quota gate를 다시 충족한다.

## Grafana targeted read-only 결과 — 2026-10-23 UTC

[Read-only 응답 기록](evidence/p6-execution-preparation-20261023.json)은 subscription ID를 placeholder로 바꾸고
response body/HTTP status만 보존한다. CLI Authorization header, credential, private path는 보관하지 않는다.

| GET endpoint (`https://management.azure.com` 뒤) | API version | 관측 |
| --- | --- | --- |
| `/subscriptions/{subscriptionId}/providers/Microsoft.Dashboard` | 2021-04-01 | HTTP 200; Registered; `grafana` resource type의 locations에 Korea Central 포함 |
| `/subscriptions/{subscriptionId}/providers/Microsoft.Dashboard/skus` | 2025-08-01 | HTTP 200; `{"value":[]}` |
| `/subscriptions/{subscriptionId}/providers/Microsoft.Dashboard/locations/koreacentral/grafanaVersions` | 2025-08-01 | HTTP 404; `ResourceTypeRegistrationNotFound`; 아래 탐색 경로의 결과 |

실제 새 CLI 호출 형식은 `az rest --method get --url '<각 행의 full endpoint>' --verbose -o json`이며,
정확한 argv도 응답 기록의 `command`에 있다. Subscription ID만 placeholder로 정규화했다.
Provider GET은 [공식 Resource Management contract](https://learn.microsoft.com/en-us/rest/api/resources/providers/get?view=rest-resources-2021-04-01)다.
SKU/major-version 두 탐색 경로는 아래 inspected OpenAPI에서 확인되지 않아 공식 regional enumeration API로 인증하지 않는다.

마지막 응답의 body는 다음과 같다.

```json
{"error":{"code":"ResourceTypeRegistrationNotFound","message":"The resource type registration 'Microsoft.Dashboard/locations/grafanaVersions' could not be found."}}
```

이전 오류의 원래 URL/API version은 전달되지 않았으며 repository에도 없다. Session search는 disabled여서
과거 요청을 복원하지 않았다. 위 요청은 **이번에 수행한 탐색 GET**이며 과거 요청과 동일하다고 주장하지 않는다.
기존 SKU 빈 목록과 major-version 오류는 전달된 historical observation으로만 유지한다.
확인한 [Microsoft OpenAPI 2025-08-01](https://github.com/Azure/azure-rest-api-specs/blob/abf2c7290136ff3e0493caf2566434b84c484522/specification/dashboard/resource-manager/Microsoft.Dashboard/Dashboard/stable/2025-08-01/grafana.json)에는
SKU/지역별 major-version 열거 endpoint가 없다. 해당 오류를 `Microsoft.Dashboard/grafana` 미등록으로 해석하거나
RP 추가 등록으로 고치지 않는다. Provider metadata의 API versions는 응답 기록에 있으며 2025-08-01을 포함한다.
Metadata에 있는 최신 API version이 위 OpenAPI snapshot과 같은 범위를 문서화한다고 가정하지 않는다.

[Microsoft service tier 문서](https://learn.microsoft.com/en-us/azure/managed-grafana/overview)는 신규 Standard와
X1/X2를 설명하고, [Microsoft upgrade 문서](https://learn.microsoft.com/en-us/azure/managed-grafana/how-to-upgrade-grafana-12)는
Managed Grafana 12를 설명한다. 이는 해당 subscription/Korea Central의 Standard 및 12/13 조합이
생성 가능하다는 증거가 아니다. OpenAPI의 `grafanaMajorVersion`도 string contract이지 지역별 허용 목록이 아니다.
AzureRM 5.7.0의 12/13 input validation과 upstream Grafana 지원 기간도 지역별 서비스 가용성과 구분한다.

**Korea Central Standard + Grafana 12/13: not verified. 확정 후보 없음.**
Region/Terraform source를 변경하지 않았으며, 공식 regional evidence 또는 Microsoft 확인 전 paid gate는 닫혀 있다.

## Bootstrap local state 보호와 dummy 복구 점검

현재 trusted operator가 생성부터 보관·복구·최종 cleanup까지 책임진다. CI identity에 bootstrap 관리 권한을 주지 않는다.
실제 state는 아직 없다. 아래는 운영자가 유료 승인 뒤 사용할 절차이며 실제 backup/restore 성공 기록이 아니다.

1. Bootstrap Terraform은 장기간 유지되는 primary Git checkout의 `infra/terraform/bootstrap/`에서 실행한다.
   기존 backend block 없는 implicit local backend를 유지하며, 기본 `terraform.tfstate`를 해당 디렉터리에 저장한다.
   이는 [Terraform local backend의 기본 경로](https://developer.hashicorp.com/terraform/language/backend/local#path)를 따른다.
   일회성 Local Agent worktree에는 실제 state를 생성하지 않는다. 승인된 operator의 기존 인증을 사용하며
   bootstrap state를 GitHub runner/remote backend로 migrate하지 않는다. Foundation/Environment는 기존 Azure Blob remote backend를 유지한다.
2. Terraform 실행마다 `umask 077`을 사용하고 state와 `terraform.tfstate.backup`, 로컬 input/crash 파일의
   owner-only 권한 `0600`을 확인한다. 기존 파일은 필요 시 `chmod 600`으로 보정한다.
   `terraform.tfstate`, `terraform.tfstate.backup`은 기존 `.gitignore`의 `*.tfstate`, `*.tfstate.*`로,
   `.terraform/`과 로컬 `*.tfvars`/`*.tfvars.json`도 기존 규칙으로 Git에서 제외한다.
   Bootstrap state가 존재하는 checkout에는 `git clean -fdx` 등 무시 파일을 삭제하는 정리 작업을 실행하지 않는다.
3. Git 저장소 밖에 최신 state와 복구 input/metadata의 암호화 백업을 하나 이상 유지한다.
   암호화 백업 위치는 operator 전용 저장소의 `encrypted-backups/<UTC>-<source-SHA>/bootstrap.tar.gpg`다.
   실제 state, 존재하는 `.backup`, 필수 복구 input, source SHA/committed lockfile/Terraform/provider version 및
   checksum manifest를 저장소 밖의 private staging directory(`0700`, 파일 `0600`)에서 묶는다.
   백업·복구에도 `umask 077`을 사용한다. `tar ... | gpg --symmetric --cipher-algo AES256 --output ...`로
   기존 GnuPG와 terminal pinentry를 사용한다. Passphrase는 기존 OS credential/password 보관 수단에 별도로
   유지하고 argv/env/Git/문서에 넣지 않는다. 암호문과 key를 같은 bundle에 넣지 않는다.
   각 승인된 bootstrap 변경 및 downstream 정리 후 새 UTC 파일로 백업을 갱신한다. 기존 backup을 덮어쓰지 않는다.
   최종 destroy 전에는 최신 원본 state와 이에 대응하는 백업, 복구 input/metadata 및 복호화 수단을 확인한다.
4. 복구 시 automation과 기존 operator writer를 정지하고 state/backend lock과 actual Azure inventory를 확인한다.
   Git 저장소 밖에 별도 `0700` directory를 만들어 암호문을 `0600` archive로 복호화하고 integrity/checksum을
   대조한다. Archive member path를 확인한 뒤 복원하고 source/lockfile/version/lineage/serial과 Azure resource IDs를
   대조한다. 기존 state를 바로 덮어쓰거나 apply하지 않는다. 더 최신 state/불확실한 ownership이면 중단한다.
   Primary checkout의 `infra/terraform/bootstrap/`에 복구본을 반영하기 전 operator가 복구본과 실제 자원 일치를 확인한다.
5. 정상 종료 후 plaintext staging/archive를 제거하고 암호화 백업은 승인된 보존 기간/복구 검증까지 유지한다.
   SSD/CoW에서 파일 삭제를 secure erase로 주장하지 않는다.

로컬 원본 state와 `.backup`, input/crash/log는 암호화되지 않을 수 있다. `.gitignore`와 owner-only 파일 권한은
암호화가 아니며, 로컬 디스크 접근·유실에 따른 민감정보 노출 위험이 남는다. 암호화 백업은 원본을 암호화하지 않는다.
실제 bootstrap state backup/restore와 Azure resource recovery는 실행 전까지 **not verified**로 유지한다.

`python3 tests/e2e/test-bootstrap-state-protection.py`는 실제 state 형식이 아닌 명시적 dummy JSON으로
`0700`/`0600` → dummy/checksum manifest tar bundle → GnuPG AES256 암호화 → 원본 삭제 →
복호화 후 member/checksum/byte 비교 → 잘못된 passphrase 거부를 점검한다.
임시 test key만 사용하고 일반 operator gpg-agent를 건드리지 않는다. 이것은 **dummy 절차 점검**이며 actual bootstrap
state 복구, encrypted volume 보장, off-device 재해복구, Azure resource 복원 evidence가 아니다.

`.gitignore`의 state/plan/tfvars/crash 제외는 실수 방지 보조다. Checkout에 보관하는 state를 Git에 추적·commit하지 않는다.
CI에는 allowlisted non-secret backend coordinates만 수동 전달한다. `terraform output -json` 전체/state pull,
credential/password, state snapshot, plan binary/JSON, `.terraform`, provider log를 Git/CI artifact/log로 보내지 않는다.

Cleanup은 platform → environment → foundation → bootstrap이다. Foundation DNS delegation 복구/전파와
downstream state/lock/evidence 보존이 끝나기 전 bootstrap backend/CI trust/RBAC/RG를 지우지 않는다.
Bootstrap은 같은 operator가 local state로 마지막 제거한다. DNS 보존이 필요하면 bootstrap도 그 경계를 유지한다.
잔존·soft-delete·identity/RBAC·state backend finalization은 aggregate preflight를 따른다.

## 수동 OIDC workflow와 campaign gate

[Workflow](../.github/workflows/azure-execution.yml)는 `workflow_dispatch`만 지원하며 한 번에 기존 remote-state
stack 하나의 operation 하나만 처리한다. Bootstrap/platform/DNS operator action은 포함하지 않는다.
`azure` Environment 선택과 workflow_dispatch 입력은 비용 승인이 아니다.

현재 immutable subject는 기존 Terraform FIC 그대로다.

```text
repo:imcherry5778-labs@273613742/github-capacity-cascade-platform@1384941385:environment:azure
```

이번 live GitHub read-only 확인에서 immutable subject/main-only branch policy/required reviewer 부재는 기존
[trust inspection](../infra/terraform/bootstrap/README.md#inspected-github-trust)과 일치했다. 설정은 변경하지 않았다.
Workflow는 Azure login action, long-lived credential, bootstrap state를 사용하지 않고 provider/backend의 OIDC 자동 탐색을 쓴다.
실제 OIDC 발급/exchange/backend locking/effective RBAC는 **not verified**다.

Trusted operator는 별도 명시적 P6 user approval을 받은 뒤에만 repository variable 두 개를 설정한다.
이번 준비 세션에서는 variable/secret을 설정하지 않고 workflow도 dispatch하지 않는다.

- `P6_EXECUTION_CONFIG`: `backend`, `foundation`을 가진 JSON object. Foundation operation에서는
  `environment`를 생략할 수 있고, Environment operation에서는 세 object가 모두 필요하다.
  Backend에는 bootstrap output에서 `storage_account_name`, `container_name`, `tenant_id`, `client_id` 네 필드만 옮긴다.
  포함한 stack object는 각 `variables.tf`의 모든 non-secret input을 정확히 포함한다. 허용되지 않은 key나
  불완전한 stack 입력은 거부하며, `environment`가 있으면 operation에 관계없이 cross-stack identity/RG도 검증한다.
  `postgresql_administrator_password`는 포함하지 않는다. Backend key/auth flag는 source가 고정한다.
  Account/resource names, SKU, versions, CIDR, authorized IPs, observability 값은 실제 승인 inventory와 대조한다.
  Config 구성이 바뀌면 전체 config SHA256과 해당 exact inputs/operation의 승인을 다시 받아야 한다.
- `P6_CAMPAIGN_APPROVAL`: 아래 **비활성 template**을 actual user approval/evidence로 채운 JSON object.
  Repository/Environment에 같은 이름의 variable을 중복 정의하지 않는다. Config digest는 canonical JSON
  (sorted keys, compact separators, ASCII encoding)의 SHA256이며
  `P6_EXECUTION_CONFIG='<non-secret JSON>' python3 scripts/azure-execution.py digest-config`로 계산한다.
  Approval link를 적는 행위 자체가 user approval은 아니다. 관리 operator가 원문 승인과 exact scope를 대조할 책임이 있다.
  Variable write 권한은 trusted operator 경계이며 workflow가 링크 내용의 승인 의사를 판정하지는 않는다.

```json
{
  "status": "pending",
  "campaign_id": "P6-UNAPPROVED",
  "source_sha": "REPLACE_WITH_REVIEWED_MERGED_MAIN_SHA",
  "source_pr": 0,
  "operator": "REPLACE_WITH_TRUSTED_GITHUB_LOGIN",
  "approval_evidence": "",
  "preflight_evidence": "",
  "starts_at": "",
  "expires_at": "",
  "budget_usd": 50,
  "config_sha256": "",
  "allowed_operations": [],
  "prerequisite_evidence": {}
}
```

승인 전 `pending`/미설정 상태는 gate 실패다. 승인 기록은 reviewed/merged source PR의 **merge commit SHA**를 사용한다
(squash 전 PR HEAD와 구분). Dispatch SHA, checkout SHA, current main, approval SHA가 모두 같아야 한다.
Gate job은 merged PR의 `merge_commit_sha`도 API로 확인한다. 따라서 이 job에만 `pull-requests: read`가 추가된다.
이 job은 OIDC 권한이 없고, 성공 뒤 `environment: azure`의 Terraform job만 `contents: read`, `id-token: write`를 가진다.
Execution job은 init 전 및 plan/apply 직전에 source/approval 만료를 재검사한다. Main이 이동했으면 새 source review/approval이 필요하다.
Rerun은 거부한다. 실패 후에는 state/locks와 actual resource를 확인하고 새 dispatch를 사용한다.
공유 concurrency는 두 stack을 직렬화하며 진행 중 실행을 자동 취소하지 않는다.

Approval의 `allowed_operations`와 `prerequisite_evidence`는 다음 순서로 **그때 확인한 evidence**를 사용한다.
서로 다른 dispatch 사이 순서는 Azure/state를 관측한 operator가 확인하며 단순 URL이 실제 cleanup을 증명하지 않는다.

| Operation | 필요한 predecessor evidence |
| --- | --- |
| `foundation:plan` / `foundation:apply` | 별도 승인된 operator bootstrap 완료, local-state 보호, backend/CI identity/RBAC, current paid preflight; apply는 검토된 plan/scope 근거 |
| `environment:plan` / `environment:apply` | foundation 완료/output 일치, Korea Central Grafana major/SKU 확정, 승인된 exact inputs; apply는 검토된 plan/scope 근거 |
| `environment:destroy` | platform writers/controller/owned resources/PVC·disk·backup 정리 또는 승인된 보존 inventory |
| `foundation:destroy` | environment cleanup 및 residual inventory, Gabia 대체 authoritative DNS 복구/전파 확인, KV soft-delete 처리 |

`apply`/`destroy`는 각 dispatch 안에서 fresh plan을 만들고 그 saved plan만 apply한다(`destroy`는 `plan -destroy`).
별도 plan dispatch의 plan 파일은 재사용하지 않는다. 승인된 inputs에 대한 fresh plan/apply를 함께 승인해야 하며,
새 diff가 별도 검토를 요구하면 dispatch하지 않는다. Plan binary/JSON은 private temp directory에서만 취급하고
로그에는 source address/action만 출력한다. Workflow는 계획의 비용/리소스 안전성을 대신 승인하지 않는다.
`P6_POSTGRESQL_ADMINISTRATOR_PASSWORD`는 별도 승인된 초기화 절차로 `azure` Environment secret에 설정하고
environment stack에서만 ephemeral `TF_VAR`로 전달한다. 새 long-lived Azure credential을 만들지 않는다.

Runner는 source/lockfile만 private directory에 복사하며 임의 CLI args/auth/cache를 상속하지 않는다.
실패 시 마지막 Terraform 단계와 allowlisted `state list` address를 출력한다. Init 실패/locking 문제로 state 조회가
불가능할 수 있으며 raw error/provider output은 secret 노출 가능성 때문에 출력하지 않는다. 자동 destroy/force-unlock은 없다.
Operator는 run URL/source/단계/UTC를 기록하고 기존 승인된 read-only 접근으로 다음을 확인한다.

1. 두 stack backend key와 lease/lock, state serial 및 실패 전후 resource address를 private하게 대조한다.
2. 승인된 project RG의 actual resource ID/provisioning state, AKS node RG와 Monitor managed RG,
   disk/IP/backup/soft-deleted KV/identity/FIC/RBAC/state backend를 inventory한다.
3. State에 없는 partial resource도 확인하고 새 plan/승인 또는 cleanup action을 결정한다.
   Runner timeout/cancellation의 로컬 파일 정리는 disposable runner 경계에 의존하며 Azure rollback은 아니다.

Gate의 10시간 UTC window/같은 Korea calendar day/$50 상한은 승인 범위 검증이다. Actual spend 제한이나 자동 teardown 보장이 아니다.
Job timeout(120분)도 paid environment 전체 수명이 아니다. Operator가 당일 deadline과 cleanup 여유 시간을 관리한다.

## 남은 paid blocker / 별도 승인 범위

- Grafana: Korea Central Standard + 12/13 조합은 not verified. 과거 URL/API version 부재 자체를 별도 blocker로 삼지 않는다.
- DNS: PR #24의 대체 authoritative DNS, Gabia 전환·복구 지연, observed TTL 및 same-day teardown 충돌이 미해결이다.
  이번에는 zone 생성/Gabia/Cloudflare mutation을 하지 않았다.
- Operator storage: primary checkout의 실제 bootstrap state 보관·파일 권한, 최신 암호화 백업과 복호화 수단 접근은 paid preflight에서 확인한다.
- Runtime/OIDC/RBAC/backend/잔존·실제 비용은 실행 전/후 별도 evidence가 필요하다.

사용자는 blocker 해소 근거와 exact merged source/config를 본 뒤 **P6 campaign**의 비용(추정 범위와 세전 $50 상한),
실행시간(당일 최대 10시간 및 cleanup 여유), explicit/managed implicit resources, operator bootstrap과 CI plan/apply,
temporary RBAC/secret 초기화/platform 범위, DNS 전환·복구와 필요 시 보존 비용/기간,
platform → environment → foundation → bootstrap destroy/finalization을 별도로 승인해야 한다.
Same-day DNS 복구가 불가능하면 해당 보존 예외를 먼저 명시하고, 24시간 초과 유지에는 새 승인이 필요하다.
이 준비 PR은 그 어느 항목도 승인하지 않으며 P7을 포함하지 않는다.
