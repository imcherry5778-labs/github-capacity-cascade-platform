# P8-W1 Azure execution evidence

상태: **측정·원복·P8-owned cleanup 완료, 독립 exact-head review 대기**.
승인 HEAD `033a53fba2a5e4f6196fa5c60654c6648f12f5b5`와
[승인 comment6477075377](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/40#issuecomment-6477075377)의 범위로 실행했다.
원래 CI40741973677 성공을 확인한 뒤 진행했다. 같은 범위의 최소 adapter 수정 뒤 최종 execution SHA는
**`bc0a4def4e6b43cf1a748b045869218214730df9`**다.
최종 제출 commit에는 test clock 고정·문서·evidence만 추가됐으며 paid runtime source는 같다.

[초기 incident/postmortem](../../incidents/p8-controlled-cascade.md)에 영향·mechanism·confounder·제한사항을 설명한다.
[execution.json](execution.json)은 승인/source lineage, image digest, paired 결과, cleanup와 비용 관측을 연결한다.
기존 `source-preparation.json`, `approval-request.md`와 management/cost/pricing 파일은 **실행 전 historical record**로 유지했다.
그 파일의 `미승인/not executed`는 당시 상태이며 현재 판정은 execution record를 따른다.
Hostname correction/review, 실패·negative evidence를 덮어쓰지 않았다.

## Raw 보존과 재검토

[raw-evidence.tar.gz](raw-evidence.tar.gz)는 202개 파일, 원본 총8,057,509 bytes다.
JSON/JSONL 및 P7 runner의 원래 scalar timing/status 파일을 byte 변경 없이 담았다.
Archive SHA256: `8d5681eba3f7d31282ab7bd24a3e226577255ec966ca877b9d871d4fd1d6970f`.
[raw-index.json](raw-index.json)에 모든 상대 경로·byte 수·SHA256이 있다.
Protected directory·credential·private local 경로·full proxy dump는 포함하지 않는다.
실제 administrator/DB password, PAT2개, ACR token의 원문/base64/URL encoding과 private directory 경로를
publish 대상 raw/문서에서 검사한 뒤 보호 사본을 제거했다. File removal이며 physical erasure를 주장하지 않는다.

| Archive 경로 | 의미 |
| --- | --- |
| `phase-ledger.jsonl`, `kubernetes-delta.json` | Source별 실행 순서, cluster/owner/Argo/정상성 delta |
| `normal/`, `healthy-gate/`, `healthy-controls.json` | 정상/healthy 각각9 operation, native deny·controlled DENY·check credential/body exclusion |
| `image-publish.json`, `runtime-provenance.json` | Build source033, runtime imageID/version, 기존 app DB role |
| `shared-mesh-data.json`, `target-*.json` | 원본/적용 mesh data 및 실제 listener/bootstrap/stat mapping |
| `initial-admission.json`, `admission-after-adapter-fix.json`, `confounder-resource-capacity.json` | 실제 init/native sidecar 포함 admission·capacity |
| `*-negative.json`, `calibration-01/02/03/`, `no-retry/` | 실패/invalid 또는 최종 pair에서 제외한 기록 |
| `calibration-04/`, `frozen.json` | 이전 valid calibration과 source/UID 변경으로 사용하지 않은 freeze |
| `calibration-05/`, `frozen-02.json` | 최종 valid calibration·검토·source/config/identity 동결 |
| `no-retry-02/`, `retry/`, `paired-result.json` | 최종 paired run raw/events/path/guards/metrics/review, 동일 fingerprint |
| `postgres-delayed-review.json` | 같은 window 지연 재조회, 상세 IO 관측값과 빈 bin 구분 |
| `restoration.json`, `post-restoration-journey-checks.json`, `final-runtime-delta.json` | Policy 우선 제거·mesh/정상 HTTPS 복귀·stable UID/spec·effective gateway 원복 |
| `credential-cleanup.json`, `image-iam-cleanup.json`, `local-forward-cleanup.json`, `local-finalization.json` | PAT revoke401·login 차단·정확한 image/IAM/owned local 사본 정리 |
| `final-cost-observation.json` | 기존 두 RG ActualCost 조회 성공, P8 actual 증가분은 unknown |

측정 디렉터리의 `mechanism-summary.json`은 cloud 검토 전 상태다.
`reviewed-summary.json`과 hash-bound `confounder-review.json`이 각 run의 valid 판정을 제공한다.
이 파일의 일반적인 `limitations`에는 후속 review가 필요하다는 원래 문구가 유지된다.
최종 판정은 같은 폴더의 실제 review와 `paired-result.json`, cleanup record를 함께 읽는다.
`paired-result.json.cleanup=pending` 역시 pair 생성 당시 상태이며 뒤의 원복 기록을 대체하지 않는다.

Cost-free replay 예시(새 출력 경로를 사용한다):

```bash
mkdir -p .tmp/p8-evidence-review
sha256sum docs/evidence/p8-controlled-cascade-20261029/raw-evidence.tar.gz
tar --no-same-owner --no-same-permissions -xzf docs/evidence/p8-controlled-cascade-20261029/raw-evidence.tar.gz -C .tmp/p8-evidence-review
python3 scripts/azure-cascade.py validate .tmp/p8-evidence-review/calibration-05 .tmp/p8-calibration-replay.json
python3 scripts/azure-cascade.py pair .tmp/p8-evidence-review/no-retry-02 .tmp/p8-evidence-review/retry .tmp/p8-evidence-review/frozen-02.json .tmp/p8-pair-replay.json
```

[offline-validation.json](offline-validation.json)은 archive 전체 checksum과 추출된 두 run의 재검증 결과다.
[validation.json](validation.json)은 직접 회귀와 `make static` 결과를 기록한다.
최종 exact HEAD의 GitHub check는 같은 Draft [PR40](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/40)의 check surface에서 확인한다.

## 판정 경계

- 600 logical operations 각각, client attempts600→1,151, dispatched checks628→1,177,
  admitted53→51, active rejection575→1,126, direct sentinel 모두 성공이다.
- Calibration 뒤 동일 source/replica/config/demand/transport를 동결했다. 두 measured run만 최종 비교한다.
- PostgreSQL CPU/connections/storage/aggregate IO, Forgejo/sidecar CPU/memory·direct latency,
  node pressure/scheduling, HAProxy queue/error/retry, HPA metric/controller/headroom을 같은 window에 확인했다.
- 일부 상세 IO minute bin은 여전히 비어 있다. Stable proxy cgroup throttle file도 unavailable이다.
  이 값을 0으로 대체하거나 모든 confounder가 완전히 배제됐다고 주장하지 않는다.
- Target의 managed default `reset-before-request` retry2는 유지·기록했다. Ingress와 HAProxy retry0 및 client1→2와 구분한다.
- Public 측정은 hostname 검증 HTTPS/native PAT, direct sentinel은 loopback Pod tunnel/native PAT다.
  DNS는 P7처럼 process-local override를 사용했고 ordinary DNS 정상성을 주장하지 않는다.
- P8-owned 변경은 정리했다. 기존 environment·Owner2개·admin version2·fixture 기록은 승인대로 보존했다.
  Environment10/30 10:30 KST, Foundation/Bootstrap10/31 00:33 KST 기한은 연장하지 않았다.
  전체 environment zero residual/teardown, P9 recovery, P10 isolation 결과는 없다.
