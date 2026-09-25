// Time series for the charts plugin: pure functions, no DOM (tested in Node).

/** "120s" | "5m" -> milliseconds; default 60 s. */
export function parseWindow(s) {
  const m = /^(\d+)(s|m)$/.exec(String(s || ''));
  if (!m) return 60000;
  return Number(m[1]) * (m[2] === 'm' ? 60000 : 1000);
}

/**
 * Samples of one signal inside a sliding time window.
 * push(tMs, value) keeps them ordered; older samples than the window drop.
 */
export class Series {
  constructor(windowMs, maxPoints = 2000) {
    this.windowMs = windowMs;
    this.maxPoints = maxPoints;
    this.t = [];
    this.v = [];
  }

  push(tMs, value) {
    if (typeof value !== 'number' || !isFinite(value)) return;
    const n = this.t.length;
    if (n && tMs < this.t[n - 1]) tMs = this.t[n - 1];   // clocks may step back; keep order
    this.t.push(tMs);
    this.v.push(value);
    if (this.t.length > this.maxPoints) { this.t.splice(0, this.t.length - this.maxPoints); this.v.splice(0, this.v.length - this.maxPoints); }
    this.trim(tMs);
  }

  trim(nowMs) {
    const cut = nowMs - this.windowMs;
    let i = 0;
    // keep one sample before the window so the line starts at the left edge
    while (i + 1 < this.t.length && this.t[i + 1] < cut) i++;
    if (i) { this.t.splice(0, i); this.v.splice(0, i); }
  }

  get length() { return this.t.length; }
  get last() { return this.v.length ? this.v[this.v.length - 1] : undefined; }

  /** [min, max] of the values, padded so a flat line sits in the middle. */
  range(fixedMin, fixedMax) {
    let lo = fixedMin, hi = fixedMax;
    if (lo == null || hi == null) {
      let mn = Infinity, mx = -Infinity;
      for (const x of this.v) { if (x < mn) mn = x; if (x > mx) mx = x; }
      if (!isFinite(mn)) { mn = 0; mx = 1; }
      if (mn === mx) { mn -= 1; mx += 1; }
      const pad = (mx - mn) * 0.1;
      if (lo == null) lo = mn - pad;
      if (hi == null) hi = mx + pad;
    }
    return [lo, hi];
  }

  /** Samples mapped to pixel coordinates of a w x h box ending at nowMs. */
  toPixels(nowMs, w, h, lo, hi) {
    const x0 = nowMs - this.windowMs;
    const span = hi - lo || 1;
    const out = [];
    for (let i = 0; i < this.t.length; i++) {
      out.push([((this.t[i] - x0) / this.windowMs) * w, h - ((this.v[i] - lo) / span) * h]);
    }
    return out;
  }
}
