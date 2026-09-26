# 04 분석: 시간 결합과 상관분석

> 목적: 설비 데이터와 제품·센서 데이터를 시간으로 잇는 규칙(`fault_level`, `health_index_at_time`)과 설비-품질 상관분석의 방법을 정한다.
> 읽어야 할 때: `domain/join.py`, `domain/correlation.py`(OPS-3, OPS-5), Dashboard 상관관계 칸.

## 1. 시간 결합 (`join.py`)

결합은 메시지를 처리하는 순간 메모리에 있는 데이터로 **한 번** 한다. 늦게 도착한 Line Status·PdM Result로 이미 기록한 행을 고치지 않는다. 모든 비교는 Payload timestamp끼리 한다(01 5절).

### 1.1 chunk ↔ `fault_level`

- `fault_level_at(ts)`: `LineTracker.fault_changes` 중 변화점 `timestamp ≤ ts`인 가장 최근 것의 `fault_level`. 없으면 null. (Shared INTERFACES Sensor Vibration의 as-of join 규칙과 같다.)
- 센서의 `sensor_id`와 관계없이 라인의 값을 붙인다(라인 하나).
- 오차: 변경 경계에서 최대 chunk 하나(0.1초). Line Status가 chunk보다 늦게 도착하면 그 chunk는 이전 값이 된다. toy 범위에서 받아들인다.
- `fault_level`은 Ground Truth 성격의 평가용 값이다. 저장·표시에만 쓰고 Interlock·Alarm·상관분석 입력으로 쓰지 않는다(Shared 8, 17절).

### 1.2 검사 ↔ 설비 상태 (`health_index_at_time`)

- 대상: 라인 센서(`line_sensor_id`)의 `pdm_history`. 재가동 기준 시각과 관계없이 모든 결과를 쓴다.
- 규칙: `timestamp ≤ vision.timestamp`(캡처 시각)인 가장 최근 결과 `r`. `vision.timestamp − r.timestamp ≤ join.max_gap_s`이면 `health_index_at_time = r.health_index`, `anomaly_score_at_time = r.anomaly_score`, `pdm_timestamp_at_time = r.timestamp`. 아니면 셋 다 null.
- `inspection.sensor_id`에는 결합에 쓴 라인 센서 id를 넣는다(결과가 없어도).
- 의미: Shared 5.3절 필드 이름 그대로 **캡처 시각** 기준 설비 상태다. 불량은 투입 시점(캡처 약 13.3초 전, Shared INTERFACES Product Created)에 정해지므로 원인 분석은 2절 Time Lag로 한다.
- 오차: PdM 결과 간격(0.5초) 정도. Vision Result가 그 시점을 덮는 PdM Result보다 먼저 오면 한 칸 이전 결과가 붙는다.

### 1.3 제품 ↔ 센서

단일 라인·단일 센서라 모든 제품을 라인 센서에 대응한다. 여러 센서·여러 라인 구분은 범위 밖이다.

## 2. 상관분석 (`correlation.py`)

설비 진동 상태와 제품 불량의 관계를 Pearson, Spearman, Time Lag로 본다(Shared 4.4 Correlation Analysis).

### 2.1 데이터

- **설비 지표** `x`: 라인 센서 `equipment_state.anomaly_score`. 원시 진동의 RMS 등은 Feature Extraction이라 PdM 책임이므로(Shared 17절) Operations는 계산하지 않는다. PdM의 이상 점수 자체가 진동에서 나온 값이다.
- **품질 지표** `y`: 제품별 `inspection.defect`(1/0). Vision의 판정 결과로서 그대로 쓴다(현재 `judgement_source = PASS_THROUGH`).
- **범위**: DB의 전체 행. `correlation.window_s`가 null이 아니면 가장 최근 검사 `timestamp`에서 그 초 이전까지. integration은 검증마다 DB를 비우므로 보통 한 실행 전체다.
- 주기: DB 스레드가 `correlation.period_s`(10초)마다 두 조회(05 5절)로 다시 계산해 StateStore에 넣는다.

