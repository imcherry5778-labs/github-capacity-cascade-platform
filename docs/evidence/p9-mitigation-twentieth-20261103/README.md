# P9 제20차 — calibration2회 invalid / owned cleanup 완료

실행 source는 `8741cf275888ee5760c6b22562182c13105b417e`다. [제20차 사용자 승인](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/41#issuecomment-6593805821)과 [exact-source review](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/41#pullrequestreview-5746387442)에 따라 같은 Mac/branch/Draft #41에서 단일 campaign을 실행했다. Source 변경은 없다.
**Campaign20 CLOSED / P9 acceptance 미충족. Calibration2회 모두 invalid이며 freeze·C0–C3 measured·유효 비교/recovery는 없다.**

## 실제 실행과 관측

- Normal/healthy journey 각각9 operations/9 attempts가 valid/success다. Public initialize1·retry0·exit0, CPU poll10·telemetry poll3·Prometheus13/25다.
- 기존 AKS1.36.4/asm-1-30·PG17·고정2노드·4RG/34개 resource를 재사용했다. Actual actor/subscription, source/image/plan·권한·native TLS·DB verify-full/read-only SQL 및 cleanup reserve를 확인했다. Source-bound image는 `sha256:1e8abd90a9d85348a73d93f10a13dda078b94d82a5b9b4d7f5159265faaaf6bf`다.
- KEDA2.19.0-25 새 operator Pod2개의 identity injection, exact ScaledObject/HPA owner·selector와 실제 external metrics API 응답을 확인했다. 초기2:46 UTC empty-metric Warning으로 첫 full gate는 거부했다. 현재 HPA 회복 뒤 별도의3개 actual snapshot gate가 통과했으며 이전 negative를 지우지 않았다.

| Calibration | 발행 / 예정 | Unissued | Client attempts | Monitor failure / origin | Complete snapshots | 새 UID 관측 Ready→failure |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| calibration-C3-1 | 725 / 1800 | 1075 | 1328 | +142.694s | 8 | 89.606s |
| calibration-C3-2 | 700 / 1800 | 1100 | 1284 | +139.050s | 15 | 82.715s |

두 실패 cycle의 네 per-Pod 응답은 rate/active/timestamp/count 모두 두 target을 포함했다. 다섯 번째 동일 instant-response/evaluation clock의 guarded row도 각각6.517724 / 6.291493으로 존재했다. Rate/fresh-rate/inventory/up count=2, up minimum=1이며 raw maximum age는25.108 / 33.570초였다. 두 run의 fifth envelope 총13개는 strict extraction·canonical/envelope provenance·UTC/monotonic budget 검증을 통과했다. 이는2m query의 실제 부분 evidence이며 유효 measured readiness나 원자적 ingestion 보장이 아니다.

**남은 blocker는75초 안의 신규 UID joint-readiness 입증 실패다.**
- Run1: 첫 Ready 관측 뒤 약34.7초에 첫 CPU metric(window14.640s)이 나타났고 timestamp가 반복됐다. 마지막 complete snapshot은 Ready+70.584초에도 AMW warming/resource initializing이었다.
- Run2: 첫 resource metric은 Ready+45.003초에 관측됐다(timestamp03:10:25Z, window42.576s). Ready+63.750초에는 AMW가 observed였지만, Ready+73.149초까지 같은 CPU timestamp가 유지됐다. Age42.052초는2×window85.152초 안이었지만 **진전한 sample을 관측하지 못했으므로** source가 not-ready를 유지했다.
- 두 failed-cycle AMW signal을 원래 응답/clock으로 replay하면 통과한다. 반면 그 시각의 resource deadline operand는 각각89.606/82.715초>75초이므로 source가 거부한다. Failed-cycle resource guard 자체는 snapshot으로 emit되지 않아 첫 throw의 metric 값은 unknown이다. Deadline-only replay를 실제 누락 guard의 재현으로 주장하지 않는다.
- 추가로 run2의 origin+112.015초 snapshot을 saved-end clock으로 평가하면 per-Pod sample의 strict60s freshness negative가 있다. Query-time/전체 snapshot 종료시각을 구분했고 threshold를 완화하지 않았다. 두 original/sanitized saved `validate`는 모두 `failed/incomplete run`을 반환한다.
- Metrics API 최초 export/cache/하위 kubelet 기여, 관측 사이에 발생했을 수 있는 다음 timestamp는 unknown이다. Averaging window를 API refresh cadence라고 단정하지 않는다. 제18차 미기록 predicate/제19차 원래 ingestion 상태도 소급 확정하지 않는다.

## 같은 source의 bounded operator 교정

Run1 뒤 [Azure CLI login mode](https://azure.github.io/kubelogin/concepts/login-modes/azurecli.html)의 per-command credential 경로를 확인하고, 같은 Entra user/audience/cluster/RBAC를 검증한0600 user kubeconfig에서만 credential을 재사용했다. Global login/권한/source·5초 query/30초 collection·최대5개 requests/collection·raw freshness60s·joint75s는 유지했다. 단일 GET은0.722→0.205초, run 전3개 complete collection은8.223/9.010/10.049초였다. Cleanup 전 원래 exec 경로를 복원했다. 이것은 AMW/Metrics API 자체를 교정했다는 뜻이 아니다.
삭제된 전 run Pod의2m range series는 unknown UID로 거부하고 range 만료를 기다렸다. 이 pre-call gate는 calibration2를 소비하지 않았다. 이후 실제2번째 calibration만 실행했으며 추가 calibration·initialize/measured retry는 없다.
CLI parser/숫자형 quota 처리, known native paths 진단 분류, 제가 생성한 bytecode로 인한 pre-call clean gate, ACR absence error의 대소문자 분류를 같은 operator 범위에서 고쳤다. 실제 credential 값/argv/stderr/private trace는 공개 archive에서 제외했다. 기존 공개 승인 문서 read의 tool 결과에 subscription UUID가 포함된 출력 실수는 있었다. 공개 artifact에서는 UUID와 소유 절대 경로를 치환했다. 추가 credential 회전·전역 cleanup을 만들지 않았다.
초기 KEDA full gate는 buffer의 snapshot을 예외 전에 저장하지 못했다. 실패 predicate와 K8s Warning metadata는 보존했고, 이후 gate/두 calibration은 append-only 기록했다. 당시 KEDA empty의 정확한 operand는 unknown이다.

## Owned cleanup와 남은 경계

CUSTOM exact UID 제거→shared CM UID/data guarded 원복→namespace/Secret/controls 제거, KEDA 원래 SA annotation/template·Ready2 복귀/restore restart1, 전용 AMW role/FIC/UAMI 제거가 완료됐다. Stable Argo spec/revisions·Pod/Deployment UID/spec·CSI·PVC/PV UID/spec/Bound와 named admin/DB Secret UID/value를 대조했다. Final native verify1은 integrity4개 통과와 기존 console-only `missing_/data/log` 진단의 정확한 분류를 포함한다.
PAT38/39 각각 DELETE204·재사용401·token list0·login401이다. Fixture 계정/저장소를 삭제하지 않고 login만 차단했다(별도의 post-cleanup SQL 재조회는 하지 않음). 소유 image tag/digest는 live reference0·공유 tag 부재 확인 후 제거했고, exact digest 재조회는 `MANIFEST_UNKNOWN`이었다. 원래 Owner2개·4RG/34개 ARM ID 집합 보존, 임시 AKS role 부재와 같은 parent의 forwarding TERM/wait(-15), parent exit0을 확인했다. 전체 환경 zero residual이나 물리적 secure erasure를 주장하지 않는다.

누적 **campaign20 / initialize17 / healthy8 / started-invalid calibration6 / measured 각0 / KEDA apply·restore6/6**이다. Campaign19는 계속 CLOSED/invalid이며 과거 raw/ledger와 미사용 권한 소멸을 보존했다.
첫 mutation 전 projection은 기존 retained-resource/lag/overlap/cleanup model285.3567 + 이번 variable estimate5 = 약USD290.3567이었다. 실비/잔액은 shared/delayed/unknown이며 새 billing GET은 반복하지 않았다. 사용자 결정대로 USD290 초과 자체는 campaign20의 NO-GO가 아니었고 새 숫자 cap/무제한 권한은 만들지 않았다. Cleanup reserve1800초/whole reserve8045초와 고정 resource 범위를 유지했다. 실제 최대 Pod4, requests/limits CPU650/1450m·memory832/1664Mi였다.
Environment `2026-11-05T01:30:00Z`, Foundation/Bootstrap `2026-11-05T15:33:00Z`는 그대로다.75초 안의 advancing fresh resource sample+AMW readiness를 입증하는 현재 계약을 만족하지 못했으며 acceptance/source 변경은 별도 판단 사항이다. 새 유료 campaign·비용 증액·기한 연장·merge/P10은 수행/제안하지 않는다.

[execution](execution.json), [comparison/gap](comparison.json), [validation](validation.json), [raw index](raw-index.json), [sanitized selected raw archive](raw-evidence.tar.gz)를 함께 본다. Archive35개 path/size/SHA256·normal/healthy9개씩·두 negative replay·publication scan을 검증했다. Original selected checksum과 공개본 checksum을 구분하며 subscription은 canonical zero UUID, 절대 경로는 placeholder로 치환했다. Source exact-head CI4 success는 재사용하고 evidence-only HEAD/CI는 #41 결과 comment에 연결한다.
