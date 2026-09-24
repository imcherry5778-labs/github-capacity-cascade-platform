# P1 local Forgejo platform entrypoints. CI(.github/workflows/local-platform.yml)도 같은 scripts를 사용한다.
#   make static   cluster 없이 source/static/render validation
#   make local    static + fresh cluster up + runtime verification + cleanup (실패해도 cleanup)
#   make up | verify | down   lifecycle 단계별 실행
.DEFAULT_GOAL := static
.PHONY: tools static up verify down local

tools:
	scripts/install-tools.sh

static:
	scripts/local-verify.sh static

up:
	scripts/local-up.sh

verify:
	scripts/local-verify.sh runtime

down:
	scripts/local-down.sh

local: static
	@if .tmp/bin/k3d cluster get capacity-cascade-local >/dev/null 2>&1; then \
		echo "cluster capacity-cascade-local already exists; run make down explicitly first" >&2; \
		exit 1; \
	fi; \
	rc=0; \
	scripts/local-up.sh && scripts/local-verify.sh runtime || rc=$?; \
	down_rc=0; \
	scripts/local-down.sh || down_rc=$?; \
	if [ $rc -ne 0 ]; then exit $rc; fi; \
	exit $down_rc
