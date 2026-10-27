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

P6 Bootstrap local state는 승인된 operator가 최종 cleanup까지 책임진다. Terraform resource/backend 소유권은 변경하지 않는다. CI identity에는 bootstrap 관리 권한을 주지 않는다.

1. 장기간 유지되는 primary Git checkout의 `infra/terraform/bootstrap/`에서 implicit local backend를 사용한다. `terraform.tfstate`와 `terraform.tfstate.backup`은 해당 디렉터리에 둔다. 일회성 Agent worktree나 GitHub runner로 옮기지 않는다. Foundation/Environment는 기존 Azure Blob remote backend를 유지한다.
2. Terraform 실행마다 `umask 077`을 적용하고 state/backup/local input/crash 파일의 owner-only `0600` 권한을 확인한다. 기존 `.gitignore`의 `*.tfstate`, `*.tfstate.*`, `*.tfvars`, `.terraform/` 제외 규칙을 사용한다. State가 존재하는 checkout에서는 `git clean -fdx`처럼 ignored 파일을 지우는 정리 명령을 사용하지 않는다.
3. **추가 GnuPG 암호화 백업, passphrase·pinentry 설정, 별도 백업 경로·복호화 점검을 P6 실행 조건으로 요구하지 않는다.** 사용자는 개인 실습에서 추가 GnuPG 백업을 생략하기로 선택했다. 로컬 state 유실·노출 위험은 남는다. 기존 파일시스템 스냅샷이 이 경로를 포함하는지와 state 복구 가능성은 **not verified**다. 스냅샷의 존재만으로 실제 state 보존·복구 성공을 주장하지 않는다.
4. 실제 apply 후에는 state 파일이 생성됐는지와 Git 추적 제외·파일 권한을 확인한다. 최종 destroy까지 **동일한 최신 local state**를 보존한다. State가 유실·손상되면 Terraform 자동 destroy를 성공으로 가정하거나 임의로 재생성하지 않는다. Azure actual resource/RBAC inventory를 확인하고 별도 복구·정리 판단을 받는다.

이전 `tests/e2e/test-bootstrap-state-protection.py`의 GnuPG dummy 암호화·복호화 시험은 과거의 **dummy 절차 점검**이다. Operator의 실제 백업 수행, 별도 passphrase 입력 또는 Azure resource recovery를 검증한 것이 아니며 이번 P6의 필수 preflight가 아니다.

로컬 원본 state/input/crash/log는 암호화되지 않을 수 있다. `.gitignore`와 owner-only 권한은 암호화도 데이터 유실 방지도 아니다. 따라서 디스크 접근·유실 시 민감정보 노출 및 state 기반 정리 불능 위험이 남는다.

`.gitignore`의 state/plan/tfvars/crash 제외는 실수 방지 보조다. Checkout에 보관하는 state를 Git에 추적·commit하지 않는다.
CI에는 allowlisted non-secret backend coordinates만 수동 전달한다. `terraform output -json` 전체/state pull, credential/password, state snapshot, plan binary/JSON, `.terraform`, provider log를 Git/CI artifact/log로 보내지 않는다.

Cleanup은 platform → environment → foundation → bootstrap이다. Foundation DNS delegation 복구·전파와 downstream state/lock/evidence 보존이 끝나기 전 bootstrap backend/CI trust/RBAC/RG를 지우지 않는다. Bootstrap은 같은 operator가 최신 local state로 마지막 제거한다. DNS 보존이 필요하면 bootstrap도 유지한다. 잔존·soft-delete·identity/RBAC·state backend finalization은 aggregate preflight를 따른다.

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

Trusted operator는 별도 명시적 P6 user approval을 받은 뒤에만 아래 repository secret과 variable을 설정한다.
이 source-only log exposure fix에서는 variable/secret을 설정하지 않고 workflow도 dispatch하지 않는다.

