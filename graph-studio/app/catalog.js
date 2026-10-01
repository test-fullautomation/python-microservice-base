// Block catalog — the editor's source of truth for which block types exist,
// their ports and their params.
//
// PHASE C: DEFAULT_CATALOG below is GENERATED — do not hand-edit. Regenerate
// with:
//   python tools/generate_catalog.py <path-to-blocks.py> --update-tool .
// (AST introspection of signal_graph/core/domain/blocks.py; also refreshes
// blocks_catalog.json, which the Electron shell prefers at runtime.)
// Tool-level param types: device_ref (must resolve via device_services),
// signal_ref (live picker from signal-discovery), enum (+ `choices`, dropdown;
// a value outside the list is a validation error).
"use strict";

const DEFAULT_CATALOG = {
  "catalog_version": "generated-2026-09-25",
  "blocks": [
    {
      "type": "AdcBlock",
      "family": "source",
      "doc": "Reads an analog input channel from a device service each cycle.",
      "inputs": [],
      "outputs": [
        {
          "name": "out",
          "type": "float"
        }
      ],
      "params": [
        {
          "name": "channel",
          "type": "int",
          "required": true
        },
        {
          "name": "unit",
          "type": "string",
          "required": false
        },
        {
          "name": "device",
          "type": "device_ref",
          "required": true
        }
      ],
      "origin": "generated",
      "source": "blocks.py"
    },
    {
      "type": "SetpointBlock",
      "family": "source",
      "doc": "Holds a controllable value updated via SetSignal; emits it each cycle.",
      "inputs": [],
      "outputs": [
        {
          "name": "out",
          "type": "float"
        }
      ],
      "params": [
        {
          "name": "signal_name",
          "type": "string",
          "required": true
        },
        {
          "name": "unit",
          "type": "string",
          "required": false
        },
        {
          "name": "initial_value",
          "type": "float",
          "required": false
        }
      ],
      "origin": "generated",
      "source": "blocks.py"
    },
    {
      "type": "SubscriberSourceBlock",
      "family": "source",
      "doc": "Consumes a signal owned by another ``signal_graph`` service.",
      "inputs": [],
      "outputs": [
        {
          "name": "out",
          "type": "float"
        }
      ],
      "params": [
        {
          "name": "signal_name",
          "type": "signal_ref",
          "required": true
        },
        {
          "name": "unit",
          "type": "string",
          "required": false
        }
      ],
      "origin": "generated",
      "source": "blocks.py"
    },
    {
      "type": "LinearScaleBlock",
      "family": "function",
      "doc": "``out = gain * in + offset`` (linear calibration / unit conversion).",
      "inputs": [
        {
          "name": "in",
          "type": "float"
        }
      ],
      "outputs": [
        {
          "name": "out",
          "type": "float"
        }
      ],
      "params": [
        {
          "name": "gain",
          "type": "float",
          "required": false
        },
        {
          "name": "offset",
          "type": "float",
          "required": false
        },
        {
          "name": "out_unit",
          "type": "string",
          "required": false
        },
        {
          "name": "in_unit",
          "type": "string",
          "required": false
        }
      ],
      "origin": "generated",
      "source": "blocks.py"
    },
    {
      "type": "ClampBlock",
      "family": "function",
      "doc": "Clamps its input to ``[min_value, max_value]``.",
      "inputs": [
        {
          "name": "in",
          "type": "float"
        }
      ],
      "outputs": [
        {
          "name": "out",
          "type": "float"
        }
      ],
      "params": [
        {
          "name": "min_value",
          "type": "float",
          "required": true
        },
        {
          "name": "max_value",
          "type": "float",
          "required": true
        }
      ],
      "origin": "generated",
      "source": "blocks.py"
    },
    {
      "type": "DecimatorBlock",
      "family": "function",
      "doc": "Passes every ``n``-th sample; emits ``None`` otherwise (rate reduction).",
      "inputs": [
        {
          "name": "in",
          "type": "float"
        }
      ],
      "outputs": [
        {
          "name": "out",
          "type": "float"
        }
      ],
      "params": [
        {
          "name": "n",
          "type": "int",
          "required": false
        }
      ],
      "origin": "generated",
      "source": "blocks.py"
    },
    {
      "type": "ThresholdBlock",
      "family": "function",
      "doc": "Emits ``1.0`` when ``in`` crosses ``threshold``, else ``0.0``.",
      "inputs": [
        {
          "name": "in",
          "type": "float"
        }
      ],
      "outputs": [
        {
          "name": "out",
          "type": "float"
        }
      ],
      "params": [
        {
          "name": "threshold",
          "type": "float",
          "required": true
        },
        {
          "name": "unit",
          "type": "string",
          "required": false
        }
      ],
      "origin": "generated",
      "source": "blocks.py"
    },
    {
      "type": "RecordSignalBlock",
      "family": "sink",
      "doc": "Batches incoming samples and flushes them to the measurement store.",
      "inputs": [
        {
          "name": "in",
          "type": "float"
        }
      ],
      "outputs": [],
      "params": [
        {
          "name": "signal_name",
          "type": "string",
          "required": true
        },
        {
          "name": "batch_size",
          "type": "int",
          "required": false
        }
      ],
      "origin": "generated",
      "source": "blocks.py"
    },
    {
      "type": "DacBlock",
      "family": "sink",
      "doc": "Writes its input to an analog output channel on a device service.",
      "inputs": [
        {
          "name": "in",
          "type": "float"
        }
      ],
      "outputs": [],
      "params": [
        {
          "name": "channel",
          "type": "int",
          "required": true
        },
        {
          "name": "device",
          "type": "device_ref",
          "required": true
        }
      ],
      "origin": "generated",
      "source": "blocks.py"
    },
    {
      "type": "UdsPeriodicSourceBlock",
      "family": "source",
      "doc": "Extracts one parameter from the tester's decoded 0x2A periodic values as a scaled signal.",
      "inputs": [],
      "outputs": [
        {
          "name": "out",
          "type": "float"
        },
        {
          "name": "last_nrc",
          "type": "float"
        },
        {
          "name": "age_s",
          "type": "float"
        },
        {
          "name": "update_count",
          "type": "float"
        }
      ],
      "params": [
        {
          "name": "tester",
          "type": "device_ref",
          "required": true
        },
        {
          "name": "periodic_id",
          "type": "int",
          "required": true
        },
        {
          "name": "parameter",
          "type": "string",
          "required": true
        },
        {
          "name": "scale",
          "type": "float",
          "required": false
        },
        {
          "name": "offset",
          "type": "float",
          "required": false
        },
        {
          "name": "on_nrc",
          "type": "enum",
          "required": false,
          "choices": [
            "none",
            "hold"
          ]
        },
        {
          "name": "unit",
          "type": "string",
          "required": false
        }
      ],
      "origin": "generated",
      "source": "blocks.py"
    },
    {
      "type": "UdsDidSourceBlock",
      "family": "source",
      "doc": "Extracts one PDX parameter from the responses of a named UDS request (manual/cyclic lane).",
      "inputs": [],
      "outputs": [
        {
          "name": "out",
          "type": "float"
        },
        {
          "name": "last_nrc",
          "type": "float"
        },
        {
          "name": "age_s",
          "type": "float"
        },
        {
          "name": "update_count",
          "type": "float"
        }
      ],
      "params": [
        {
          "name": "request_service",
          "type": "device_ref",
          "required": true
        },
        {
          "name": "service_name",
          "type": "string",
          "required": true
        },
        {
          "name": "parameter",
          "type": "string",
          "required": true
        },
        {
          "name": "scale",
          "type": "float",
          "required": false
        },
        {
          "name": "offset",
          "type": "float",
          "required": false
        },
        {
          "name": "on_nrc",
          "type": "enum",
          "required": false,
          "choices": [
            "none",
            "hold"
          ]
        },
        {
          "name": "unit",
          "type": "string",
          "required": false
        }
      ],
      "origin": "generated",
      "source": "blocks.py"
    },
    {
      "type": "UdsWriteSinkBlock",
      "family": "function",
      "doc": "Embeds a signal into the DUT: writes the scaled input to a memory address through the tester (0x3D).",
      "inputs": [
        {
          "name": "in",
          "type": "float"
        }
      ],
      "outputs": [
        {
          "name": "ack",
          "type": "float"
        },
        {
          "name": "last_nrc",
          "type": "float"
        },
        {
          "name": "age_s",
          "type": "float"
        },
        {
          "name": "write_count",
          "type": "float"
        }
      ],
      "params": [
        {
          "name": "tester",
          "type": "device_ref",
          "required": true
        },
        {
          "name": "address",
          "type": "int",
          "required": true
        },
        {
          "name": "size",
          "type": "int",
          "required": false
        },
        {
          "name": "scale",
          "type": "float",
          "required": false
        },
        {
          "name": "offset",
          "type": "float",
          "required": false
        },
        {
          "name": "trigger",
          "type": "enum",
          "required": false,
          "choices": [
            "on_change",
            "every_tick"
          ]
        },
        {
          "name": "min_interval_s",
          "type": "float",
          "required": false
        }
      ],
      "origin": "generated",
      "source": "blocks.py"
    }
  ]
};

