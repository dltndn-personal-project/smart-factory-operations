# 04 분석 계획 (M2)

> 목적: OPS-5(상관분석)의 PLAN 정의와 단계 개요. 시간 결합(04 1절)은 OPS-3A(`03-control.md`)가 한다.
> 읽어야 할 때: OPS-5를 실행하거나 등록할 때. 같이 읽을 spec: `docs/spec/04-analysis.md` 2·3절.

## 1. task

### OPS-5 상관분석

```yaml
  - id: OPS-5
    milestone: M2
    type: feature
    title: 설비-품질 상관분석과 DB 주기 계산
    why: 설비 상태(PdM Anomaly Score)와 불량의 관계를 Pearson·Spearman·Time Lag로 Dashboard에 보여야 한다. 알려진 lag로 방법이 맞는지 확인한다 (C-07, spec 04 2절, D-13·D-30)
    depends_on: [OPS-4]
    scope: [src/factory_operations/domain/correlation.py, tests/unit/test_correlation.py, tests/docker/test_correlation_db.py, docs/spec/04-analysis.md, docs/spec/DECISIONS.md]
    acceptance:
      - id: A1
        text: 단위 테스트 전체가 통과한다
        check: {type: command, run: "make test"}
      - id: A2
        text: seed 고정 합성 데이터(점수 0.5초 간격 600초 계단, 제품 2초 간격, 불량 확률 0.05 + 0.6·score(t − 13))에서 best.lag_s가 12~14이고 at_default.pearson > 0.3이다 (C-07, 08 3.4절)
        check: {type: command, run: "make venv >/dev/null && .venv/bin/python -m pytest -q tests/unit/test_correlation.py::test_known_lag_13"}
      - id: A3
        text: 표본 19개 → insufficient_samples, 모두 양품 → single_class, 점수 상수 → constant_score로 계수가 null이고, |Pearson|이 같은 두 lag 중 작은 lag가 best다 (04 2.2절)
        check: {type: command, run: "make venv >/dev/null && .venv/bin/python -m pytest -q tests/unit/test_correlation.py::test_insufficient_samples tests/unit/test_correlation.py::test_single_class tests/unit/test_correlation.py::test_constant_score tests/unit/test_correlation.py::test_tie_prefers_smaller_lag"}
      - id: A4
        text: bins가 첫 검사 시각부터 30초 구간이고 각 defect_rate·n_inspected가 직접 센 값과 같으며, 결과 dict의 키와 반올림이 04 2.3절 형식이다
        check: {type: command, run: "make venv >/dev/null && .venv/bin/python -m pytest -q tests/unit/test_correlation.py::test_bins_match_counts tests/unit/test_correlation.py::test_result_shape"}
      - id: A5
        text: 실제 DB에 합성 검사·설비 행을 넣고 DB 스레드에 이 계산 함수를 주입하면 주기 계산 결과가 콜백으로 나오고 best.lag_s가 12~14다
        check: {type: command, run: "make venv >/dev/null && .venv/bin/python -m pytest -q tests/docker/test_correlation_db.py::test_periodic_correlation_from_db"}
      - id: A6
        text: Docker 연동 테스트 전체가 통과한다
        check: {type: command, run: "make docker-test"}
    size: S
```

단계 개요:
1. `correlation.py` `compute(inspections, scores, cfg) -> dict`: 04 2.2절 1~5번(searchsorted as-of, `max_gap_s`, 사유 세 가지, scipy `pearsonr`·`spearmanr`, 소수 4자리, `at_default`, `best`, `curve`, `bins` 최근 20구간), `computed_at`은 주입한 시계. 예외는 호출자(DB 스레드)가 로그로 남기고 이전 결과를 유지한다. → A2~A4
2. `tests/unit/test_correlation.py`(합성 데이터 생성은 테스트 안, seed 고정). → A1
3. `tests/docker/test_correlation_db.py`: OPS-4 fixture로 행을 넣고 짧은 주기(`correlation.period_s` 1)로 DB 스레드를 돌려 콜백을 기다린다. `store/`는 고치지 않는다(05 계획 1절). → A5, A6

읽을 spec: 04 2·3절, 05 3·5절(주기·조회), 08 3.4절, D-13·D-30.
