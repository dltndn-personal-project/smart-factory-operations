# Payload fixture 출처

`tests/conftest.py`의 `payload_examples`가 이 폴더의 `*.json`을 파일 이름(확장자 제외) → JSON 값으로 준다(spec 08 2절).
원문은 commit을 고정해 원격 Contents API로 읽었다(2026-09-27). OPS-2 때는 `contract_ref`가 null이라 90-shared 2절처럼 참고로 읽었고(`d0c997c`, `db9b7e7`), OPS-10에서 `contract_ref` `cb6dc3c`를 채택해 90-shared 1절로 확정본 예시를 더했다. `d0c997c`의 Sensor Vibration·Product Created·Vision Result·Conveyor Control·Line Status 절은 `cb6dc3c`에서 바뀌지 않았다.

- Shared: `dltndn-personal-project/smart-factory-shared-repository` `docs/INTERFACES.md` @ `d0c997c97129141d9853a42ce6e0d1f8f7309ae9`
- PdM: `dltndn-personal-project/smart-factory-pdm` `docs/ARCHITECTURE.md` @ `db9b7e79ce2329104d611ab52c509e74c6b927dd`
- Shared 확정본(`contract_ref`, OPS-10): `docs/INTERFACES.md` @ `cb6dc3cc6900e9f129b2a06688c5e5e5f75fd0b8` (PdM Result, PdM Spectrum, Alarm Event)

| 파일 | 출처 | 만든 방법 |
|---|---|---|
| `shared_sensor_vibration.json` | Shared `d0c997c` INTERFACES "Sensor Vibration" 예시 | 원문 스칼라 필드(`schema_version`, `sensor_id`, `timestamp`, `seq`, `sample_rate_hz`, `rpm`, `temperature`) 그대로. 원문 배열에는 설명 문자열(`"… 1000개"`)이 있어 그대로 쓸 수 없으므로 `vibration_x/y/z`는 `numpy.random.default_rng(20260927).normal(0.0, 0.05, 1000)`을 x, y, z 순서로 뽑아 소수 4자리로 반올림 |
| `shared_product_created.json` | Shared `d0c997c` INTERFACES "Product Created" 예시 | 원문 그대로 |
| `shared_vision_result.json` | Shared `d0c997c` INTERFACES "Vision Result" 예시 | 원문 그대로 |
| `shared_conveyor_control.json` | Shared `d0c997c` INTERFACES "Conveyor Control" 예시 | 원문 그대로 (`build_conveyor` 형식 비교용) |
| `shared_line_status.json` | Shared `d0c997c` INTERFACES "Line Status" 예시 | 원문 그대로 |
| `pdm_result_draft.json` | PdM `db9b7e7` ARCHITECTURE 6.2절 PdM Result 예시 | 원문 그대로 (확정 전 초안. 확정 형식에도 맞아 받아진다) |
| `shared_pdm_result.json` | Shared `cb6dc3c` INTERFACES "PdM Result" 예시 | 원문 그대로. `pdm.py` 템플릿 |
| `shared_alarm_event.json` | Shared `cb6dc3c` INTERFACES "Alarm Event" 예시 | 원문 그대로 (`build_alarm` 형식 비교용) |
| `shared_pdm_spectrum.json` | Shared `cb6dc3c` INTERFACES "PdM Spectrum" 예시 | 원문 스칼라 필드(`schema_version`, `sensor_id`, `timestamp`, `window_start`, `rpm`, `freq_step_hz`, `rot_hz`, `bpfo_hz`, `bpfi_hz`) 그대로. 원문 배열에는 설명 문자열(`"… 501개"`)이 있어 그대로 쓸 수 없으므로 배열 6개는 아래 식으로 합성. `pdm.py` 템플릿 |

스펙트럼 합성(`numpy.random.default_rng(20260929)`, `spectrum_x/y/z`, `envelope_x/y/z` 순서로 한 번씩 뽑음): 주파수 `f = k × freq_step_hz`,
k = 0..floor(500 / freq_step_hz)(501개), 배열마다 `|normal(0, 0.0005, 501)| + Σ c·a·exp(-0.5·((f − hz)/0.8)²)`을 계산하고
0 Hz 값을 0으로 둔 뒤 소수 4자리로 반올림한다(모두 유한한 0 이상). c = 1.0, 0.8, 0.5(x, y, z).
원 스펙트럼 봉우리: (`rot_hz`, 0.05), (2·`rot_hz`, 0.02), (3·`rot_hz`, 0.01), (`bpfo_hz`, 0.004).
포락선 봉우리: (`bpfo_hz`, 0.006), (2·`bpfo_hz`, 0.003), (3·`bpfo_hz`, 0.0015).

OPS-2의 가정 형식 스펙트럼 fixture(`pdm_spectrum_basic/envelope/nostep.json`, 느슨한 해석용)는 OPS-10에서 지웠다.
확정본에서는 그 셋이 모두 필수 필드 누락이라 거부 대상이다.

`pdm.py`는 테스트·smoke용 PdM 메시지 생성 함수다. PdM fixture를 템플릿으로 읽어 값만 바꾼다(spec D-39).