// Colour convention shared with the design docs / zero-to-hero deck:
// teal source, violet function, green sink.
const FAMILY_STYLE = {
  source: { fill: "#0e7490", stroke: "#67e8f9" },
  function: { fill: "#5b21b6", stroke: "#c4b5fd" },
  sink: { fill: "#166534", stroke: "#86efac" },
  unknown: { fill: "#334155", stroke: "#94a3b8" },
};

const TYPE_COLOR = {
  float: "#38bdf8",
  int: "#67e8f9",
  bool: "#f59e0b",
  string: "#f472b6",
  bytes: "#10b981",
};

function typeColor(t) {
  return TYPE_COLOR[t] || "#94a3b8";
}

// Minimal shape check for an externally supplied catalog; returns a list of
// problems (empty = usable). Lenient by design: unknown extra fields are fine.
function checkCatalog(cat) {
  const problems = [];
  if (!cat || typeof cat !== "object" || !Array.isArray(cat.blocks)) {
    return ["catalog must be an object with a 'blocks' array"];
  }
  const seen = new Set();
  cat.blocks.forEach((b, i) => {
    if (!b.type) problems.push(`blocks[${i}]: missing 'type'`);
    else if (seen.has(b.type)) problems.push(`blocks[${i}]: duplicate type '${b.type}'`);
    else seen.add(b.type);
    if (!["source", "function", "sink"].includes(b.family)) {
      problems.push(`blocks[${i}] (${b.type || "?"}): family must be source|function|sink`);
    }
    for (const key of ["inputs", "outputs", "params"]) {
      if (b[key] !== undefined && !Array.isArray(b[key])) {
        problems.push(`blocks[${i}] (${b.type || "?"}): '${key}' must be an array`);
      }
    }
    const params = Array.isArray(b.params) ? b.params : [];
    for (const p of params) {
      if (p.type === "enum" && !(Array.isArray(p.choices) && p.choices.length)) {
        problems.push(`blocks[${i}] (${b.type || "?"}): enum param '${p.name}' needs a non-empty 'choices' list`);
      }
      if (p.allowed_from !== undefined) {
        const src = params.find((q) => q.name === p.allowed_from?.param);
        if (!src) {
          problems.push(`blocks[${i}] (${b.type || "?"}): param '${p.name}' allowed_from references unknown param '${p.allowed_from?.param}'`);
        } else if (src.type !== "list") {
          problems.push(`blocks[${i}] (${b.type || "?"}): param '${p.name}' allowed_from '${src.name}' must be a list param (is ${src.type})`);
        }
      }
    }
  });
  return problems;
}

function catalogByType(cat) {
  const map = new Map();
  for (const b of cat.blocks) map.set(b.type, b);
  return map;
}
