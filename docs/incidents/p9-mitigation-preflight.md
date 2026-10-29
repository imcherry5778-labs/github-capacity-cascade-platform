# P9 runtime telemetry gate 중단 — corrective action

## 상태와 범위

2026-10-29 KST, P9 통합 승인 후 필수 live telemetry gate에서 중단하고 P9-owned control을 원복했다.
[실행·raw·원복 evidence](../evidence/p9-mitigation-preflight-20261029/README.md)의 source는
`c06ce67b2d438c7affde6b6934368b43afa4c1f4`다. 정상 HTTPS journey와 최종 read verify는 성공했다.
CUSTOM policy·fault·calibration·measured run은 시작하지 않았다. Production incident 또는 P9 recovery 완료로 분류하지 않는다.

## 확인한 사실

Actual managed Envoy의 bootstrap tag와 cluster metric sample은 `cluster_name`을 사용한다.
승인 source는 `envoy_cluster_name` selector를 고정한다. Up/UID inventory는 존재하지만 필수 exact query는 empty였고,
healthy traffic 이전의 target inbound admin stat도 materialize되지 않았다. No-data를 zero로 변환하지 않고
required gate 미통과 및 source/runtime contract 충돌 시 중단하는 기존 경계를 적용했다.

Target inbound startup 초기화 순서는 아직 검증하지 않았다. 따라서 label mismatch만으로 모든 empty의 단일 원인을
측정했다고 주장하지 않으며, namespace/helper readiness를 proxy-saturation signal 성공으로 해석하지 않는다.

## 기존 incident와 P9 비교

[P8 incident](p8-controlled-cascade.md)의 proxy saturation/retry amplification 근거는 historical evidence로 보존한다.
P9가 계획한 backoff+jitter(C1), HAProxy admission+queue(C2), proxy-signal managed KEDA(C3)의 효과는 이번에 측정하지 못했다.
C0–C3 비교와 continuing-demand recovery time은 모두 not measured다. 정상 서비스 read verify는 P9 회복 proof가 아니다.

## Corrective action — 구현/실행 전 제안

| 항목 | 이번 처리 | 다음 확인 |
| --- | --- | --- |
| Native label ↔ source query | actual tag/sample과 hardcoded selector 차이를 raw로 보존, 실행 중단 | actual label을 제한된 입력/검증 contract로 source·KEDA query·collector·validator에 일관되게 연결하고 새 source gate |
| Inbound startup stat | pre-traffic missing을 negative로 보존 | 승인된 healthy path로 초기화/검증하는 순서 정리; 기존 Pod missing·unknown UID·empty guard를 완화하지 않음 |
| KEDA identity | token 주입만 확인, SA/template/identity env 원복 후 FIC/UAMI 정리 | 실제 workspace/scaler 인증과 controller cadence는 새 실행 gate에서 확인 |
| Audit completeness | 성공한 workload를 재실행하지 않고 parser/422/501·미보존 numeric ID를 기록 | 부작용 전 token ID/요청 metadata를 append하고 empty response·API 최소 PATCH를 안전하게 처리 |
| 비교/회복 | run0, freeze 없음 | 동일 schedule·상한·3×10초 criterion을 유지; warmup/부분 수렴을 성공 proof로 세지 않음 |

위 source correction을 이번 승인 SHA에 임의 반영하지 않았다. 신규 controller·metric bridge·별도 work unit/PR,
P6/P7 drill, P8 전체 실험, 추가 node/서버/Disk/PVC·DNS·retention 변경·P10은 수행하지 않았다.

## 원복 결과와 남은 limitation

Shared ConfigMap 원본 data, KEDA 원래 SA annotation/template/identity env와 Ready2를 확인했다.
Experiment namespace·DB Secret·HPA/PodMonitor/Sidecar, source image, 소유 IAM/FIC/UAMI 및 임시 AKS role을 제거했다.
PAT 잔여0/원래 PAT401과 login 차단, 보호된 local 사본 제거를 확인했고 기존 stable/PVC/PV/ingress/node를 보존했다.
Fixture 기록은 보존한다. 전체 환경 zero-residual·물리적 cache 삭제 또는 즉시 authorization-cache revocation을 주장하지 않는다.
P9 실제 증가 비용은 billing 지연/shared-resource 때문에 unknown이다. 상세 한계와 checksum은 연결 evidence를 따른다.