- Repository secret `P6_EXECUTION_CONFIG_B64`: `backend`, `foundation`을 가진 UTF-8 JSON object를
  줄바꿈 없는 standard Base64로 인코딩한 문자열. Foundation operation에서는
  `environment`를 생략할 수 있고, Environment operation에서는 세 object가 모두 필요하다.
  Backend에는 bootstrap output에서 `storage_account_name`, `container_name`, `tenant_id`, `client_id` 네 필드만 옮긴다.
  포함한 stack object는 각 `variables.tf`의 모든 non-secret input을 정확히 포함한다. 허용되지 않은 key나
  불완전한 stack 입력은 거부하며, `environment`가 있으면 operation에 관계없이 cross-stack identity/RG도 검증한다.
  `postgresql_administrator_password`는 포함하지 않는다. Backend key/auth flag는 source가 고정한다.
  Account/resource names, SKU, versions, CIDR, authorized IPs, observability 값은 실제 승인 inventory와 대조한다.
  Config 구성이 바뀌면 전체 config SHA256과 해당 exact inputs/operation의 승인을 다시 받아야 한다.
- Repository variable `P6_CAMPAIGN_APPROVAL`: 아래 **비활성 template**을 actual user approval/evidence로 채운 JSON object.
  Repository/Environment에 같은 이름의 variable을 중복 정의하지 않는다. Config digest는 canonical JSON
  (sorted keys, compact separators, ASCII encoding)의 SHA256이며
  아래 local command로 계산한다. Digest는 Base64 문자열이 아닌 decoded JSON에 대해 계산하므로
  같은 JSON의 key 순서/공백/인코딩 표현을 바꿔도 기존 canonical digest를 유지한다.
  Approval link를 적는 행위 자체가 user approval은 아니다. 관리 operator가 원문 승인과 exact scope를 대조할 책임이 있다.
  Variable write 권한은 trusted operator 경계이며 workflow가 링크 내용의 승인 의사를 판정하지는 않는다.

Operator가 보관한 private JSON 파일을 `$config_file`로 지정하고 shell tracing을 끈 local shell에서
다음 형식으로 digest만 확인한다. JSON/encoded 문자열을 command argument, shell history, CI log에 붙여 넣지 않는다.

```sh
P6_EXECUTION_CONFIG_B64="$(base64 -w0 < "$config_file")" python3 scripts/azure-execution.py digest-config
```

새 reviewed/merged main과 current preflight에 대한 **새 campaign 승인 후**, 동일한 파일을
`base64 -w0 < "$config_file" | gh secret set P6_EXECUTION_CONFIG_B64 --repo imcherry5778-labs/github-capacity-cascade-platform`
형식으로 repository secret에 전달한다. 같은 이름의 Environment/organization secret으로 덮어쓰지 않는다.
Obsolete repository variable `P6_EXECUTION_CONFIG`는 새 dispatch 전에 trusted operator가 삭제하고 삭제 결과를 확인한다.
Workflow/Python은 이 variable을 참조하거나 fallback하지 않으며 새 secret이 없거나 malformed이면 실패한다.
이 변경은 variable/secret 실제 수정 권한이나 기존 Plan-only campaign의 재사용을 승인하지 않는다.

