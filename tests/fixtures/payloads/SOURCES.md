# Payload fixture 출처

`tests/conftest.py`의 `payload_examples`가 이 폴더의 `*.json`을 파일 이름(확장자 제외) → JSON 값으로 준다(spec 08 2절).
원문은 commit을 고정해 원격 Contents API로 읽었다(2026-09-27, `contract_ref`가 null이라 90-shared 2절처럼 참고로 읽음).

- Shared: `dltndn-personal-project/smart-factory-shared-repository` `docs/INTERFACES.md` @ `d0c997c97129141d9853a42ce6e0d1f8f7309ae9`
- PdM: `dltndn-personal-project/smart-factory-pdm` `docs/ARCHITECTURE.md` @ `db9b7e79ce2329104d611ab52c509e74c6b927dd`

| 파일 | 출처 | 만든 방법 |
|---|---|---|
| `shared_sensor_vibration.json` | Shared `d0c997c` INTERFACES "Sensor Vibration" 예시 | 원문 스칼라 필드(`schema_version`, `sensor_id`, `timestamp`, `seq`, `sample_rate_hz`, `rpm`, `temperature`) 그대로. 원문 배열에는 설명 문자열(`"… 1000개"`)이 있어 그대로 쓸 수 없으므로 `vibration_x/y/z`는 `numpy.random.default_rng(20260927).normal(0.0, 0.05, 1000)`을 x, y, z 순서로 뽑아 소수 4자리로 반올림 |
| `shared_product_created.json` | Shared `d0c997c` INTERFACES "Product Created" 예시 | 원문 그대로 |
| `shared_vision_result.json` | Shared `d0c997c` INTERFACES "Vision Result" 예시 | 원문 그대로 |
| `shared_conveyor_control.json` | Shared `d0c997c` INTERFACES "Conveyor Control" 예시 | 원문 그대로 (`build_conveyor` 형식 비교용) |
| `shared_line_status.json` | Shared `d0c997c` INTERFACES "Line Status" 예시 | 원문 그대로 |
| `pdm_result_draft.json` | PdM `db9b7e7` ARCHITECTURE 6.2절 PdM Result 예시 | 원문 그대로 (A-05 가정 형식. OPS-10이 Shared 확정본으로 바꾼다) |
| `pdm_spectrum_basic.json` | spec 08 3.2절 (a), PdM `db9b7e7` 6.2절 FFT Spectrum 제안(`freq_step_hz` 1.0, `spectrum_x/y/z` 501개, 소수 4자리) | 합성. 아래 식 |
| `pdm_spectrum_envelope.json` | spec 08 3.2절 (b) | basic + `envelope_y` |
| `pdm_spectrum_nostep.json` | spec 08 3.2절 (c) | basic에서 `freq_step_hz`만 뺌 |

스펙트럼 합성(`numpy.random.default_rng(20260928)`, 한 번에 순서대로 뽑음): 주파수 `f = 0..500`(1 Hz), 계열마다
`|normal(0, 0.0005, 501)| + Σ a·exp(-0.5·((f − hz)/0.8)²)`을 소수 4자리로 반올림한다.
`spectrum_x/y/z`의 봉우리는 (30 Hz, 0.05·k), (60, 0.02·k), (90, 0.01·k), (107.5, 0.004·k), k = 1.0, 0.8, 0.5.
`envelope_y`의 봉우리는 (107.5, 0.006), (215, 0.003), (322.5, 0.0015). 스칼라는
`schema_version` 1, `sensor_id` `motor01`, `timestamp` `2026-09-25T05:20:14.400Z`, `window_start` `2026-09-25T05:20:13.400Z`, `freq_step_hz` 1.0.

`pdm.py`는 테스트·smoke용 PdM 메시지 생성 함수다. PdM fixture를 템플릿으로 읽어 값만 바꾼다(spec D-39).
