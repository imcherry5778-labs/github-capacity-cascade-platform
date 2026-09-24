# Repository Conventions

## 1. Language

사람 대상 문서는 한국어 기본. Product/API/metric/CLI/code identifier/file path는 공식 영어 표기를 유지한다.

Machine interface(JSON/YAML key, env var, metric/log field, branch 등)는 영어를 사용한다.

## 2. Commit / PR title

```text
<type>(<scope>): <한글 설명>
```

예:

```text
feat(forgejo): local developer platform baseline 추가
test(e2e): developer journey 검증 추가
infra(terraform): Azure network source 추가
docs(architecture): experiment ownership 경계 보정
```

권장 type: `feat`, `fix`, `docs`, `test`, `refactor`, `perf`, `build`, `ci`, `chore`, `revert`.

Branch 이름은 영어다.

## 3. Pull Request

PR body는 한국어 기본이며 최소한 다음을 설명한다.

- 무엇을/왜 변경했는가
- 어떤 work unit scope/acceptance인가
- 실제 검증 결과
- 비용/external side effect
- non-goal / limitation

Solo project이므로 PR을 peer review라고 과장하지 않는다. PR-gated change management와 independent review라고 표현한다.

Main은 squash merge 기본.

## 4. Naming

Project-only 평가형 shorthand보다 실제 변경 변수를 우선한다.

선호:

```text
hpa-app-cpu
retry-immediate
retry-backoff-jitter
envoy-request-limit
```

피함:

```text
hpa-blind
hpa-aware
good-retry
bad-retry
```

Exact metric이 선택되지 않았다면 이름에 미리 박지 않는다.

## 5. Measurement units

다음을 혼용하지 않는다.

- developer operation
- operation attempt
- HTTP request
- authorization check
- Envoy upstream request
- application request

Project-specific ratio/metric은 numerator, denominator, measurement location, unit과 필요한 aggregation/window를 정의한다.

## 6. Claims

Incident claim은 FACT / INFERENCE / LAB_IMPLEMENTATION / UNKNOWN을 구분한다. Historical GitHub architecture를 현재 incident의 exact topology 증거로 사용하지 않는다.

## 7. Git storage

저장:

- authoritative source/config
- test/experiment definition
- human-readable docs
- reviewed evidence

저장하지 않음:

- state/credential/secret/kubeconfig/local env
- large raw telemetry
- temporary/generated runtime files
- portfolio website source / presentation asset / résumé-facing copy
- personal learning notes

## 8. Directory / abstraction

- target tree를 `.gitkeep`으로 미리 만들지 않는다.
- capability 첫 구현 시 필요한 path만 생성한다.
- module/helper는 실제 중복이나 독립 lifecycle이 생긴 뒤 추출한다.

## 9. Version

미래 milestone의 exact version을 장기간 선제 고정하지 않는다. 해당 work unit 시작 시 current upstream/compatibility를 확인하고 evidence reproducibility가 필요한 dependency를 exact pin한다.

Third-party GitHub Action은 가능한 경우 full commit SHA pin. Final evidence에는 actual runtime version/image digest를 기록한다.

## 10. Evidence wording

다음을 구분한다.

- valid / invalid run
- experiment PASS / FAIL
- SLO met / violated
- hypothesis supported / not supported / inconclusive

측정하지 않은 결과는 주장하지 않고, negative result도 valid하면 보존한다.
