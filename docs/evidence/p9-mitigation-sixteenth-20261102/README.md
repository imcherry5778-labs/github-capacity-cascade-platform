# P9 제16차 — CPU 준비 통과, 최종 telemetry deadline 실패

**단일 campaign 종료 / initialize 재호출0 / KEDA·calibration·measured·recovery 미도달 / P9 acceptance 미충족**.

[명시 승인](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/41#issuecomment-6570216466),
[source review](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/41#pullrequestreview-5731886201),
[security review](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/41#pullrequestreview-5732101835)를 확인했다.
실행 source는 `de600e4d5f439be2f65c087b136ee221290b317d`다. Current main
`d9977cc9046485bb7b47849297ec9769a3629223`의 #46 운영 보정을 적용하되 paid HEAD에 merge하지 않았다.
PR의 실행 전 base snapshot은 `b8dc521af4671306f4b5abfefea244c8143ba5a4`다.
이번 후속 evidence commit은 실행 source가 아니다. Repository implementation source는 변경하지 않았다.

첫 mutation은 **2026-11-02 06:31:46 UTC**였다. 단일 임시 exact-AKS Entra user role과 보호 user kubeconfig를 사용했다.
Image digest `sha256:1c8efc9a1c6916c8478ddbb9cb32c077ee28a663e01f6d968a5f33dca8719c51`과 source label,
actual cluster UID/managed ingress IP/hostname, preparation plan hash를 결합했다.
4-Pod preview는 requests650m/832Mi, limits1450m/1664Mi다. DB hostname/CA verify-full·TLSv1.3/read-only SQL,
target-stage headroom 확인 뒤 HAProxy를 준비했다. Stable Argo는 Synced/Healthy였다.

## 실제 positive와 실패 경계

Normal1과 healthy journey1은 각각 **valid/success/warmup, 9operations/9attempts**다.
Public initialize1은 **06:39:31–06:43:06 UTC / exit1**, source 내부 elapsed210.253초였다.
CPU poll6개 중 fresh3·ready2이며 첫 fresh는 source settling 시작20.769초, 두 advancing fresh sample의
준비 완료는126.985초였다. HPA 회복·같은 UID/Warning 이력·window/quiet 조건을 유지했다.
제15차의 첫 fresh 약286초/ready0과 다른 관측이지만, 단일 비동시 실행으로 GET 순서 교정의 인과 효과를 분리하지 못한다.

| Source 시작 후 | CPU sample age | CPU 준비 판정 | Target signal |
| --- | ---: | --- | --- |
| 20.769s | 24.969s | pending, 첫 fresh | 아직 journey 전 |
| 55.696s / 91.471s | 59.896s / 36.671s | stale, 후보 보존 | 아직 journey 전 |
| 126.985s | 14.185s | ready | healthy journey 진입 |
| 150.841s | 29.471s | ready | 이어진151.757s poll은 uninitialized |
| 182.445s | 61.218s | stale, pending | 이어진183.614s poll은 observed |

Observed signal은 같은 target UID의 inbound overflow rate0/active0/samples2 및 guarded query0이었다.
이때 CPU sample은 stale이므로 source는 healthy initialization 완료로 승격하지 않았다.
마지막 `telemetry_configuration`에서 전체 telemetry deadline이 소진됐다. 보호 traceback을 값 없이 분류한 결과,
ingress `config_dump?resource=dynamic_route_configs` 명령에 남은 subprocess budget은 **0.046233초**였다.
`TimeoutExpired / command_timeout`은 이 축소 budget의 결과이며 일반15초 Azure API timeout의 증거가 아니다.
Source failure event의 `ready_for_keda_authentication`·`runtime_preflight_passed`는 모두 false다.

CPU export/cache와 local collection 각각의 지연 기여율은 unknown이다. Source의 fail-closed 판정과 budget 적용은
이번 timestamp·payload·trace 분류에 부합하며, 이를 고칠 correctness bug나 acceptance 완화 근거는 확인하지 못했다.
따라서 source 수정·구현을 그대로 재현하는 새 test를 추가하지 않았다. 기존 exact-source test/CI를 재사용하고
실제 raw의 순서·freshness·failure/consumption을 cost-free로 대조했다.
다음 관측이 필요하면 기존 collector/operator에서 고정 operation label별 시작/종료·남은 budget을 같은 guard/signal epoch에
연결하는 최소 timing 진단으로 collection 대 sample 갱신의 기여를 구분한다. 완전한 원인 규명을 새 진입 gate로 추가하지 않는다.
이미 실패한 initialize를 반복하거나 timeout/freshness를 늘리는 근거로 쓰지 않는다.

## 종료·원복·보안

승인된 initialize≤1을 소비해 campaign을 닫았다. Optional post-settling metrics GET은 **미실행**이다.
이번 실패는 CPU settling timeout이 아니므로 해당 진단 권한을 확대 해석하지 않았다.
KEDA UAMI/FIC/role·SA/template mutation과 apply/restore restart는0/0, calibration0/measured 각0이다.
누적은 **campaign16 / public initialize13 / healthy4 / started-invalid calibration2 / measured 각0 / KEDA restart3/3**이다.
남은 calibration2/measured 각1은 closed campaign에서 사용할 수 없고 다음 campaign으로 이월하지 않는다.

CUSTOM exact UID 제거 → shared CM UID/data guarded 원본 복원 → owned namespace 삭제 뒤 final native verify1/exit0의
5개 CLI check를 확인했다. Verify는 create와 달리 structured operation events를 생성하지 않는다.
PAT30·31 각각 DELETE204/재사용401/list0, fixture 로그인 차단/Basic401을 확인했다. Fixture DB records는 보존했다.
Live reference0·exact digest/tag set 확인 뒤 소유 ACR image/local tag를 제거하고 각각 부재를 재확인했다.
원래 Owner2개 보존과 임시 AKS role 제거, stable Pod UID/spec/Ready/zero-restart·Argo/Deployment/KEDA spec,
admin/DB Secret UID/data·admin CSI 버전, bound PVC/PV와 기존 Azure Disk IDs·고정4RG inventory를 확인했다.
**13개 cleanup check가 모두 true**다. Bound storage는 현재 관측 및 동일 stable Pod spec·기존 Disk inventory와 연결했으며
이번에 새로 얻지 않은 사전 PVC/PV UID snapshot을 얻었다고 주장하지 않는다.

같은 campaign 부모가 forwarding handle을 준비부터 cleanup까지 소유했다. Start1/poll603/failed poll0,
의도한 TERM/wait(-15), parent exit0과 두 owned PID 부재를 확인했다. 실제 measured 직전 direct semantic probe는 미도달이다.
따라서 이 liveness를 native sentinel 또는 제14차 실패 원인 해결의 증거로 해석하지 않는다.

Local Docker daemon 부재는 기존 rootless Podman으로, Argo client version nesting은 parser로 교정했다.
Cleanup의 socket import와 ACR tag/absence 응답 형식 가정도 교정했다. 실패 event·최초 intent를 보존하고
normal/initialize/healthy/final verify나 이미 완료한 PAT 폐기를 반복하지 않았다. Source/ledger 횟수는 초기화하지 않았다.
새 KEDA private action은 compile만 했고 호출하지 않았다. Action별 named Secret GET은 bootstrap/DB 준비/각 보존검증의4회뿐이다.

[별도 admin 회전 결과](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/41#issuecomment-6569049379)를 재사용했다.
현재 admin CSI version `712ccfb64ac7409789fa78ec2ddcf7f2`는 유지됐다. Old credential/transcript는 열지 않았고
추가 회전·KV write·global logout/session DB mutation은 수행하지 않았다. Session/output unknown과 기존 incident 한계는 남는다.

## 비용·기한·검증

Latest bounded preflight는 **06:22 UTC**, posted Two-RG **KRW150,587.6256920534**,
누적 planning **USD263.1902866454506 / 승인 세전 review cap275**다.
기존260.896801 모델에 이전 posted 관측 대비 양수 delta만 반영했다. 이미 포함된 보존/overlap·과거 allowance·remediation5·
이번 variable10을 다시 더하지 않았다. 1,200KRW/USD는 planning 가정이며 시장 환율·잔액·billing hard cap이 아니다.
Scope/rate/retention 가정에 유의미한 변화가 없어 #46에 따라 이 관측·모델을 재사용했으며 실행 후 비용 GET은 반복하지 않았다.
현재 P9 단독 실비와 최신 미반영 사용량/잔액은 **unknown/shared/delayed**다. 비용0 또는 잔액을 주장하지 않는다.

Environment **2026-11-05 10:30 KST**, Foundation/Bootstrap **11월6일00:33 KST**는 유지한다.
전체8045초·initialize/run/drain/rollback3065초·run/drain/rollback2220초의 strict reserve도 유지했다.
새 보존·전체 teardown·merge/P10은 수행하지 않았다. Source 교정이 필요하면 cost-free 영향 검증 뒤 독립 exact-head review가 필요하고,
새 paid campaign은 별도 exact-SHA/횟수/비용/기한 승인이 필요하다. 이번 결과는 다음 실행 승인이 아니다.

[execution.json](execution.json), [comparison.json](comparison.json), [validation.json](validation.json),
[raw-index.json](raw-index.json), [sanitized raw archive](raw-evidence.tar.gz)에 검증 범위와 한계를 연결한다.
Archive35개 member의 path/size/SHA256을 다시 읽어 확인했고 과거15개 archive byte/hash를 보존했다.
현재 실제 password/PAT·관측된 Azure/ACR token과 encoding scan matches0, private path0이다.
Secret object/value·kubeconfig·private trace·raw account/tool output·operator program은 공개하지 않았다.
이 scan은 과거 tool-output 노출을 취소하거나 session containment를 입증하지 않는다.
소유 RAM/보호 evidence/export program의 파일564개를 제거했고 global Azure CLI cache·무관한 image cache는 보존했다.
물리적 secure erasure나 전체 Environment zero residual은 주장하지 않는다. Final exact evidence HEAD CI는 기존 PR 결과 comment에 기록한다.
