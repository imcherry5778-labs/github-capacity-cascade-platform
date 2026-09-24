# Terminology

## 1. Claim provenance

- **FACT**: primary/public source가 직접 뒷받침
- **INFERENCE**: 공개 자료 또는 project evidence의 해석
- **LAB_IMPLEMENTATION**: failure effect를 측정하기 위한 project topology/config/policy
- **UNKNOWN**: 공개되지 않았거나 현재 evidence로 확인 불가

## 2. Term source

- **PRODUCT_TERM**: upstream product 공식 용어
- **INDUSTRY_TERM**: SRE/distributed systems 일반 용어
- **PROJECT_TERM**: 이 repository의 measurement boundary를 명확히 하기 위한 용어
- **LEGACY_LAB_TERM**: Lab provenance에는 남지만 Platform 기본 표현으로 사용하지 않는 용어

## 3. Core terms

### cascading failure

한 부분의 overload/failure가 다른 부분의 load/failure probability를 높이며 연쇄 확산되는 현상.

### overload

처리 capacity를 넘는 상태. CPU뿐 아니라 concurrency, queue, connection, request/admission limit 등을 포함한다.

### developer operation

개발자가 의도한 상위 행동. 예: Git push, Pull Request 생성. HTTP request와 1:1이라고 가정하지 않는다.

### operation attempt

하나의 developer operation을 수행하려 한 한 번의 시도. Client retry가 있으면 여러 attempt가 생긴다.

### HTTP request

Protocol-level request. Git operation 하나가 여러 HTTP request를 포함할 수 있다.

### authorization check

Reliability experiment에서 synthetic shared gate로 보내는 decision request. Forgejo native authentication/authorization replacement가 아니다.

### Envoy upstream request

Selected Envoy가 upstream cluster로 전달한 request 단위. Developer operation/client attempt와 별도 계층이다.

### application request

최종 application container가 실제 수신/처리한 request 단위.

### retry amplification

Retry 때문에 같은 상위 demand가 더 많은 attempt/request workload로 변하는 현상. Ratio는 numerator/denominator를 명시한다.

### active-request capacity / circuit breaker

Selected proxy의 request/concurrency limit. P0에서는 version-specific Envoy counter 이름을 일반화하지 않고 selected runtime의 actual stat/config inventory에서 exact rejection signal을 확인한다.

### application-container CPU HPA

Application container CPU signal을 scaling input으로 쓰는 HPA. Kubernetes 공식 mode로 `blind HPA`가 존재하는 것은 아니다.

### proxy/saturation-signal scaling

Proxy capacity/saturation과 더 직접적인 signal을 사용하는 scaling policy의 일반 설명. 실제 implementation에서는 controller와 exact metric을 명시한다.

### rate limiting / load shedding

Rate limiting은 구체적인 request 제한 mechanism이고, load shedding은 overload 보호를 위해 일부 work를 거절/중단하는 더 넓은 개념이다.

### Service Active Window

Ephemeral environment가 의도적으로 serviceable 상태로 선언된 측정 구간. 24/7 monthly SaaS availability와 같은 의미가 아니다.

### confounder

의도한 target 외의 원인으로 결과를 설명할 수 있게 하는 교란 변수. 예: Forgejo/DB/node saturation.

### reviewed evidence

Raw run 중 provenance/validity/secret boundary를 검토해 project claim을 다시 확인할 수 있도록 보존한 evidence.

## 4. Legacy Lab mapping

| Legacy Lab term | Platform에서 우선할 표현 |
| --- | --- |
| `logical_requests` | 문맥에 따른 developer/logical operations |
| `physical_attempts` | exact client/operation attempt 단위 명시 |
| `hpa-blind` | application-container CPU HPA |
| `hpa-aware` | exact proxy/saturation signal + controller |
| `sidecar active overflow` | selected runtime의 exact rejection/overflow signal |
| `recovery_idle` | exact recovery criterion met |

## 5. Evidence status

- **valid run**: provenance/condition/target/confounder boundary를 해석 가능
- **experiment PASS/FAIL**: 해당 acceptance 충족 여부
- **SLO met/violated**: developer SLO 충족 여부
- **hypothesis supported/not supported/inconclusive**: valid evidence에 대한 해석

의도된 failure experiment에서는 SLO violation이 정상일 수 있으며 experiment failure와 동일하지 않다.