### 2.2 계산

1. 검사를 `timestamp` 순으로 `t_i`, `y_i`. 설비 결과를 `timestamp` 순으로 `s_j`, `x_j`(numpy 배열).
2. lag `L`을 `lag_min_s`부터 `lag_max_s`까지 `lag_step_s` 간격(기본 0, 1, …, 30초)으로 바꾸며:
   - 목표 시각 `u_i = t_i − L`. `k = searchsorted(s, u_i, side="right") − 1`.
   - `k ≥ 0`이고 `u_i − s_k ≤ join.max_gap_s`인 표본만 쓴다. 표본 쌍 `(x_k, y_i)`.
   - 표본 수 `n < correlation.min_samples`(20)이거나, `y`가 모두 같거나, `x`의 분산이 0이면 두 계수 모두 null(사유 `insufficient_samples`, `single_class`, `constant_score`).
   - 아니면 `pearson = scipy.stats.pearsonr(x, y).statistic`(이진 `y`라 점이연 상관), `spearman = scipy.stats.spearmanr(x, y).statistic`. 소수 4자리로 반올림.
3. `at_default`: `L = correlation.default_lag_s`(13초)의 결과. 13초는 투입 → 캡처 약 13.3초(Shared INTERFACES Product Created)에서 정했다.
4. `best`: pearson이 null이 아닌 lag 중 |pearson| 최대. 같으면 작은 lag. 모두 null이면 null.
5. `bins`: 기본 lag의 표본을 캡처 시각 기준 `correlation.bin_s`(30초) 구간으로 나눈다. 구간 시작은 첫 검사 시각에서 `bin_s`씩. 구간마다 `start`(iso), `n_inspected`(그 구간의 모든 검사 수), `defect_rate`(그 구간 불량 수 / 검사 수), `mean_anomaly`(그 구간 유효 표본의 `x` 평균, 없으면 null). 최근 20구간만.

### 2.3 결과 형식 (StateStore `correlation`, 화면 06 3절)

```json
{
  "computed_at": "2026-09-25T05:25:00.120Z",
  "n_inspections": 150,
  "default_lag_s": 13,
  "at_default": {"lag_s": 13, "n": 131, "pearson": 0.4123, "spearman": 0.3981, "reason": null},
  "best": {"lag_s": 13, "n": 131, "pearson": 0.4123, "spearman": 0.3981, "reason": null},
  "curve": [{"lag_s": 0, "n": 140, "pearson": 0.2011, "spearman": 0.1874, "reason": null}],
  "bins": [{"start": "2026-09-25T05:20:13.425Z", "n_inspected": 15, "defect_rate": 0.0667, "mean_anomaly": 0.2130}]
}
```

`computed_at`은 Operations 시각이다. 계산 중 예외는 로그로 남기고 이전 결과를 유지한다.

### 2.4 해석 주의 (화면 문구)

- 화면에 "설비 지표 = PdM Anomaly Score, 품질 지표 = 검사 불량 여부(pass-through), 기본 lag 13초(투입 → 캡처)"를 적는다.
- 라인 정지 중에는 PdM 결과가 없어 그 구간을 가리키는 표본은 빠진다.

## 3. 설정

| 키 | 기본값 | 의미 |
|---|---|---|
| `join.max_gap_s` | 5.0 | 결합에 쓸 PdM 결과의 최대 시간 차(초). 1.2절, 2.2절 |
| `correlation.period_s` | 10 | 재계산 주기(초) |
| `correlation.lag_min_s` | 0 | |
| `correlation.lag_max_s` | 30 | |
| `correlation.lag_step_s` | 1 | |
| `correlation.default_lag_s` | 13 | `lag_min_s`~`lag_max_s` 안이어야 한다 |
| `correlation.min_samples` | 20 | |
| `correlation.bin_s` | 30 | |
| `correlation.window_s` | null | null이면 전체 |
