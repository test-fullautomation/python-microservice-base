/**
 * @fileoverview Testbench configuration view (Testbenches tab).
 *
 * Inherits view lifecycle, layout, sidebar and header coordination from ConfigBaseView.
 * Focuses on device editing, schema form generation, and device model picker.
 *
 * @version 2.0.0
 */
(function () {
  'use strict';

  var root = (typeof window !== 'undefined') ? window : (typeof global !== 'undefined' ? global : this);
  var MM = root.MicroserviceManager = root.MicroserviceManager || {};
  var SF = MM.schemaForm || (typeof require !== 'undefined' ? require('./SchemaForm.js') : null);
  var Common = MM.configCommon || (typeof require !== 'undefined' ? require('./ConfigCommon.js') : null);
  var Base = MM.configBaseView || (typeof require !== 'undefined' ? require('./ConfigBaseView.js') : null);

  var h = Common.h;
  var icon = Common.icon;
  var btn = Common.btn;

  function fmtValue(v) {
    if (v !== null && typeof v === 'object') return JSON.stringify(v);
    return String(v);
  }

  function constraintText(f) {
    var parts = [f.type === 'json' ? 'JSON' : f.type];
    if (f.min) parts.push((f.min.exclusive ? '> ' : '≥ ') + f.min.value);
    if (f.max) parts.push((f.max.exclusive ? '< ' : '≤ ') + f.max.value);
    return parts.join(', ');
  }

  var baseView = Base.createBaseView({
    idPrefix: 'tb',
    title: 'Testbenches',
    iconName: 'boxes',
    itemLabel: 'testbench',
    sidePaneId: 'testbenchSidePane',
    fallbackSideId: 'testbenchSidebar',
    contentId: 'testbenchContent',
    searchPlaceholder: 'Search or enter testbench ID…',
    emptyTitle: 'No testbench created yet',
    emptySubtext: 'Use + to create the first one.',
    emptyIcon: 'diagram-3',
    placeholderText: 'Select a testbench, or create one with +',
    hasNameInput: true,
    idPlaceholder: 'id (e.g. tower_1)',
    namePlaceholder: 'name (defaults to ID if not entered)',
    initialUI: {
      picking: false,
      pickFilter: '',
      pickSelected: null
    },

    createStore: function () {
      return MM.testbenchStoreApi.createStore(MM.configHub, { storage: window.localStorage });
    },
    onStoreCreated: function (s) {
      MM.testbenchStore = s;
    },
    onCreate: function (store, id, name) {
      var finalName = (name && String(name).trim()) ? String(name).trim() : id;
      var res = store.createNew(id, finalName);
      if (!res.ok) return res;
      return store.save().then(function (saveRes) {
        if (!saveRes.ok) {
          return { ok: false, message: (store.state.current && store.state.current.saveError && store.state.current.saveError.message) || 'Failed to save new testbench' };
        }
        return { ok: true, version: saveRes.version };
      });
    },
    onBeforeOpen: function (ui) {
      ui.picking = false;
    },
    onActivate: function (store) {
      if (store.state.catalog.status !== 'ok') store.loadCatalog();
    },

    renderCard: function (cur, ctx) {
      return renderDevices(cur, ctx);
    },

    onUpdateLive: function (cur, v, ctx) {
      ctx.mainEl.querySelectorAll('[data-err]').forEach(function (el) {
        var key = el.getAttribute('data-err');
        var msg = '';
        if (key === 'testbench:name') {
          msg = v.testbench && v.testbench.name ? 'Name ' + v.testbench.name : '';
        } else if (key && key.indexOf(':') !== -1) {
          var i = key.indexOf(':');
          var dk = key.slice(0, i), fname = key.slice(i + 1);
          var de = v.devices && v.devices[dk];
          if (de) {
            msg = fname === 'device_id' ? (de.device_id || '') : (de.fields && de.fields[fname] ? fname + ' ' + de.fields[fname] : '');
          }
        }
        el.textContent = msg;
        el.style.display = msg ? '' : 'none';
        var input = el.parentElement && el.parentElement.querySelector('input, select, textarea');
        if (input) input.classList.toggle('is-invalid', !!msg);
      });
    }
  });

  function getStore() {
    return baseView.getStore();
  }

  // ---------------------------------------------------- Devices Card Rendering
  function renderDevices(cur, ctx) {
    var st = getStore();
    var ui = baseView.getUI();

    var headTitle = [
      h('h2', { text: 'Testbench Devices' }),
      h('span', {
        class: 'badge tb-ver', id: 'tbVersionBadge',
        text: cur.isNew ? 'not saved' : 'v' + cur.version
      }),
      h('span', { class: 'tb-status', id: 'tbStatus' })
    ];

    var tools = [];
    if (!cur.readOnly) {
      tools.push(btn('Add device', 'btn-outline-primary', function () {
        ui.picking = !ui.picking; ui.pickSelected = null;
        if (ui.picking && st.state.catalog.status !== 'ok') st.loadCatalog();
        baseView.renderMain();
      }, { id: 'tbAddDevice' }));
      tools.push(btn('Save', 'btn-primary', function () { st.save(); }, { id: 'tbSave' }));
    } else {
      tools.push(btn('Load version', 'btn-primary', function () {
        var targetVer = cur.viewingVersion || cur.version;
        Common.confirmModal({
          title: 'Load Version',
          message: 'Are you sure you want to load version v' + targetVer + ' as the current configuration?',
          confirmText: 'Load Version',
          confirmVariant: 'primary',
          icon: 'box-arrow-in-down'
        }).then(function (ok) {
          if (ok) st.loadVersionForUse(targetVer);
        });
      }, { id: 'tbLoadVersionCard', title: 'Load version to use' }));
      tools.push(btn('Back to latest', 'btn-outline-primary', function () { st.open(cur.id, cur.latestVersion); }, { id: 'tbBackLatest' }));
    }

    var kids = [];
    if (ui.picking && !cur.readOnly) kids.push(renderPicker(st, ui));
    if (!cur.devices.length) {
      kids.push(h('div', { class: 'tb-empty', id: 'tbNoDevices', text: 'No devices yet.' }));
    }
    cur.devices.forEach(function (d) { kids.push(renderDevice(cur, d, st)); });
    return ctx.section(headTitle, 'cpu', kids, 'tbDevices', tools);
  }

  function renderPicker(st, ui) {
    var cat = st.state.catalog;
    var box = h('div', { class: 'tb-picker', id: 'tbPicker' });
    if (cat.status === 'loading') {
      box.appendChild(h('div', { class: 'tb-muted', text: 'Loading catalog…' }));
    } else if (cat.status === 'error') {
      box.appendChild(h('div', { class: 'tb-error', id: 'tbCatalogError', text: 'Catalog: ' + cat.error }));
      box.appendChild(btn('Retry', 'btn-outline-danger', function () { st.loadCatalog(); }, { id: 'tbCatalogRetry' }));
    } else {
      box.appendChild(h('input', {
        class: 'form-control form-control-sm', id: 'tbPickFilter', placeholder: 'Filter models…', value: ui.pickFilter,
        oninput: function (e) { ui.pickFilter = e.target.value; renderPickerList(box, st, ui); }
      }));
      box.appendChild(h('div', { class: 'tb-picker-list', id: 'tbPickerList' }));
      renderPickerList(box, st, ui);
    }
    return box;
  }

  function renderPickerList(box, st, ui) {
    var list = box.querySelector('#tbPickerList');
    if (!list) return;
    list.textContent = '';
    var q = ui.pickFilter.toLowerCase();
    var models = st.state.catalog.models.filter(function (m) {
      return !q || (m.catalog_id + ' ' + m.manufacturer + ' ' + m.model + ' ' + m.description).toLowerCase().indexOf(q) !== -1;
    });
    if (!models.length) list.appendChild(h('div', { class: 'tb-muted', text: 'No matching device models.' }));
    models.forEach(function (m) {
      list.appendChild(h('button', {
        type: 'button', class: 'tb-model', 'data-catalog-id': m.catalog_id,
        onclick: function () {
          ui.picking = false;
          st.addDevice(m.catalog_id);
        }
      }, [
        h('span', { class: 'tb-model-title', text: m.manufacturer + ' ' + m.model }),
        h('span', { class: 'tb-model-id', text: m.catalog_id }),
        h('span', { class: 'tb-model-desc', text: m.description || '' })
      ]));
    });
  }

  function renderDevice(cur, d, st) {
    var card = h('div', { class: 'tb-device' + (d.open ? ' open' : '') + (d.editing ? ' editing' : ''), 'data-key': d.key, 'data-device-id': d.device_id });
    var locked = st.isDeviceLocked(d.key);
    var m = d.model;
    var title = m ? (m.manufacturer + ' ' + m.model) : d.catalog_ref;
    var idIn = h('input', {
      class: 'form-control form-control-sm tb-devid', 'data-field': 'device_id', 'aria-label': 'Device id',
      value: d.device_id, disabled: locked,
      oninput: function (e) { baseView.live(function () { st.setDeviceId(d.key, e.target.value); }); }
    });
    card.appendChild(h('div', { class: 'tb-device-head' }, [
      h('button', {
        type: 'button', class: 'tb-toggle', 'aria-label': d.open ? 'Collapse' : 'Expand',
        onclick: function () { if (d.open) st.closeDevice(d.key); else st.openDevice(d.key); }
      }, [icon(d.open ? 'chevron-down' : 'chevron-right')]),
      h('div', { class: 'tb-device-id' }, [idIn, h('div', { class: 'tb-fielderr', 'data-err': d.key + ':device_id' })]),
      h('div', { class: 'tb-device-sub' }, [
        d.isNew ? h('span', { class: 'tb-chip tb-chip-new', text: 'new' }) : null,
        d.editing ? h('span', { class: 'tb-chip tb-chip-editing', 'data-status': 'editing', title: 'This device is being edited', text: 'editing' }) : null,
        d.schemaStatus === 'missing' ? h('span', { class: 'tb-chip tb-chip-warn', title: d.schemaError, text: 'not in catalog' }) : null,
        d.schemaStatus === 'error' ? h('span', { class: 'tb-chip tb-chip-err', title: d.schemaError, text: 'catalog error' }) : null,
        (!d.open && title) ? h('span', { class: 'tb-device-summary', text: title + (d.model && d.model.description ? ' — ' + d.model.description : '') }) : null
      ]),
      (cur.readOnly || d.isNew) ? null : (d.editing
        ? h('button', {
          type: 'button', class: 'btn btn-sm tb-icon-btn tb-cancel-edit', title: 'Cancel editing (discard changes to this device)',
          'aria-label': 'Cancel editing', onclick: function () { st.cancelEdit(d.key); }
        }, [icon('x-lg')])
        : h('button', {
          type: 'button', class: 'btn btn-sm tb-icon-btn tb-edit', title: 'Edit device',
          'aria-label': 'Edit device', 'data-edit': d.key, onclick: function () { st.startEdit(d.key); }
        }, [icon('pencil')])),
      locked ? null : h('button', {
        type: 'button', class: 'btn btn-sm tb-icon-btn tb-remove', title: 'Remove device',
        'aria-label': 'Remove device', onclick: function () { st.removeDevice(d.key); }
      }, [icon('trash')])
    ]));

    if (!d.open) return card;
    var body = h('div', { class: 'tb-device-body' });
    if (m && m.description) body.appendChild(h('div', { class: 'tb-muted tb-desc', text: m.description }));

    // Identity: shown once here instead of repeating it in the header.
    var info = h('dl', { class: 'tb-meta', 'data-meta': d.key }, [
      title && title !== d.catalog_ref ? h('dt', { text: 'Model' }) : null,
      title && title !== d.catalog_ref ? h('dd', {}, [h('code', { text: title })]) : null,
      h('dt', { text: 'Catalog' }), h('dd', {}, [h('code', { text: d.catalog_ref || '—' })]),
      h('dt', { text: 'Adapter' }), h('dd', {}, [h('code', { text: d.adapter || '—' })])
    ]);
    if (d.capabilities && d.capabilities.length) {
      info.appendChild(h('dt', { text: 'Capabilities' }));
      info.appendChild(h('dd', { class: 'tb-caps' }, d.capabilities.map(function (c) {
        return h('span', { class: 'tb-chip tb-chip-cap', text: String(c) });
      })));
    }
    body.appendChild(info);

    var keys = Object.keys(d.static_config || {});
    if (keys.length) {
      body.appendChild(h('h3', { class: 'tb-sub' }, [
        'Static configuration ', h('span', { class: 'tb-sub-note', text: 'read-only · ' + keys.length })
      ]));
      var dl = h('dl', { class: 'tb-static', 'data-static': d.key });
      keys.forEach(function (k) { dl.appendChild(h('dt', { text: k })); dl.appendChild(h('dd', { text: fmtValue(d.static_config[k]) })); });
      body.appendChild(dl);
    }

    var nFields = d.schema ? SF.fields(d.schema).length : 0;
    body.appendChild(h('h3', { class: 'tb-sub' }, [
      'Settings', nFields ? h('span', { class: 'tb-sub-note', text: ' ' + nFields }) : null
    ]));
    if (d.schemaStatus === 'loading') {
      body.appendChild(h('div', { class: 'tb-muted', text: 'Loading catalog entry…' }));
    } else if (d.schemaStatus === 'error' || d.schemaStatus === 'missing') {
      body.appendChild(h('div', { class: 'tb-error', 'data-schema-error': d.key, text: d.schemaError }));
      if (d.schemaStatus === 'error') body.appendChild(btn('Retry', 'btn-outline-danger', function () { st.openDevice(d.key); }));
      body.appendChild(renderSavedConfig(d));
    } else {
      var fs = SF.fields(d.schema);
      if (!fs.length) body.appendChild(h('div', { class: 'tb-muted', text: 'This device has no user settings.' }));
      fs.forEach(function (f) { body.appendChild(renderField(cur, d, f, st, locked)); });
    }
    card.appendChild(body);
    return card;
  }

  function renderSavedConfig(d) {
    var keys = Object.keys(d.savedUserConfig || {});
    var dl = h('dl', { class: 'tb-static', 'data-saved-config': d.key });
    if (!keys.length) return h('div', { class: 'tb-muted', text: 'No saved settings.' });
    keys.forEach(function (k) { dl.appendChild(h('dt', { text: k })); dl.appendChild(h('dd', { text: fmtValue(d.savedUserConfig[k]) })); });
    return dl;
  }

  function renderField(cur, d, f, st, locked) {
    var id = 'tbf-' + d.key + '-' + f.name;
    var raw = d.raw[f.name];
    var input;
    var set = function (v) { baseView.live(function () { st.setField(d.key, f.name, v); }); };
    if (f.enum) {
      input = h('select', {
        class: 'form-select form-select-sm', id: id, 'data-field': f.name, disabled: locked,
        onchange: function (e) { var i = e.target.selectedIndex; set(i === 0 ? '' : f.enum[i - 1]); }
      });
      input.appendChild(h('option', { value: '', text: '—' }));
      f.enum.forEach(function (e) {
        input.appendChild(h('option', { value: String(e), text: String(e), selected: raw !== '' && raw !== undefined && String(raw) === String(e) }));
      });
    } else if (f.type === 'boolean') {
      input = h('input', {
        type: 'checkbox', class: 'form-check-input', id: id, 'data-field': f.name, checked: raw === true, disabled: locked,
        onchange: function (e) { set(e.target.checked); }
      });
    } else if (f.type === 'json') {
      input = h('textarea', {
        class: 'form-control form-control-sm tb-json', id: id, 'data-field': f.name, rows: 3, disabled: locked,
        oninput: function (e) { set(e.target.value); }
      });
      input.value = raw === undefined ? '' : raw;
    } else {
      input = h('input', {
        type: 'text', class: 'form-control form-control-sm', id: id, 'data-field': f.name, value: raw === undefined ? '' : raw,
        inputmode: f.type === 'string' ? 'text' : 'decimal', disabled: locked,
        oninput: function (e) { set(e.target.value); }
      });
    }
    var label = h('label', { class: 'form-label', for: id }, [
      f.label, f.required ? h('span', { class: 'tb-req', title: 'Required', text: ' *' }) : null,
      h('span', { class: 'tb-constraint', text: ' ' + constraintText(f) })
    ]);
    return h('div', { class: 'tb-field' + (f.type === 'boolean' ? ' tb-field-bool' : ''), 'data-field-row': f.name }, [
      label, input,
      f.description ? h('div', { class: 'form-text', text: f.description }) : null,
      h('div', { class: 'tb-fielderr', 'data-err': d.key + ':' + f.name })
    ]);
  }

  MM.testbench = baseView;
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = baseView;
  }
})();
