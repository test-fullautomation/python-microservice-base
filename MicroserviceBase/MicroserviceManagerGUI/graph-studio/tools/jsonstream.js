// Incremental splitter for grpcurl's streaming output: a sequence of
// pretty-printed JSON objects with no delimiter. Feed chunks, get objects.
// Plain CommonJS module (no Electron) so it can be unit-tested with node.
"use strict";

class JsonObjectStream {
  constructor(onObject, onError) {
    this._onObject = onObject;
    this._onError = onError || (() => {});
    this._buf = "";
    this._depth = 0;
    this._start = -1;
    this._inString = false;
    this._escape = false;
  }

  feed(chunk) {
    const text = String(chunk);
    for (let i = 0; i < text.length; i++) {
      const ch = text[i];
      this._buf += ch;
      const pos = this._buf.length - 1;
      if (this._inString) {
        if (this._escape) this._escape = false;
        else if (ch === "\\") this._escape = true;
        else if (ch === '"') this._inString = false;
        continue;
      }
      if (ch === '"') { this._inString = true; continue; }
      if (ch === "{") {
        if (this._depth === 0) this._start = pos;
        this._depth++;
      } else if (ch === "}") {
        this._depth--;
        if (this._depth === 0 && this._start >= 0) {
          const raw = this._buf.slice(this._start, pos + 1);
          this._buf = "";
          this._start = -1;
          try { this._onObject(JSON.parse(raw)); }
          catch (e) { this._onError(e, raw); }
        } else if (this._depth < 0) {
          this._depth = 0; // stray brace — resync
          this._buf = "";
        }
      }
    }
    // keep the buffer from growing on non-JSON noise between objects
    if (this._depth === 0 && this._buf.length > 65536) this._buf = "";
  }
}

module.exports = { JsonObjectStream };
