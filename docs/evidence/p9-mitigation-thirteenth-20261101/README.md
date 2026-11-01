# P9 제13차 — 준비 계약 불충족과 initialize telemetry deadline 중단

상태: **단일 campaign 종료 / 준비 계약 invalid / normal·healthy journey 각각 valid/success/warmup9 / initialize1회·exit1 / calibration·C0–C3 measured0 / P9-owned cleanup 검증 / P9 acceptance 미충족**.
아래 시각은 2026-11-01 UTC다. KST는 +9시간이다.

실제 실행 source는 **`453841d4274d6777073a0ed1d5282e3e784461c8`**,
main/base는 `3f788a9c1d103f6c07bd403af269133fac287002`다.
[단일 실행·추가 세전 USD40/누적 USD180 승인](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/41#issuecomment-6557532658),
[exact-source 독립 review](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/41#pullrequestreview-5727609636),
[Full Local CI](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/actions/runs/41291863379),
[CodeQL/Analyze](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/actions/runs/41291861279)를 실행 전에 재사용했다.
후속 docs/evidence HEAD는 실행 source가 아니다. 구현·timeout·acceptance 변경은 없다.

## 중복 방지와 실제 도달

Fetch 뒤 local/remote main·PR HEAD, Draft/Open/unmerged와 기존 PR worktree clean 상태를 확인했다.
현재 호스트 process, Orca session/terminal, preparation/run ledger, raw output, 미push evidence에 제13차 흔적이 없었고,
live namespace/CUSTOM 및 ACR repository도 부재였다. GitHub 보고 부재만으로 판단하지 않았다.
새 branch/PR이나 추가 campaign은 만들지 않았다.

첫 mutation intent **12:55:08.668108** → cleanup/finalization **13:11:48.960577**다.
Campaign `p9z20261101`, 준비/원복 누적13회다. Normal1, public initialize1, 그 안의 healthy journey1을 소비했다.
Calibration0/2, measured C0/C1/C2/C3 각각0/1, freeze 없음이다.

Kubectl **v1.36.4**, `.tmp/bin/kubectl` SHA256
`8b8f088da2dab964f853b38464033b1be15ede2839eca751482357c45abdd05a`,
fresh protected kube context, Entra user auth, `PYTHONDONTWRITEBYTECODE=1`을 사용했다.
Stable Secret logical version2 UID/data·mounted versions, shared mesh 원래 UID/data를 실제 확인했다.
Live ingress Service IP를 process-local DNS override에 연결했고 HTTPS certificate/hostname 검증과 non-admin journey를 유지했다.

Local image revision label과 ACR single tag/digest를 확인했다:
**`sha256:ade8027ac1c958c23cb07c568365f5f7f875380de32c6de51474a6666ee1ff0c`**.
Preparation plan SHA256는 **`ec82078689d9d5df7e15a3315ceefbd6c82bb375a8c8efd1f9bab785a008958e`**다.
Approval은 source/identity/plan에 bind했고 healthy/runtime flag는 false를 유지했다.

## 준비 오류와 source-native 결과를 분리

Operator가 임시 `p8-db-read`에 **`PGSSLMODE=require`**를 넣었다. 문서 계약은 **`verify-full`**이다.
이는 준비 계약 불충족이며 DB hostname/certificate 검증 성공으로 해석하지 않는다.
기존 app DB role/credential을 복사한 실험 Secret만 해당하며 stable Secret rotation/변경은 없다.
Self-review에서 확인한 뒤 Secret/Pod를 고쳐 새 run으로 보충하지 않고 downstream을 중단했다.

실제 순서는 initial node headroom → injected sidecar/init 포함 server-side dry-run → guarded mesh overlay
→ target/DB Ready → backend Ready EndpointSlice → HAProxy Ready → HPA/PodMonitor/CUSTOM
→ initial all-Pod live headroom → normal이었다.
Target 단계에서 HAProxy 전에 별도 live node headroom을 수집해야 하는 순서를 완전히 만족하지 못했다.
뒤의 positive headroom으로 앞의 ordered gate를 소급 충족시키지 않는다.
4-Pod dry-run은 requests **650m/832Mi**, limits **1450m/1664Mi**,
실제 초기3Pods는 requests **400m/512Mi**, limits **900m/1024Mi**였다.
실제 Ready/UID/restart0·init 종료 상태를 보존했고 Pod/history reset은 없다.

로컬 첫 build는 필수 BASE_IMAGE 누락으로 exit125였으며 publish 전에 고정 pin/context로 바로잡았다.
Pin key 조회, read-only negative schema/Argo 이름, normal context transport key의 operator invocation 오류도
`operator-final-review.json`에 남겼다. 이 오류 때 normal/initialize는 시작되지 않았다.
임시 AKS role 전파의 Forbidden을 read-only polling했고 실제 접근 확인 뒤 workload를 생성했다.
이들을 source CPU/telemetry 실패나 추가 campaign으로 분류하지 않는다.

Normal **13:01:43.635642 → 13:01:49.859260**, elapsed **6.223587s**,
**1회 valid/success/warmup, 9operations/9attempts**다.
Public initialize **13:01:49.862229 → 13:08:11.248513**, external elapsed **381.386203s**, **1회/exit1**이다.
Source 내부 elapsed **376.880783s**, 최종 `telemetry_configuration` stage **1.056685s**에
`TimeoutExpired / command_timeout`을 기록했다.

CPU poll11개 중 ready1개가 있었고 healthy journey intent1회 뒤 journey 자체는 **valid/success/warmup9**였다.
같은-window accounting은 ALLOW checks30 / ingress HTTP records30을 보존했다.
Target signal은 telemetry poll2개에서 실제 `observed`였으나 CPU freshness를 포함한 최종 healthy gate는 완료되지 않았다.
`healthy_initialization_complete=0`, runtime preflight false다. 부분 관측을 전체 healthy 성공으로 승격하지 않는다.

마지막 source command는 다음과 같으며 private diagnostic에서 남은 timeout **0.144983690s**만 추출했다.

```text
kubectl --request-timeout=10s -n p8-shared-gate get scaledobjects -o json
```

전체 telemetry deadline의 잔여 budget에서 실패했다. 개별15초·snapshot30초·settling300초·outer840초/kill5초는 늘리지 않았다.
선행 command별 latency와 underlying API 원인은 unknown이다. Full private traceback은 publication에서 제외하고 cleanup했다.
준비 TLS/순서 오류는 이 timeout과 별도의 invalid 사유이며 인과관계를 단정하지 않는다.

KEDA auth/단일 generated HPA proof, calibration/freeze, C0–C3 measured, C3 두 Ready target snapshot≤30s/end gap≤35s,
continuing-demand recovery의3×10s SLO/accounting은 **모두 미도달**이다.
Measured valid-negative나 `not recovered within observation window` 결과는 없다. 관측 window 자체가 없다.
네 arm compare와 measured cloud confounder review는 수행하지 않았고 synthetic28.391s는 Azure 증거가 아니다.

## 비용과 보존

첫 paid mutation 전 한 번의 bounded 비용 검토에서 두 RG ActualCost는 **KRW123,029.5838968907**였다.
Oct28–31 및 Nov1 partial **KRW1,610.4675368223**를 포함한다. Usage·동일 ARM inventory23/7·고정2×D4s_v4,
기존 PostgreSQL/ACR·quota/RBAC 및 Korea Central Retail Prices API 응답을 보존했다.
제12차 posted **KRW115,421.7153009966**를 변경하지 않았다.

기존 ninth baseline 이후 posted delta 전체, 최근 full-day rate×50h, Foundation/Bootstrap/Grafana USD5와
이전 미반영 campaign/이번 variable USD15를 포함한 누적 위험 추정은 **세전 USD134.192723**였다.
50h는 Oct31부터 Environment cutoff까지49.5h를 올린 값이며 이미 posted된 Oct31과 Nov1 partial도 중복 포함한다.
Planning stress **1200KRW/USD**는 시장/청구 환율 주장이 아니다.
기존 USD140 + 추가 USD40 = **누적 USD180 review envelope** 안이었다. Billing hard cap/확정 잔액은 아니다.
초기 잔여 보존기간은 전체8,045s reserve보다 컸다. Run/drain60s/rollback30min guard는 유지했다.

Cleanup 후 final ActualCost 요청1회는 nonzero로 실패했다. Collector가 stderr/exit code를 보존하지 못해
실패 원인과 final posted 금액은 **unknown**이다. 재조회 루프나 승인 재검토는 하지 않았다.
마지막 성공 금액을 after-cleanup 금액으로 바꾸거나 posted delta를 P9 단독 비용으로 귀속하지 않는다.
**P9 attributable incremental actual은 shared/delayed/unknown**이다.

Environment **2026-11-02 10:30 KST**, Foundation/Bootstrap **2026-11-03 00:33 KST**를 유지한다.
자동 연장·provider TTL 변경·전체 Environment teardown은 없다.

## Owned 원복과 artifact

Source 종료 후 CUSTOM exact UID 삭제 → original UID/data guarded mesh 복구 → KEDA 변경0 확인
→ experiment namespace exact UID 삭제를 완료했다. KEDA SA/operator/UAMI/FIC/Reader role은 미사용,
apply/restore restart **각0**, historical 누적 **각2**다.
Final native verify **1회/exit0** 뒤 normal PAT25와 healthy PAT26을 각각 DELETE204/empty,
PAT401, token list0, fixture login 차단/Basic401로 확인했다. Fixture DB records는 보존했다.

Live image refs0·single owned tag/digest 확인 뒤 ACR digest/tag와 local tag를 제거했다.
임시 AKS role exact ID 삭제 후 `RoleAssignmentNotFound`와 기존 assignments 보존을 확인했다.
Stable Forgejo/Argo/Secret/PVC/PV/Disk/nodes/ingress·mesh·KEDA·Azure inventory 보존 비교 **26항목 모두 true**다.
Owned port-forward는 생성하지 않았다. 보호된 kubeconfig·credentials·clone·trace·registry auth·tool/operator 사본 **247 files**를 제거했다.
Global Azure CLI login/cache와 unrelated base cache는 보존했다. 물리적 secure erasure/IAM cache 즉시 만료는 주장하지 않는다.

[execution.json](execution.json), [comparison.json](comparison.json), [validation.json](validation.json),
[raw-index.json](raw-index.json), [raw-evidence.tar.gz](raw-evidence.tar.gz)를 연결한다.
Archive **194 files**, SHA256 **`7ef5d4d4d4eeb59e1a614892169cb02aa7460077e1d7253b93319c715f0da091`**다.
Member path/size/hash와 과거12개 archive의 byte/hash 보존을 검증한다.
Known credential/encoding/private-path scan matches0이며 raw failure를 성공으로 고치지 않았다.
Source regression/static을 수동 반복하지 않았다. 후속 evidence exact-head CI는 같은 Draft PR #41에 별도로 기록한다.

**P9 acceptance 미충족**이다. 준비 오류, initialize 최종 gate와 KEDA/calibration/freeze·네 arm/recovery가 남았다.
자동 제14차·source 개선·새 work unit/PR·merge/P10은 없다.
