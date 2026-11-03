# P9 제15차 — CPU settling timeout, owned 원복과 후속 source 교정

**단일 campaign 종료 / normal positive / public initialize 실패 / healthy·KEDA·calibration·freeze·C0–C3 measured·recovery 미도달 / P9 acceptance 미충족**.

실행 source는 `7fc49ad391cddf70d9c901046901ed24917a2095`, main은
`cbb1a222478b867167b5572f103ab23139c308dc`다.
[사용자 명시 승인](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/41#issuecomment-6567553025),
[독립 source review](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/41#pullrequestreview-5731350400),
[통합 요청](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/41#issuecomment-6567397692)을 확인했다.
이 후속 source/evidence HEAD는 실제 실행 source와 다르며 새 유료 실행 승인이 아니다.

첫 external mutation intent는 **2026-11-02 11:32:05.719 KST**다.
Actual actor/subscription·AKS/PG·RBAC/quota와 비용 GET은 **11:27:08–11:27:14 KST**,
네 fixed RG inventory는 **10:59:26 KST** 관측을 재사용했다. 이를 모두 첫 mutation 직전 새 GET으로 표시하지 않는다.
첫 mutation gate에서 exact clean source·실제 plan·남은255475.87초와 전체8045초 reserve를 확인했다.
임시 exact-AKS Entra user role 하나와 보호 user kubeconfig를 사용했고 admin credential을 발급하지 않았다.

## 실제 준비와 중단

Source revision label을 확인한 image digest는
`sha256:458ecd8711c4fa75c29016bcda3c5385835edb25de76742e324c3bc2d9801abe`,
preparation plan SHA256은 `ec82078689d9d5df7e15a3315ceefbd6c82bb375a8c8efd1f9bab785a008958e`다.
Injected4-Pod preview의 보수적 합계는 requests650m/832Mi, limits1450m/1664Mi다.
Live target/DB Ready 뒤 **11:34:07 KST target-stage headroom**, **11:34:08 KST DB verify-full**,
그 뒤 HAProxy를 생성했다. 실제 managed hostname·CA를 검증한 SQL은 TLSv1.3이다.
Stable UID/spec/image/restart·Secret UID/data/mounted version을 확인했다.

Private operator의 mounted version `id`/DB password-only Secret 형식 가정을 교정했다.
기존 normal context는 actual status `imageID` digest·cluster/Kubernetes/Argo/chart/tool과 비교했다.
첫 실패/projection 기록과 최초 snapshot은 보존했고 source·load 횟수를 초기화하지 않았다.
이 교정들은 initialize 호출 전이다.

Normal1은 **valid/success/warmup, 9operations/9attempts**, 5.416초다.
Public initialize1은 **11:34:53–11:40:00 KST / 307.287초 / exit1**이었다.
보호된 traceback은 `CPU preparation settling timeout`, source failure event는
`readiness_resource_guard / validation_failed / elapsed300.000077초`다.
CPU polling9개 중 fresh1개·ready0개다. HPA는 실제 CPU metric/ScalingActive로 회복했고 retained Warning은
증가하지 않았으나, 마지막 poll의 첫 fresh sample 이후 두 번째 advancing fresh sample을 deadline 안에 얻지 못했다.
**Healthy journey intent0**이다. Invalid calibration이라고 분류하지 않는다. Calibration은 시작하지 않았다.

별도 read-only metric GET1의 응답 시점 sample age는30.786초였다.
과거 poll에는 exact guard UTC/age가 없어 post-failure clock anchor로 계산한 age는 **추정**이다.
Export/cache 지연과 local collection 지연의 실제 기여율은 분리하지 못했다.
Raw 최초 진단의 “fresh gate never positive” 문구는 addendum에서 **fresh1 / two-sample ready0**으로 정정했다.
원본을 덮어쓰지 않았다.

Public initialize≤1을 소비했으므로 `_initialize` 우회/재호출이나 새 ledger/campaign으로 계속하지 않았다.
제15차는 initialize1/healthy0/calibration0/measured 각0/KEDA restart0/0이다.
Calibration 잔여2와 measured 각1은 종료된 campaign에서 실행할 수 있는 승인으로 이월하지 않는다.
과거14회를 합쳐 **campaign15 / initialize12 / healthy3 / started-invalid calibration2 / measured 각0 /
KEDA apply·restore 각3**을 보존한다. Freeze·continuing-demand recovery·accounting/confounder 비교는 미도달이다.
제14차 sentinel transport와 별도 monitor failure의 원인·인과는 여전히 unknown이다.
이번에는 `owned_forward()`를 시작하는 단계에도 도달하지 않았다. Local process 검증을 live forwarding proof로 표시하지 않는다.

## 원복·비용·credential 출력 사고

CUSTOM exact UID 제거 → shared CM original UID/data guarded restore → owned namespace 삭제를 수행했다.
Namespace-native public CA/CRL의 UID·label·namespace 생성 이후 시각을 확인했으며 finalizer를 강제 제거하지 않았다.
Final native verify1/exit0 뒤 PAT29 DELETE204·PAT401·token list0·fixture login 차단/Basic401을 확인했다.
Fixture DB records는 보존했다. Live image reference0 확인 뒤 소유 ACR digest/local tag와 임시 AKS role을 제거했다.
기존 Owner2개, stable Argo/Forgejo·Secret/mounted version·PVC/PV·ingress/mesh·KEDA·AKS/PG·inventory 등
**28개 check가 모두 true**다. KEDA IAM/SA mutation은 없었다. Stable Azure Environment는 보존했다.

최종 bounded GET도 성공했고 네 RG inventory34개가 같았다. 전후 posted two-RG는
**KRW144,123.7793191074**, project4 합계는 **KRW144,240.0700643775**다.
최신 usage는11월1일 partial이며11월2일 실비가 반영됐다는 근거가 없다.
보수적 누적 planning 모델은 전후 **USD242.8037480503**, 승인된 세전 review envelope **USD275** 안이다.
122h overlap·historical20·aux72h·buffer5·제15차 variable/uncertainty10을 포함한다.
1200KRW/USD는 planning 환율이며 invoice/시장 환율이 아니다. P9 단독 실비/잔액은 unknown/shared/delayed다.
Posted delta0을 실행 비용0으로 해석하지 않는다.

Environment **11월5일10:30 KST**, Foundation/Bootstrap **11월6일00:33 KST**를 유지했다.
Run360+drain60+rollback1800=2220초, initialization840+kill5를 더한3065초,
전체 준비1800+840+5+6×600+rollback1800=8045초의 기존 strict cutoff를 유지한다.
Candidate 전체 시작 한계는 **11월5일08:15:55 KST 미만**이며 actual plan별 재계산이 필요하다.
보존 연장·전체 teardown·새 compute/Disk/PVC·merge/P10은 없다.

Campaign parent 종료 시 REPL의 `os.environ.pop()` 반환값이 **stable 관리자 credential을 local tool output에 노출**했다.
값은 PR/저장소/이 archive에 넣지 않았다. 알려진 credential/encoding의 publication scan matches0이다.
이 scan은 도구 출력 노출을 취소하지 않는다. Stable credential은 회전하지 않았으며 **별도 처리·회전 권한 판단이 필요**하다.
PAT29 폐기와 stable admin credential 회전은 서로 다른 조치다.
Parent 종료·보호 사본296개 제거를 확인했고 global Azure CLI cache/무관한 base image cache는 보존했다.
물리적 secure erasure나 전체 Environment zero residual을 주장하지 않는다.

## 후속 cost-free 변경과 artifact

CPU 준비 경로에서 같은1회의 Pod metrics GET을 SQL/Argo/HPA/event 조회 뒤로 옮겨
freshness 판정 전에 local reads가 sample을 더 오래되게 만드는 지연을 줄였다.
Normal P8/measure 경로의 순서는 유지한다. Poll에 exact guard UTC·sample age·Ready 이후 window 여부를 추가했다.
**Freshness30초, settling300초, 두 advancing sample·Warning/quiet·collection/run/retention·횟수 기준은 유지**한다.
이 변경이 이번 실행을 성공으로 바꾸거나 export 지연을 해결했다고 주장하지 않는다.
새 SHA/image/plan binding·독립 review·별도 실행 승인과 credential 노출 처리 판단 전 paid 경로는 보류한다.

[execution.json](execution.json), [comparison.json](comparison.json), [validation.json](validation.json),
[raw-index.json](raw-index.json), [raw-evidence.tar.gz](raw-evidence.tar.gz),
[incident](../../incidents/p9-mitigation-fifteenth.md)를 연결한다.
Publication copy167개는 known-credential scan을 통과했고 private path만 redact했다.
Index에 원본/공개본 SHA256과 redaction 여부를 구분했다. Full account 응답은 제외했고 billing raw·Secret·trace·operator/history는 공개하지 않았다.
Archive SHA256은 `bd308dfcbd641433062c1a8e30d1e40fb3b84d15594f1a69c1bf11a8027d9589`이며
다시 읽어 모든 member path/size/hash를 확인했다. 과거14개 archive byte/hash는 그대로다.
Local 검사와 최종 exact-head 자동 CI 결과는 validation 및 PR 결과에 연결한다. 독립 review는 별도로 남는다.
