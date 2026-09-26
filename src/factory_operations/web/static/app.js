/* Dashboard 동작 (docs/spec/06-dashboard.md 4·5절, docs/WIREFRAME.html).
   /api/snapshot을 1초마다 가져와 모든 칸을 다시 그린다. WebSocket·SSE 없음. 외부 요청 없음. */
(function () {
  "use strict";

  const POLL_INTERVAL_MS = 1000; // 08-verification.md 4.1절 P = 1.0초. 바꾸지 않는다(test_static.py가 검사)
  const REQUEST_TIMEOUT_MS = 3000; // 3초가 지나면 끊고 실패로 본다(4절)
  const COMMAND_TIMEOUT_MS = 5000; // 서버는 워커를 2초 기다린다(504 timeout)
  const PDM_HISTORY_S = 120;
  const PDM_HOP_S = 0.5;
  const DEBUG = new URLSearchParams(window.location.search).get("debug") === "1";

  const START_CONFIRM_TEXT =
    "현재 설비 판정이 CRITICAL입니다. 재가동하면 PdM이 다시 CRITICAL을 내는 즉시 Interlock이 라인을 멈춥니다. simulator에서 Fault Level을 먼저 낮추었는지 확인하세요.";

  // 4절 화면 문구
  const TEXT = {
    connLost: "Operations 서버 연결 끊김",
    pdmStale: "마지막 판정",
    lineStopped: "라인 정지 중 — 정지 중에는 PdM 판정이 없음",
    beforeRestart: "재가동 전 판정 — Interlock 판단에서 제외",
    pdmNone: "PdM 판정 수신 없음",
    lineOffline: "Simulator offline",
    lineStale: "Line Status 수신 없음",
    lineNone: "대기 중",
    dataAge: "초 전 데이터",
    spectrumNone: "PdM 스펙트럼 없음",
    vibrationNone: "진동 데이터 수신 없음",
    gradcamNone: "현재 범위에서 제공하지 않음",
    passThrough: "pass-through(Simulator 정보 전달)",
    imageNone: "이미지 없음",
    corrStale: "마지막 계산",
    corrNone: "상관분석 결과 없음(첫 계산 대기)",
    pending: "대기",
  };

  // 04-analysis.md 2.2절 계수 null 사유
  const REASON_TEXT = {
    insufficient_samples: "표본 부족",
    single_class: "불량 여부가 한 가지뿐(모두 양품 또는 모두 불량)",
    constant_score: "Anomaly Score가 일정함",
  };

  const STATE_BADGE = { NORMAL: "b-normal", CAUTION: "b-caution", WARNING: "b-warning", CRITICAL: "b-critical" };

  const $ = (id) => document.getElementById(id);

  // ---------------------------------------------------------------------------
  // 형식

  function esc(v) {
    return String(v === null || v === undefined ? "" : v)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function isNum(v) {
    return typeof v === "number" && isFinite(v);
  }

  function num(v, digits) {
    return isNum(v) ? v.toFixed(digits) : "—";
  }

  function orDash(v) {
    return v === null || v === undefined || v === "" ? "—" : String(v);
  }

  function pad(n, w) {
    return String(n).padStart(w || 2, "0");
  }

  // ISO 시각 → 브라우저 지역 시각 HH:MM:SS.mmm
  function hms(iso) {
    if (!iso) return "—";
    const d = new Date(iso);
    if (isNaN(d.getTime())) return String(iso);
    return pad(d.getHours()) + ":" + pad(d.getMinutes()) + ":" + pad(d.getSeconds()) + "." + pad(d.getMilliseconds(), 3);
  }

  function secs(v) {
    return isNum(v) ? String(Math.round(v)) : "?";
  }

  function badgeClass(state, stale) {
    return stale ? "b-stale" : STATE_BADGE[state] || "b-stale";
  }

  // 같은 내용이면 DOM을 건드리지 않는다(이미지 재요청·깜빡임 방지).
  function setHTML(el, html) {
    if (el._html !== html) {
      el.innerHTML = html;
      el._html = html;
    }
  }

  function setText(el, text) {
    const t = String(text);
    if (el.textContent !== t) el.textContent = t;
  }

  function setClass(el, cls) {
    if (el.className !== cls) el.className = cls;
  }

  function imageUrl(path) {
    return "/api/images/" + String(path).split("/").map(encodeURIComponent).join("/");
  }

  // ---------------------------------------------------------------------------
  // 칸마다 그리기

  function renderHeader(s) {
    setText($("generated-at"), s.generated_at || "—");
    setClass($("mqtt-state"), "meta " + (s.mqtt_connected ? "ok" : "bad"));
    setClass($("db-state"), "meta " + (s.db_ok ? "ok" : "bad"));
  }

  function renderLine(s) {
    const line = s.line || { status: "NONE" };
    const il = s.interlock || {};
    let note = "";
    if (line.status === "NONE") note = TEXT.lineNone;
    else if (line.status === "OFFLINE") note = TEXT.lineOffline;
    else if (line.status === "STALE") note = TEXT.lineStale + "(" + secs(line.age_s) + "초)";
    setText($("line-note"), note);

    const conv = line.conveyor;
    const cls = conv === "RUNNING" ? "run" : conv === "STOPPED" ? "stop" : "";
    setClass($("line-conveyor"), "big " + cls + (line.status === "OFFLINE" || line.status === "NONE" ? " dim" : ""));
    setText($("line-conveyor"), orDash(conv));
    setText($("line-fault"), orDash(line.fault_level));
    setText($("line-production"), line.production_active === true ? "예" : line.production_active === false ? "아니오" : "—");
    setText($("line-rpm"), isNum(line.motor_rpm) ? line.motor_rpm.toFixed(1) + " rpm" : "—");
    setText($("line-created"), line.products ? orDash(line.products.created) : "—");

    const lineState = il.line_state === "UNKNOWN" ? "알 수 없음" : orDash(il.line_state);
    const parts = ["라인 상태 " + lineState];
    parts.push(il.pending_stop ? "대기 중 STOP (" + num(il.pending_stop.age_s, 1) + "초)" : "대기 중 STOP 없음");
    parts.push(il.last_trigger_timestamp ? "마지막 trigger " + hms(il.last_trigger_timestamp) : "trigger 없음");
    if (il.judged) parts.push("판정 " + il.judged.state);
    setText($("line-interlock"), parts.join(" · "));

    const lc = line.last_command;
    setText(
      $("line-last-command"),
      lc ? [lc.command, lc.result || "결과 없음", lc.reason, lc.source, lc.error].filter(Boolean).join(" · ") : "—"
    );
  }

  function renderPdm(s) {
    const p = s.pdm || { status: "NONE" };
    const line = s.line || {};
    const stale = p.status !== "LIVE";
    let title = "설비 상태 (PdM)";
    if (p.status === "STALE") title += " · " + TEXT.pdmStale + " · " + secs(p.age_s) + "초 전";
    setText($("pdm-title"), title);

    const badge = $("pdm-state");
    setClass(badge, "badge " + badgeClass(p.state, stale));
    setText(badge, p.state || "—");
    setClass($("pdm-values"), "row" + (stale ? " dim" : ""));
    setText($("pdm-hi"), orDash(p.health_index));
    setText($("pdm-score"), num(p.anomaly_score, 2));
    setText($("pdm-time"), p.timestamp ? "판정 " + hms(p.timestamp) + " · " + num(p.age_s, 1) + "초 전" : "");

    const notes = [];
    if (p.status === "NONE") notes.push(TEXT.pdmNone);
    if (p.status === "STALE" && line.conveyor === "STOPPED") notes.push(TEXT.lineStopped);
    if (p.before_restart) notes.push(TEXT.beforeRestart);
    setText($("pdm-notes"), notes.join(" · "));

    // 최근 120초를 0.5초 칸으로 펼친다(빈 칸 = 결과 없음, 선이 끊긴다). 끝 = 마지막 판정 + 경과
    const n = Math.round(PDM_HISTORY_S / PDM_HOP_S) + 1;
    const hi = new Array(n).fill(null);
    const score = new Array(n).fill(null);
    const end = p.timestamp ? Date.parse(p.timestamp) + (isNum(p.age_s) ? p.age_s * 1000 : 0) : null;
    if (end !== null && Array.isArray(p.history)) {
      for (const h of p.history) {
        const idx = Math.round((Date.parse(h.timestamp) - end) / (PDM_HOP_S * 1000)) + n - 1;
        if (idx < 0 || idx >= n) continue;
        hi[idx] = isNum(h.health_index) ? h.health_index : null;
        score[idx] = isNum(h.anomaly_score) ? h.anomaly_score * 100 : null;
      }
    }
    Plot.drawLines($("pdm-chart"), {
      x: { start: -PDM_HISTORY_S, step: PDM_HOP_S, unit: "s" },
      series: [
        { values: hi, label: "HI", colorVar: stale ? "--stale" : "--accent" },
        { values: score, label: "Anomaly Score ×100", colorVar: "--series2" },
      ],
      y: { min: 0, max: 100 },
      hlines: [
        { value: 80, label: "80" },
        { value: 60, label: "60" },
        { value: 40, label: "40" },
      ],
    });
  }

  function renderVibration(s) {
    const v = s.vibration || { status: "NONE" };
    let note = "";
    if (v.status === "NONE") note = TEXT.vibrationNone;
    else if (v.status === "STALE") note = secs(v.age_s) + TEXT.dataAge;
    setText($("vibration-note"), note);
    const axes = [
      ["x", "--band-x"],
      ["y", "--band-y"],
      ["z", "--band-z"],
    ];
    for (const [axis, colorVar] of axes) {
      const a = v[axis] || { min: [], max: [] };
      Plot.drawBands($("vib-" + axis), {
        min: a.min,
        max: a.max,
        colorVar: v.status === "STALE" ? "--stale" : colorVar,
        window_s: v.window_s || 1,
        label: axis + " (g)",
      });
    }
    const meta = ["x · y · z 축별 min/max 띠"];
    if (v.status !== "NONE") {
      meta.push("온도 " + num(v.temperature, 1) + " °C");
      meta.push(num(v.rpm, 1) + " rpm");
      meta.push(num(v.window_s, 2) + "초 · " + orDash(v.sample_rate_hz) + " Hz");
      if (v.timestamp) meta.push(hms(v.timestamp));
    }
    setText($("vibration-meta"), meta.join(" · "));
  }

  function renderSpectrum(s) {
    const sp = s.spectrum || { status: "NONE" };
    const panels = sp.status === "NONE" ? [] : sp.panels || [];
    let note = "";
    if (sp.status === "NONE" || panels.length === 0) note = TEXT.spectrumNone;
    else if (sp.status === "STALE") note = secs(sp.age_s) + TEXT.dataAge;
    setText($("spectrum-note"), note);
    const box = $("spectrum-panels");
    setHTML(
      box,
      panels
        .map((p, i) => '<div class="note">' + esc(p.title) + '</div><canvas class="chart" data-panel="' + i + '" aria-label="' + esc(p.title) + '"></canvas>')
        .join("")
    );
    panels.forEach((p, i) => {
      const canvas = box.querySelector('canvas[data-panel="' + i + '"]');
      Plot.drawLines(canvas, {
        x: { start: p.x_start, step: p.x_step, unit: p.x_unit },
        series: (p.series || []).map((sr, j) => ({
          values: sr.values,
          label: sr.name,
          colorVar: sp.status === "STALE" ? "--stale" : ["--band-x", "--band-y", "--band-z", "--series3"][j % 4],
        })),
        y: { min: 0 },
      });
    });
  }

  function thumbHTML(r) {
    const img = r.image_path
      ? '<img loading="lazy" src="' + esc(imageUrl(r.image_path)) + '" alt="' + esc(r.product_id) + '" data-view="' + esc(r.image_path) + '" data-caption="' + esc(r.product_id) + '">'
      : esc(TEXT.imageNone);
    let verdict;
    if (r.defect === true) verdict = '<span class="defect-text">불량</span> · ' + esc(orDash(r.defect_type));
    else if (r.defect === false) verdict = "양품";
    else verdict = "판정 없음";
    const gradcam = r.gradcam_path
      ? '<button type="button" class="linkish" data-view="' + esc(r.gradcam_path) + '" data-caption="' + esc(r.product_id + " Grad-CAM") + '">보기</button>'
      : esc(TEXT.gradcamNone);
    const source = r.judgement_source === "PASS_THROUGH" ? TEXT.passThrough : orDash(r.judgement_source);
    return (
      '<div class="thumb' + (r.defect === true ? " defect" : "") + '">' +
      '<div class="img">' + img + "</div>" +
      "<b>" + esc(r.product_id) + "</b><br>" +
      verdict + "<br>" +
      "Confidence " + esc(isNum(r.confidence) ? r.confidence.toFixed(4) : "—") + "<br>" +
      "Grad-CAM " + gradcam + "<br>" +
      esc(source) + "<br>" +
      "캡처 " + esc(hms(r.timestamp)) + " · HI " + esc(orDash(r.health_index_at_time)) +
      "</div>"
    );
  }

  function renderQuality(s) {
    const pr = s.production;
    setText($("q-rate"), pr && isNum(pr.defect_rate) ? (pr.defect_rate * 100).toFixed(1) + "%" : "—");
    setText($("q-produced"), pr ? orDash(pr.produced) : "—");
    setText($("q-inspected"), pr ? orDash(pr.inspected) : "—");
    setText($("q-defects"), pr ? orDash(pr.defects) : "—");
    const rows = s.inspections || [];
    const empty = s.db_ok ? "검사 결과 없음" : "DB 연결 끊김 — 요약 없음";
    setHTML($("q-thumbs"), rows.length ? rows.map(thumbHTML).join("") : '<div class="note">' + esc(empty) + "</div>");
  }

  function coefText(r) {
    if (!r) return "—";
    if (!isNum(r.pearson)) return "lag " + r.lag_s + "초 · " + (REASON_TEXT[r.reason] || orDash(r.reason)) + " · n " + orDash(r.n);
    return "lag " + r.lag_s + "초 · Pearson " + r.pearson.toFixed(2) + " · Spearman " + num(r.spearman, 2) + " · n " + orDash(r.n);
  }

  function renderCorrelation(s) {
    const c = s.correlation;
    let title = "설비-품질 상관관계";
    if (c && c.stale) {
      const ago = (Date.parse(s.generated_at) - Date.parse(c.computed_at)) / 1000;
      title += " · " + TEXT.corrStale + " · " + secs(ago) + "초 전";
    }
    setText($("corr-title"), title);
    if (!c) {
      setText($("corr-default"), TEXT.corrNone);
      setText($("corr-best"), "");
    } else {
      setText($("corr-default"), "기본 " + coefText(c.at_default));
      setText(
        $("corr-best"),
        c.best ? "최대 |Pearson| lag " + c.best.lag_s + "초 (" + num(c.best.pearson, 2) + ")" : "최대 |Pearson| lag 없음(모든 lag " + (REASON_TEXT[(c.at_default || {}).reason] || "계수 없음") + ")"
      );
    }
    const curve = (c && c.curve) || [];
    const step = curve.length > 1 ? curve[1].lag_s - curve[0].lag_s : 1;
    Plot.drawLines($("corr-curve"), {
      x: { start: curve.length ? curve[0].lag_s : 0, step: step, unit: "s" },
      series: [
        { values: curve.map((r) => r.pearson), label: "Pearson", colorVar: c && c.stale ? "--stale" : "--accent" },
        { values: curve.map((r) => r.spearman), label: "Spearman", colorVar: "--series2" },
      ],
      y: { min: -1, max: 1, label: "lag별 계수" },
      hlines: [0],
    });
    const bins = (c && c.bins) || [];
    Plot.drawBars($("corr-bins"), {
      labels: bins.length ? [hms(bins[0].start).slice(0, 8), hms(bins[bins.length - 1].start).slice(0, 8)] : [],
      bars: { values: bins.map((b) => b.defect_rate), label: "불량률(30초)", colorVar: "--bar" },
      line: { values: bins.map((b) => b.mean_anomaly), label: "평균 Anomaly Score", colorVar: "--accent" },
      y: { min: 0, max: 1 },
    });
  }

  function emptyRow(cols, s, what) {
    const text = s.db_ok ? what + " 없음" : "DB 연결 끊김 — 요약 없음";
    return '<tr><td class="empty" colspan="' + cols + '">' + esc(text) + "</td></tr>";
  }

  function renderAlarms(s) {
    const rows = s.alarms || [];
    setHTML(
      $("alarms-body"),
      rows.length
        ? rows
            .map(
              (a) =>
                "<tr><td>" + esc(hms(a.timestamp)) + "</td>" +
                '<td><span class="badge ' + badgeClass(a.severity, false) + '">' + esc(a.severity) + "</span></td>" +
                "<td>" + esc(orDash(a.previous_state)) + " → " + esc(a.severity) + "</td>" +
                "<td>" + esc(orDash(a.health_index)) + "</td>" +
                "<td>" + esc(num(a.anomaly_score, 2)) + "</td></tr>"
            )
            .join("")
        : emptyRow(5, s, "Alarm")
    );
  }

  function renderControls(s) {
    const rows = s.controls || [];
    setHTML(
      $("controls-body"),
      rows.length
        ? rows
            .map(
              (c) =>
                "<tr><td>" + esc(hms(c.recorded_at)) + "</td>" +
                "<td>" + esc(c.command) + "</td>" +
                "<td>" + esc(orDash(c.reason)) + "</td>" +
                "<td>" + esc(orDash(c.origin) + (c.source ? " / " + c.source : "")) + "</td>" +
                "<td" + (c.result === "REJECTED" ? ' class="cmd-error"' : "") + ">" + esc(c.result || TEXT.pending) + "</td>" +
                "<td>" + esc(c.error || "") + "</td></tr>"
            )
            .join("")
        : emptyRow(6, s, "명령")
    );
  }

  function render(s) {
    const x = window.scrollX;
    const y = window.scrollY;
    renderHeader(s);
    renderLine(s);
    renderPdm(s);
    renderVibration(s);
    renderSpectrum(s);
    renderQuality(s);
    renderCorrelation(s);
    renderAlarms(s);
    renderControls(s);
    if (window.scrollX !== x || window.scrollY !== y) window.scrollTo(x, y); // 스크롤 위치 유지
  }

  // ---------------------------------------------------------------------------
  // polling

  let inFlight = false;
  let lastSnapshot = null;
  let lastOkAt = null; // performance.now() 기준
  let lastResponseMs = null;
  let lastRenderMs = null;
  let failed = false;

  function setConnLost(lost) {
    failed = lost;
    const banner = $("conn-lost");
    if (banner.hidden === lost) banner.hidden = !lost;
  }

  function renderAgo() {
    const el = $("updated-ago");
    if (lastOkAt === null) setText(el, failed ? TEXT.connLost : "갱신 대기 중");
    else setText(el, Math.floor((performance.now() - lastOkAt) / 1000) + "초 전 갱신");
    setClass(el, "meta" + (failed ? " bad" : ""));
    if (DEBUG) {
      const d = $("debug-info");
      d.hidden = false;
      setText(d, "응답 " + num(lastResponseMs, 0) + " ms · 렌더링 " + num(lastRenderMs, 1) + " ms");
    }
  }

  function poll() {
    if (inFlight) return; // 이전 요청이 끝나지 않았으면 건너뛴다
    inFlight = true;
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), REQUEST_TIMEOUT_MS);
    const t0 = performance.now();
    fetch("/api/snapshot", { cache: "no-store", signal: ctrl.signal })
      .then((r) => {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then((snap) => {
        const t1 = performance.now(); // 응답 처리 시작
        lastResponseMs = t1 - t0;
        render(snap);
        lastRenderMs = performance.now() - t1; // 그리기 끝까지(08 4.1절 R)
        lastSnapshot = snap;
        lastOkAt = performance.now();
        setConnLost(false);
      })
      .catch(() => setConnLost(true)) // 마지막 화면 유지
      .finally(() => {
        clearTimeout(timer);
        inFlight = false;
        renderAgo();
      });
  }

  // ---------------------------------------------------------------------------
  // 버튼

  function setCommandResult(text, isError) {
    const el = $("cmd-result");
    setText(el, text);
    setClass(el, "note" + (isError ? " cmd-error" : ""));
  }

  function sendCommand(command) {
    const judged = lastSnapshot && lastSnapshot.interlock ? lastSnapshot.interlock.judged : null;
    if (command === "START" && judged && judged.state === "CRITICAL") {
      if (!window.confirm(START_CONFIRM_TEXT)) return; // 막지 않고 경고한다(D-24)
    }
    const buttons = [$("btn-start"), $("btn-stop")];
    buttons.forEach((b) => (b.disabled = true));
    setCommandResult(command + " 보내는 중", false);
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), COMMAND_TIMEOUT_MS);
    fetch("/api/conveyor", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ command: command }),
      cache: "no-store",
      signal: ctrl.signal,
    })
      .then((r) =>
        r
          .json()
          .catch(() => ({}))
          .then((body) => ({ status: r.status, body: body || {} }))
      )
      .then(({ status, body }) => {
        if (status === 202) setCommandResult(command + " 보냄 · " + hms(body.timestamp), false);
        else setCommandResult(command + " 실패 · " + status + " " + (body.error || "error"), true);
      })
      .catch(() => setCommandResult(command + " 실패 · network_error", true))
      .finally(() => {
        clearTimeout(timer);
        buttons.forEach((b) => (b.disabled = false));
      });
  }

  // ---------------------------------------------------------------------------
  // 원본 보기

  function openViewer(path, caption) {
    $("viewer-img").src = imageUrl(path);
    setText($("viewer-caption"), caption || path);
    $("viewer").hidden = false;
  }

  function closeViewer() {
    $("viewer").hidden = true;
    $("viewer-img").removeAttribute("src");
  }

  function init() {
    $("btn-start").addEventListener("click", () => sendCommand("START"));
    $("btn-stop").addEventListener("click", () => sendCommand("STOP"));
    const thumbs = $("q-thumbs");
    thumbs.addEventListener("click", (e) => {
      const t = e.target.closest("[data-view]");
      if (t) openViewer(t.getAttribute("data-view"), t.getAttribute("data-caption"));
    });
    // 썸네일 로드 실패 → "이미지 없음" (error는 버블링되지 않아 capture로 받는다)
    thumbs.addEventListener(
      "error",
      (e) => {
        const img = e.target;
        if (img && img.tagName === "IMG" && img.parentNode) img.parentNode.textContent = TEXT.imageNone;
      },
      true
    );
    $("viewer").addEventListener("click", closeViewer);
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") closeViewer();
    });
    $("viewer-img").addEventListener("error", () => setText($("viewer-caption"), TEXT.imageNone));
    window.addEventListener("resize", () => {
      if (lastSnapshot) render(lastSnapshot);
    });
    poll();
    setInterval(poll, POLL_INTERVAL_MS); // 요청 시작 시각 기준 1초마다
    setInterval(renderAgo, 250);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
