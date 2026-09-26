/* canvas 2D 차트 (docs/spec/06-dashboard.md 5절, DECISIONS D-12).
   선 그래프, min/max 띠, 막대 세 가지만 그린다. 축 눈금·범례·가로선만 있고 확대·툴팁은 없다.
   색은 style.css의 CSS 변수 이름(colorVar, 예: "--accent")으로 받아 그릴 때마다 읽는다(테마 전환 반영).
   값 null은 빈 곳이다(선이 끊긴다). 외부 라이브러리 없음. */
(function (global) {
  "use strict";

  const PAD = { left: 44, right: 10, top: 18, bottom: 18 };
  const FONT = "11px ui-monospace, Menlo, monospace";

  function cssVar(name, fallback) {
    const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return v || fallback || "#888";
  }

  // canvas 픽셀 크기를 CSS 크기 × devicePixelRatio에 맞추고 논리 좌표(CSS px)로 그리는 context를 돌려준다.
  function setup(canvas) {
    const dpr = global.devicePixelRatio || 1;
    const w = Math.max(1, canvas.clientWidth);
    const h = Math.max(1, canvas.clientHeight);
    if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
    }
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    ctx.font = FONT;
    ctx.lineJoin = "round";
    return { ctx, w, h };
  }

  function isNum(v) {
    return typeof v === "number" && isFinite(v);
  }

  // 1·2·5 × 10^k 간격의 눈금
  function niceStep(range, count) {
    if (!(range > 0)) return 1;
    const raw = range / Math.max(1, count);
    const mag = Math.pow(10, Math.floor(Math.log10(raw)));
    const f = raw / mag;
    const nice = f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10;
    return nice * mag;
  }

  function ticks(min, max, count) {
    const step = niceStep(max - min, count);
    const out = [];
    const first = Math.ceil(min / step - 1e-9) * step;
    for (let v = first; v <= max + step * 1e-9; v += step) out.push(Math.abs(v) < step * 1e-9 ? 0 : v);
    return { values: out, step };
  }

  function fmt(v, step) {
    if (step >= 1 || v === 0) return String(Math.round(v * 1000) / 1000);
    const d = Math.min(6, Math.max(0, -Math.floor(Math.log10(step))));
    return v.toFixed(d);
  }

  // 값 범위: 주어진 min/max가 우선, 없으면 데이터에서(여유 5%)
  function range(arrays, yopt) {
    let lo = Infinity;
    let hi = -Infinity;
    for (const a of arrays) {
      for (const v of a || []) {
        if (isNum(v)) {
          if (v < lo) lo = v;
          if (v > hi) hi = v;
        }
      }
    }
    const y = yopt || {};
    if (!isFinite(lo)) { lo = 0; hi = 1; }
    if (lo === hi) { lo -= 0.5; hi += 0.5; }
    const pad = (hi - lo) * 0.05;
    return {
      min: isNum(y.min) ? y.min : lo - pad,
      max: isNum(y.max) ? y.max : hi + pad,
    };
  }

  function frame(ctx, w, h, xr, yr, xunit, ylabel) {
    const plot = { x0: PAD.left, x1: w - PAD.right, y0: PAD.top, y1: h - PAD.bottom };
    const X = (v) => plot.x0 + ((v - xr.min) / (xr.max - xr.min || 1)) * (plot.x1 - plot.x0);
    const Y = (v) => plot.y1 - ((v - yr.min) / (yr.max - yr.min || 1)) * (plot.y1 - plot.y0);
    const hair = cssVar("--hair");
    const muted = cssVar("--muted");
    ctx.lineWidth = 1;
    ctx.fillStyle = muted;
    // y 눈금
    const yt = ticks(yr.min, yr.max, Math.max(2, Math.floor((plot.y1 - plot.y0) / 22)));
    ctx.textAlign = "right";
    ctx.textBaseline = "middle";
    for (const v of yt.values) {
      const y = Math.round(Y(v)) + 0.5;
      ctx.strokeStyle = hair;
      ctx.beginPath(); ctx.moveTo(plot.x0, y); ctx.lineTo(plot.x1, y); ctx.stroke();
      ctx.fillText(fmt(v, yt.step), plot.x0 - 4, y);
    }
    // x 눈금
    const xt = ticks(xr.min, xr.max, Math.max(2, Math.floor((plot.x1 - plot.x0) / 70)));
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    for (const v of xt.values) {
      const x = Math.round(X(v)) + 0.5;
      ctx.strokeStyle = hair;
      ctx.beginPath(); ctx.moveTo(x, plot.y1); ctx.lineTo(x, plot.y1 + 3); ctx.stroke();
      ctx.fillText(fmt(v, xt.step) + (xunit ? " " + xunit : ""), x, plot.y1 + 4);
    }
    // 축
    ctx.strokeStyle = cssVar("--line");
    ctx.beginPath(); ctx.moveTo(plot.x0 + 0.5, plot.y0); ctx.lineTo(plot.x0 + 0.5, plot.y1 + 0.5); ctx.lineTo(plot.x1, plot.y1 + 0.5); ctx.stroke();
    if (ylabel) {
      ctx.textAlign = "right";
      ctx.textBaseline = "top";
      ctx.fillText(ylabel, plot.x1, 2);
    }
    return { plot, X, Y };
  }

  function legend(ctx, items, x0) {
    let x = x0;
    ctx.textAlign = "left";
    ctx.textBaseline = "top";
    for (const it of items) {
      ctx.fillStyle = cssVar(it.colorVar, it.fallback);
      ctx.fillRect(x, 5, 10, 3);
      ctx.fillStyle = cssVar("--ink");
      ctx.fillText(it.label, x + 14, 2);
      x += 14 + ctx.measureText(it.label).width + 12;
    }
  }

  const SERIES_VARS = ["--accent", "--series2", "--series3", "--normal", "--warning", "--critical"];

  /* drawLines(canvas, {x: {start, step, unit}, series: [{values, label, colorVar}], y: {min, max, label}, hlines})
     hlines: 숫자 또는 {value, label} 목록(가로 기준선). */
  function drawLines(canvas, opts) {
    const { ctx, w, h } = setup(canvas);
    const series = (opts && opts.series) || [];
    const x = (opts && opts.x) || { start: 0, step: 1 };
    const step = isNum(x.step) && x.step > 0 ? x.step : 1;
    const start = isNum(x.start) ? x.start : 0;
    const n = series.reduce((m, s) => Math.max(m, (s.values || []).length), 0);
    const xr = { min: start, max: start + step * Math.max(1, n - 1) };
    const yr = range(series.map((s) => s.values), opts.y);
    const { plot, X, Y } = frame(ctx, w, h, xr, yr, x.unit, opts.y && opts.y.label);

    ctx.save();
    ctx.beginPath(); ctx.rect(plot.x0, plot.y0 - 1, plot.x1 - plot.x0, plot.y1 - plot.y0 + 2); ctx.clip();
    for (const hl of opts.hlines || []) {
      const v = typeof hl === "number" ? hl : hl.value;
      if (!isNum(v)) continue;
      const y = Math.round(Y(v)) + 0.5;
      ctx.strokeStyle = cssVar("--line");
      ctx.setLineDash([4, 3]);
      ctx.beginPath(); ctx.moveTo(plot.x0, y); ctx.lineTo(plot.x1, y); ctx.stroke();
      ctx.setLineDash([]);
      if (typeof hl === "object" && hl.label) {
        ctx.fillStyle = cssVar("--muted");
        ctx.textAlign = "left";
        ctx.textBaseline = "bottom";
        ctx.fillText(hl.label, plot.x0 + 3, y - 1);
      }
    }
    ctx.lineWidth = 1.5;
    series.forEach((s, i) => {
      ctx.strokeStyle = cssVar(s.colorVar || SERIES_VARS[i % SERIES_VARS.length]);
      ctx.beginPath();
      let pen = false;
      (s.values || []).forEach((v, j) => {
        if (!isNum(v)) { pen = false; return; }
        const px = X(start + j * step);
        const py = Y(v);
        if (pen) ctx.lineTo(px, py); else { ctx.moveTo(px, py); pen = true; }
      });
      ctx.stroke();
      // 이웃 없이 혼자인 점은 점으로
      (s.values || []).forEach((v, j, a) => {
        if (isNum(v) && !isNum(a[j - 1]) && !isNum(a[j + 1])) {
          ctx.fillStyle = ctx.strokeStyle;
          ctx.fillRect(X(start + j * step) - 1.5, Y(v) - 1.5, 3, 3);
        }
      });
    });
    ctx.restore();
    legend(ctx, series.map((s, i) => ({ label: s.label || "", colorVar: s.colorVar || SERIES_VARS[i % SERIES_VARS.length] })), plot.x0);
  }

  /* drawBands(canvas, {min, max, colorVar, window_s, label})
     구간별 최솟값·최댓값 배열을 0~window_s초 가로축의 띠로 그린다. */
  function drawBands(canvas, opts) {
    const { ctx, w, h } = setup(canvas);
    const lo = (opts && opts.min) || [];
    const hi = (opts && opts.max) || [];
    const n = Math.min(lo.length, hi.length);
    const win = isNum(opts.window_s) && opts.window_s > 0 ? opts.window_s : 1;
    const xr = { min: 0, max: win };
    const yr = range([lo, hi], opts.y);
    const { plot, X, Y } = frame(ctx, w, h, xr, yr, "s", null);
    const color = cssVar(opts.colorVar || "--accent");
    if (n > 0) {
      const xAt = (i) => X(n === 1 ? win / 2 : (i / (n - 1)) * win);
      ctx.save();
      ctx.beginPath(); ctx.rect(plot.x0, plot.y0, plot.x1 - plot.x0, plot.y1 - plot.y0); ctx.clip();
      ctx.beginPath();
      for (let i = 0; i < n; i++) (i ? ctx.lineTo : ctx.moveTo).call(ctx, xAt(i), Y(hi[i]));
      for (let i = n - 1; i >= 0; i--) ctx.lineTo(xAt(i), Y(lo[i]));
      ctx.closePath();
      ctx.globalAlpha = 0.35;
      ctx.fillStyle = color;
      ctx.fill();
      ctx.globalAlpha = 1;
      ctx.lineWidth = 1;
      ctx.strokeStyle = color;
      ctx.stroke();
      ctx.restore();
    }
    if (opts.label) legend(ctx, [{ label: opts.label, colorVar: opts.colorVar || "--accent" }], plot.x0);
  }

  /* drawBars(canvas, {labels, bars: {values, label, colorVar}, line: {values, label, colorVar}, y: {min, max, label}})
     구간마다 막대 하나와, 같은 구간 중앙을 잇는 선 하나(선택). 값 null이면 그 구간은 비운다. */
  function drawBars(canvas, opts) {
    const { ctx, w, h } = setup(canvas);
    const bars = (opts && opts.bars) || { values: [] };
    const line = opts && opts.line;
    const labels = (opts && opts.labels) || [];
    const n = Math.max((bars.values || []).length, line ? (line.values || []).length : 0);
    const yr = range([bars.values, line ? line.values : []], opts.y);
    // 가로축은 구간 번호(0..n). 눈금 대신 첫·끝 구간 라벨만 쓴다.
    const plot = { x0: PAD.left, x1: w - PAD.right, y0: PAD.top, y1: h - PAD.bottom };
    const fr = frame(ctx, w, h, { min: 0, max: Math.max(1, n) }, yr, null, opts.y && opts.y.label);
    // frame이 그린 x 눈금 숫자를 지우고 구간 라벨로 대신한다
    ctx.clearRect(0, plot.y1 + 1, w, PAD.bottom);
    const Y = fr.Y;
    const bw = (plot.x1 - plot.x0) / Math.max(1, n);
    const base = Y(Math.max(yr.min, 0));
    ctx.fillStyle = cssVar(bars.colorVar || "--bar");
    (bars.values || []).forEach((v, i) => {
      if (!isNum(v)) return;
      const y = Y(v);
      ctx.fillRect(plot.x0 + i * bw + bw * 0.12, Math.min(y, base), bw * 0.76, Math.max(1, Math.abs(base - y)));
    });
    if (line) {
      ctx.strokeStyle = cssVar(line.colorVar || "--accent");
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      let pen = false;
      (line.values || []).forEach((v, i) => {
        if (!isNum(v)) { pen = false; return; }
        const px = plot.x0 + (i + 0.5) * bw;
        if (pen) ctx.lineTo(px, Y(v)); else { ctx.moveTo(px, Y(v)); pen = true; }
      });
      ctx.stroke();
    }
    ctx.fillStyle = cssVar("--muted");
    ctx.textBaseline = "top";
    if (labels.length) {
      ctx.textAlign = "left";
      ctx.fillText(String(labels[0]), plot.x0, plot.y1 + 4);
      if (labels.length > 1) {
        ctx.textAlign = "right";
        ctx.fillText(String(labels[labels.length - 1]), plot.x1, plot.y1 + 4);
      }
    }
    const items = [];
    if (bars.label) items.push({ label: bars.label, colorVar: bars.colorVar || "--bar" });
    if (line && line.label) items.push({ label: line.label, colorVar: line.colorVar || "--accent" });
    legend(ctx, items, plot.x0);
  }

  global.Plot = { drawLines, drawBands, drawBars };
})(window);