Base64는 암호화나 비밀 보호 수단이 아니다. Encoded 문자열의 runner env 표시는 GitHub Secret masking에 의존한다.
원본 JSON을 secret 값으로 직접 넣는 방법도 structured data redaction 한계가 있다
([GitHub secure use](https://docs.github.com/en/actions/reference/security/secure-use)).
따라서 secret은 gate/execute Python step에만 주입하고 Python 안에서 strict Base64/UTF-8/JSON으로 디코딩한다.
Decoded JSON은 env/job output/artifact/log로 내보내지 않고 기존 exact-input/digest/approval 검증 뒤에만 사용한다.
Terraform stdout/stderr와 payload exception은 계속 비공개로 처리한다. Credential-free regression은 이 source 경계를
검사하지만 실제 GitHub-hosted runner의 Secret masking은 **not verified**이며 별도 승인된 runtime 확인이 남는다.
과거 노출 로그의 retention/redaction 처리도 이 source fix로 완료됐다고 주장하지 않는다.

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

PostgreSQL password rotation은 새 campaign의 `P6_CAMPAIGN_APPROVAL`에
`"plan_policy": "postgresql-password-rotation-1-to-2"`를 명시한다. 이 선택적 필드는 campaign ID와
독립적이며, 지정하면 `allowed_operations`에는 `environment:plan` / `environment:apply`만 허용한다.
승인 config의 `postgresql.administrator_password_version`은 정수 `2`여야 한다. 별도 Plan-only 승인과
이후 Apply 승인 모두 이 정책을 사용하며 기존 source/config digest/operator/time/evidence gate를 그대로 통과해야 한다.

정책은 각 dispatch에서 생성한 **동일 saved plan**의 `show -json`을 메모리에서 검증한다.
`azurerm_postgresql_flexible_server.this`의 유일한 action은 `["update"]`,
`administrator_password_wo_version`은 정수 `1` → `2`여야 한다. 모든 source resource가 정확히 한 번
나타나야 하며 나머지는 `["no-op"]`이고 before/after가 같아야 한다. PostgreSQL의 다른 속성도 모두 같아야 한다.
Resource ID 변경, create/delete/replace/import/move, drift, unknown/deferred action, output 변경,
미완료 plan/check, version·inventory·검증 필드 누락은 Apply 전에 거부한다. 검증 실패는 raw plan이나
provider diagnostics를 출력하지 않으며 자동 재시도·우회하지 않는다. 정책 없는 기존 PostgreSQL mutation도
`environment:apply`에서 거부한다. 초기 create와 destroy의 기존 승인 경계는 유지한다.

실패 진단은 `scripts/azure-execution.py`의 고정 `PLAN_FAILURE_CODES` 사유 코드와 source allowlist에서
확인한 resource address만 출력한다. 예를 들어 `PASSWORD_VERSION`, `UNKNOWN_VALUES`, `ATTRIBUTE_DIFF`,
`RESOURCE_DRIFT`로 거부 범주를 구분하며 version/attribute 값과 raw JSON은 출력하지 않는다.
JSON decode 실패는 `PLAN_JSON_INVALID`, 예상하지 못한 검증 예외는 원문 없이 `VALIDATION_EXCEPTION`으로
표시한다. 이 진단은 Apply 거부와 기존 최상위 generic error/실패 exit를 유지하며 live 실패 원인을 소급 확정하지 않는다.

`RESOURCE_DRIFT` 거부 때만 `drift diagnostic:` 요약을 추가한다. `resource_drift`는 saved state와
refresh 결과의 차이이고 `resource_changes`는 실제 planned action이므로 별도 목록으로 표시한다.
각 목록은 entry 개수와 `shown`/`withheld` 개수, source allowlist의 정확한 resource address와
고정 action(`no-op`, `create`, `read`, `update`, `delete`, `delete,create`, `create,delete`)만 출력한다.
이 action 목록은 **진단용 어휘**이며 rotation 허용 조건을 확장하지 않는다.
각 목록은 최대 34 entries만 검사·출력한다(기존 요약 합계 최대 70줄). 초과 목록은 개수와 `LIMIT`만 기록한다.
Malformed/unallowlisted address·metadata·action은 원문 없이 `withheld`에 합산하고,
중복 source address가 있으면 해당 목록 전체를 숨긴다. 목록 구조가 잘못되면 개수도 `unknown`으로 표시한다.
`OK`는 해당 목록의 address/action 투영이 모두 출력됐다는 뜻이며 guard 통과를 의미하지 않는다.
진단 자체가 실패해도 고정 `unavailable`만 출력하고 원래 `RESOURCE_DRIFT` 거부를 유지한다.

동일 거부 경로에서 유효한 단일 AKS `resource_changes` entry가 있으면 `aks planned diagnostic:` 세 줄을
추가한다(전체 최대 73줄). Planned action은 기존 address/action 요약을 사용한다. 출력 path allowlist는
`default_node_pool[0].upgrade_settings`와 `default_node_pool[0].upgrade_settings[0].max_surge` 두 개뿐이다.
각각 `changed=true/false/unknown`을 출력하고, 블록은 `added/removed/changed/unchanged/unknown`으로 구분한다.
후보 블록 전체를 제외한 AKS before/after 차이는 `other_changed_paths` 개수만 출력한다. Dict key/list index별
leaf 차이를 세며, container 자체의 추가·제거·type 변경은 해당 위치 하나로 센다. Sensitive 필드도 개수에
포함하지만 실제 값, resource ID, 임의 attribute 이름/path, sensitive mask나 raw plan/state는 출력하지 않는다.
`KNOWN`은 이 비교를 완료했다는 뜻이며 benign/computed-only 판정이나 Apply 허가가 아니다.

AKS `after_unknown`이 없거나 후보 경로/상위 경로의 mask가 unknown/malformed이면 세 진단 모두 `unknown`이다.
후보 외 경로에 unknown이 있으면 후보 비교는 유지하되 `other_changed_paths`는 `unknown`으로 표시한다.
양쪽 default pool이 각각 하나가 아니거나 후보 블록/schema 형태가 맞지 않아도 추측하지 않는다. 후보 블록의 missing/null/빈 list는
absent로 취급한다. 다른 경로 비교는 최대 10,000개 위치/깊이 64로 제한하며 초과하면 `unknown`이다.
미허용 metadata/action, 중복 address 또는 목록 제한으로 숨긴 AKS는 추가 진단도 출력하지 않는다.

[AzureRM 5.11.0 default-pool schema](https://github.com/hashicorp/terraform-provider-azurerm/blob/v5.11.0/internal/services/containers/helpers/kubernetes_nodepool.go#L633-L660)는
`upgrade_settings`를 Optional TypeList/MaxItems 1, `max_surge`를 Required로 정의하며 블록은 Computed가 아니다.
[Flatten 구현](https://github.com/hashicorp/terraform-provider-azurerm/blob/v5.11.0/internal/services/containers/helpers/kubernetes_nodepool.go#L1360-L1384)은
비어 있지 않은 ARM `MaxSurge`를 state에 기록한다. Source의 블록 생략과 planned update 사이의 관계는
**후보 가설**이며 다음 별도 승인 Plan의 실제 진단으로 확인해야 한다. AKS Terraform 설정은 변경하지 않는다.

[이전 Plan](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/actions/runs/40496488152)의
drift 23건은 별도 strict blocker다. Planned AKS/PostgreSQL update 2건 및 no-op 32건과 혼동하거나,
drift를 근거 없이 computed-only/benign으로 분류하지 않는다. 이 진단으로 password version 1→2 충족,
PostgreSQL 다른 attribute 불변 또는 새 credential 활성 여부를 주장할 수 없다. 기존 전체 guard가 그대로 적용된다.
JSON 계약은 [Terraform 1.16.7 JSON plan 구현](https://github.com/hashicorp/terraform/blob/v1.16.7/internal/command/jsonplan/plan.go)과
공식 JSON format의 drift/change 구조 및 action 어휘를 재확인했다. Raw plan/state/JSON이나 artifact는 추가하지 않는다.

검증 근거는 [Terraform JSON format](https://developer.hashicorp.com/terraform/internals/json-format)과
[AzureRM 5.11.0 PostgreSQL resource](https://github.com/hashicorp/terraform-provider-azurerm/blob/v5.11.0/internal/services/postgres/postgresql_flexible_server_resource.go)다.
Source pin은 Terraform `1.16.7` / AzureRM `5.11.0`이며 provider의 version 변경 update 경로를 확인했다.
Credential-free regression은 허용/거부 및 saved-plan 연결을 검증한다. 실제 provider JSON에서 before version과
전체 변경 속성을 확인할 수 있는지는 **not verified**이며, 향후 별도 승인된 Plan에서 확인 불가하면 blocker다.
이 source-only 변경은 secret/config/approval variable 수정, workflow dispatch 또는 live rotation을 승인하지 않는다.

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
- Operator storage: primary checkout의 실제 bootstrap state 위치·파일 권한·보존 경계는 paid preflight에서 확인한다. 별도 GnuPG 백업·passphrase는 필수 gate가 아니다.
- Runtime/OIDC/RBAC/backend/잔존·실제 비용은 실행 전/후 별도 evidence가 필요하다.

사용자는 blocker 해소 근거와 exact merged source/config를 본 뒤 **P6 campaign**의 비용(추정 범위와 세전 $50 상한),
실행시간(당일 최대 10시간 및 cleanup 여유), explicit/managed implicit resources, operator bootstrap과 CI plan/apply,
temporary RBAC/secret 초기화/platform 범위, DNS 전환·복구와 필요 시 보존 비용/기간,
platform → environment → foundation → bootstrap destroy/finalization을 별도로 승인해야 한다.
Same-day DNS 복구가 불가능하면 해당 보존 예외를 먼저 명시하고, 24시간 초과 유지에는 새 승인이 필요하다.
이 준비 PR은 그 어느 항목도 승인하지 않으며 P7을 포함하지 않는다.
