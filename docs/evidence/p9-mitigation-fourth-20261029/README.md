# P9 제4차 승인 실행 — bounded CPU preparation 미완료

상태: **필수 CPU preparation 실패 / P9-owned 원복·cleanup 완료 / P9 acceptance 미충족**.
Healthy journey·fault·calibration·각 measured arm0, freeze 없음이다. Mitigation/recovery는 not measured이며
fault/recovery observation window가 없으므로 recovery FAIL/non-recovery 측정 결과로 바꾸지 않는다.

승인·실제 execution source는 **`b484160cc0bf13af93d234a5ba30c4013f1d8e00`**다.
[사용자 통합 승인](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/41#issuecomment-6490726245),
[독립 source review](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/41#pullrequestreview-5694111880),
exact-head Full Local CI40833032392·CodeQL/Analyze success를 확인했다. Main은 `3f788a9c1d103f6c07bd403af269133fac287002`다.
실행 중 source는 수정하지 않았다. Cleanup 이후 발견한 duration 표현의 cost-free source correction과 최종 HEAD는
위 실행 source/승인과 구분하며 새로운 유료 실행에 승계하지 않는다. 이전 세 차례 raw/checksum/승인·비용을 보존했다.

## 실제 준비와 실패

| 단계 | 이번 실행 |
| --- | --- |
| 환경/identity | 승인 사용자·subscription·AKS/cluster UID 일치, Argo Synced/Healthy·stable/shared/KEDA baseline 일치 |
| Image | exact-source tag1 build/publish, digest `sha256:351ac866e37d4fd4e977c3218d1e3223d5c1c2b9df67666bea7762e24db92026`; 종료 시 삭제 |
| Native normal | 새 non-admin fixture create1, structured operations/attempts9 성공; 원복 후 같은 fixture verify1 성공 |
| Initial admission | Ready Pod3, requests CPU400m/512Mi, limits CPU900m/1024Mi; injected init/native sidecar 포함 conservative sum |
| Initialize | invocation1/exit1, command92.26초, healthy_initialize87.14초, readiness_resource_guard stage72.45초 |
| 직접 failure | `readiness_resource_guard / ValueError / validation_failed`; private traceback의 고정 source error는 `CPU warning outside startup lifetime` |
| CPU 준비 proof | emitted poll2개 모두 pending; pre-Ready window·같은 sample·ScalingActive=False/currentMetrics 미확보 |
| Healthy journey/fault | 각각0, intent/completion 없음, 자동 workload 재실행 없음 |
| KEDA | actual2.19.0-25/SA/CRD, 다른 ScaledObject/ScaledJob0; 새 UAMI/FIC/workspace role·SA/template mutation·apply/restore restart0 |
| Calibration/freeze/C0–C3 | calibration0, frozen plan 없음, measured 각0; [comparison](comparison.json) 모두 not measured |

Target Pod와 CPU HPA는 **07:39:10 UTC** 생성, Pod Ready는 **07:39:26 UTC**다.
두 CPU poll의 sample은 **07:39:29 UTC / 13.482793024초 / app CPU46764346n**로 같다.
Window 시작 약07:39:15.52 UTC는 Ready 이전이며 두 poll 모두 `valid_ready_window=false`,
`hpa_metric_recovered=false`다. HPA Warning count/time도 실제 기록으로 보존했다.
실제 admission 요약→opt-in lifecycle 경계는 이번 실행에서 통과했고 과거 KeyError를 반복한 결과가 아니다.

Source는 pending warning이 있을 때 target Pod와 HPA 각각의 생성 age≤90초도 검사한다.
이번 exception은 이 **creation lifetime 경계**이며 전체 healthy_initialize90초 timeout과 동일한 시계가 아니다.
Command 종료 시각07:41:00 UTC와 source frame/creation 시각은 이 판단과 일치한다.
Snapshot30초/command15초를 늘리거나 warning을 제외하지 않았다. 고정 error와 source frame만 안전하게 공개했고
mode0600 full traceback은 보호 local cleanup에서 제거했다.

## 중단 후 관측과 source-only 보완

CUSTOM 제거/shared restore 뒤의 terminal snapshot은 HPA `ScalingActive=True/ValidMetricFound`,
reported transition **07:40:40 UTC**, matching currentMetrics **app/cpu averageUtilization2 / averageValue1m**를 보존한다.
이는 **나중에 읽은 HPA status**이며 실패한 마지막 guard의 전체 반환 payload나 완료된 준비 proof가 아니다.
두 emitted pending poll에서의 미회복과 post-stop status를 구분한다. `failure-reviewed.json`의
`hpa_recovery_observed=false`는 이 두 poll의 범위이며 모든 후속 snapshot에서 False라는 뜻이 아니다.
Quiet interval·advancing valid samples를 충족한 CPU preparation completion은 없고 추가 실행으로 보완하지 않았다.
Underlying metric 지연/부재 원인과 과거 두 번째 실행 원인은 여전히 미확정/unknown이다.

Post-stop target PodMetrics sample **07:41:31 UTC/window `1m5.166s`**도 보존됐다.
승인 source의 초 전용 window regex는 이 실제 표현을 거부한다. Cleanup 후 같은 PR에서 **표현만** 보완했다:
`1m5.166s`와 `65.166s`를 동일65.166초로 해석하되 ≤90초 window·Ready 구간/freshness·warning/lifetime 상한은 유지한다.
실제 payload의 window를 synthetic healthy wrapper에 적용한 회귀는 수정 전 `invalid CPU sample window`를 재현했고
수정 후 equivalent positive/Ready 이전 pending/상한 초과·zero·unknown 거부를 확인했다.
이 source correction으로 Azure를 다시 실행하지 않았으며 post-stop sample을 live preparation/recovery 성공으로 만들지 않는다.
[Incident/corrective action](../../incidents/p9-mitigation-fourth.md)을 연결한다.

## 원복과 credential/IAM/image cleanup

1. Mandatory failure 뒤 소유 UID를 확인해 **CUSTOM을 우선 제거**했다. Shared CM UID/applied-data를 JSON Patch test한 뒤 원본 data 복구.
2. KEDA는 변경하지 않았고 원래 Deployment UID/spec·SA UID/annotation·Ready2를 확인했다. 새 UAMI/FIC/workspace role은 만들지 않았다.
3. 소유 namespace/controllers/Sidecar/PodMonitor/DB Secret/Pods를 제거하고 namespace 부재를 확인했다.
4. Live Pod image 참조0, 소유 digest의 tag가 exact source 한 개임을 확인한 뒤 ACR manifest/tag·local tag를 삭제했다. Shared base/node cache는 purge하지 않았다.
5. PAT **ID15**를 발급·후속 cleanup 전에 audit에 기록했다. DELETE204/0 bytes, 기존 PAT401·token 목록0을 login 차단 전에 확인했고
   `prohibit_login=true`·Basic401도 확인했다. 기존 request helper를 재사용했다. Fixture 계정/repo/Issue/PR 기록은 남긴다.
6. 소유 AKS-only 임시 role만 삭제하고 원래 assignment ID 집합을 확인했다. 전용 kubeconfig/admin·DB/PAT/clone/ACR auth/traceback·임시 kubelogin을 제거했다.
   기본 kubeconfig를 변경하지 않았고 port-forward는 만들지 않았다. 기존 Azure CLI login은 유지했다.
7. Stable Argo Synced/Healthy·Deployment UID/spec·Secret UID/data hash, PVC/PV/node UID 집합·기존 Disk10GiB와 environment resource ID 집합을 대조했다.
   Nodes2/autoscaling OFF와 기존 admin Secret logical version2의 명시적 P9 한정 재사용을 보존했다. Secret rotation은 없다.

P9-owned cleanup이며 전체 environment teardown/fixture record·physical cache zero-residual이 아니다.
Kubernetes authorization cache의 즉시 권한 소멸은 측정하지 않았고 Azure assignment 부재는 확인했다.

## 비용·한도·증거

Current ActualCost는 최초429 뒤 제한된 재조회에서 성공했다. Before/final 모두
**KRW26,885.8891798273 / usage date20261028**이다. 과거 KRW18,845.545320581 → KRW24,292.445425032 →
KRW26,885.8891798273과 세 번의 준비/cleanup·KEDA apply1/restore1을 이어받는다.
동일 전후 값은 P9 비용0의 증거가 아니며 **P9 incremental actual은 delayed/shared billing으로 unknown**이다.
과거 관련 namespace 관측 log376,863 bytes와 동일 resource ID 집합은 bounded 재준비 판단 근거이며 전체 비용 proof는 아니다.
기존 USD5 계획/누적 USD10 검토 기준은 hard billing cap이 아니고 reset하지 않았다.

Environment **2026-10-30 10:30 KST**, Foundation/Bootstrap **2026-10-31 00:33 KST** 유지.
Run+60초 drain+30분 원복 여유는 있었지만 필수 gate 실패 후 추가 run을 시작하지 않았다.
새 node/server/Disk/PVC·autoscaling/DNS·retention·stable Secret 변경은 없다.

API helper request intent/response와 numeric PAT ID는 `normal-request-audit.jsonl`에 보존한다.
Git 내부 HTTP·일부 auxiliary curl을 포함한 전체 HTTP 수는 unknown이며 operation/check와1:1로 추정하지 않는다.
[실행 요약](execution.json), [raw108 archive](raw-evidence.tar.gz), [개별 index/checksum](raw-index.json),
[검증](validation.json)을 연결한다. 알려진 secret 값과 private path/credential pattern을 publication 전에 검사했고
full traceback/Secret data/credential/kubeconfig/clone은 archive에서 제외했다.

남은 gate는 생성 lifetime·settling wall-clock·실제 metric cadence의 계약 검토, 완료된 HPA/CPU positive proof,
healthy shared-path/target telemetry·KEDA scaler auth 및 calibration/freeze/C0–C3 continuing-demand measurement다.
현재 한도나 acceptance를 사후 완화하지 않았다. 새 exact-source gate와 필요한 별도 통합 승인 전 유료 Azure 실행은 없다.

후속 source-only 시간 계약 보정은 [incident](../../incidents/p9-mitigation-fourth.md#후속-source-only-시간-계약-보정)과
[현재 CPU preparation contract](../../p9-mitigation-recovery.md#최초-healthy-초기화-순서)를 따른다.
Warning 발생 허용90초와 settling monotonic300초를 분리하고 외부 initialize timeout을 전체 단계 예산에 맞췄다.
이 archive의 구조를 재사용한 회귀에서90초 이후 pending과 synthetic advancing recovery를 구분한다.
실제 추가 Azure 실행/측정은 없으며 위 raw108/checksum·실행 승인/source·비용·준비/원복 누적4회를 보존한다.
