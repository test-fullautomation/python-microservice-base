/**
 * @fileoverview Infrastructure configuration view (Infrastructure tab).
 *
 * Inherits view lifecycle, layout, sidebar and header coordination from ConfigBaseView.
 * Focuses on node placement and datacenter selection for testbenches.
 *
 * @version 2.0.0
 */
(function () {
  'use strict';

  var root = (typeof window !== 'undefined') ? window : (typeof global !== 'undefined' ? global : this);
  var MM = root.MicroserviceManager = root.MicroserviceManager || {};
  var Common = MM.configCommon || (typeof require !== 'undefined' ? require('./ConfigCommon.js') : null);
  var Base = MM.configBaseView || (typeof require !== 'undefined' ? require('./ConfigBaseView.js') : null);

  var h = Common.h;
  var icon = Common.icon;
  var btn = Common.btn;

  var baseView = Base.createBaseView({
    idPrefix: 'infra',
    title: 'Infrastructure',
    iconName: 'hdd-network',
    itemLabel: 'infrastructure configuration',
    sidePaneId: 'infraSidePane',
    fallbackSideId: 'infraSidebar',
    contentId: 'infraContent',
    searchPlaceholder: 'Search or enter testbench ID to configure…',
    emptyTitle: 'No infrastructure configuration yet',
    emptySubtext: 'Use + or search/enter a testbench ID to configure.',
    emptyIcon: 'hdd-network',
    placeholderText: 'Select an infrastructure configuration or search/enter a testbench ID to configure.',
    hasNameInput: false,
    idPlaceholder: 'testbench id (e.g. tower_1)',

    createStore: function () {
      return MM.infraStoreApi.createStore(MM.configHub, { storage: window.localStorage });
    },
    onStoreCreated: function (s) {
      MM.infraStore = s;
    },
    onCreate: function (store, id) {
      var targetId = String(id || '').trim();
      if (!targetId) return { ok: false, message: 'Testbench ID is required' };
      if (store.state.list.items.some(function (i) { return i.id === targetId && !i.isNew; })) {
        return { ok: false, message: 'An infrastructure configuration with ID "' + targetId + '" already exists' };
      }
      return store.open(targetId).then(function (cur) {
        if (!cur) return { ok: false, message: 'Failed to open infrastructure' };
        if (!cur.isDefault && cur.version > 0) {
          return { ok: true };
        }
        return store.save().then(function (saveRes) {
          if (!saveRes.ok) {
            return { ok: false, message: (store.state.current && store.state.current.saveError && store.state.current.saveError.message) || 'Failed to save infrastructure' };
          }
          return { ok: true, version: saveRes.version };
        });
      });
    },

    renderCard: function (cur, ctx) {
      return renderPlacementCard(cur, ctx);
    },

    onUpdateLive: function (cur, v, ctx) {
      ctx.mainEl.querySelectorAll('[data-err]').forEach(function (el) {
        var key = el.getAttribute('data-err');
        var msg = (v.errors && v.errors[key]) || '';
        el.textContent = msg;
        el.style.display = msg ? '' : 'none';
        var input = el.parentElement && el.parentElement.querySelector('input');
        if (input) input.classList.toggle('is-invalid', !!msg);
      });
    }
  });

  function getStore() {
    return baseView.getStore();
  }

  // ---------------------------------------------------- Placement Card Rendering
  function renderPlacementCard(cur, ctx) {
    var st = getStore();

    var node = h('input', {
      type: 'text', class: 'form-control form-control-sm', id: 'infraNode', value: cur.node, disabled: cur.readOnly,
      oninput: function (e) { baseView.live(function () { st.setNode(e.target.value); }); }
    });
    var dcs = h('input', {
      type: 'text', class: 'form-control form-control-sm', id: 'infraDatacenters', value: cur.datacenters, disabled: cur.readOnly,
      oninput: function (e) { baseView.live(function () { st.setDatacenters(e.target.value); }); }
    });

    var headTitle = [
      h('h2', { text: 'Node Placement & Datacenters' }),
      h('span', {
        class: 'badge ' + (cur.isDefault ? 'tb-badge-default' : 'tb-ver'), id: 'infraVersionBadge',
        text: cur.isDefault ? 'defaults — not saved (v0)' : 'v' + cur.version
      }),
      h('span', { class: 'tb-status', id: 'infraStatus' })
    ];

    var tools = [];
    if (!cur.readOnly) {
      tools.push(btn(cur.isDefault ? 'Save infrastructure (creates v1)' : 'Save new version', 'btn-primary', function () { st.save(); }, { id: 'infraSave' }));
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
      }, { id: 'infraLoadVersionCard', title: 'Load version to use' }));
      tools.push(btn('Back to latest', 'btn-outline-primary', function () { st.open(cur.id, cur.latestVersion); }, { id: 'infraBackLatest' }));
    }

    var kids = [
      cur.isDefault ? h('div', { class: 'alert alert-info tb-banner', style: 'margin-bottom:1rem;' }, [
        icon('info-circle'),
        h('span', { text: ' These values are provider defaults (v0) and have not been saved yet. You can accept or modify them and click Save.' })
      ]) : null,
      h('div', { class: 'tb-infra-grid' }, [
        h('div', { class: 'tb-field' }, [
          h('label', { class: 'form-label', for: 'infraNode', text: 'Nomad Client Node' }),
          node,
          h('div', { class: 'form-text', text: 'Nomad client node that runs this testbench\'s devices (matches ${node.unique.name}, e.g. client1).' }),
          h('div', { class: 'tb-fielderr', 'data-err': 'node' })
        ]),
        h('div', { class: 'tb-field' }, [
          h('label', { class: 'form-label', for: 'infraDatacenters', text: 'Datacenters' }),
          dcs,
          h('div', { class: 'form-text', text: 'Comma-separated list of Nomad datacenters (e.g. dc1, dc2).' }),
          h('div', { class: 'tb-fielderr', 'data-err': 'datacenters' })
        ])
      ])
    ];

    if (cur.saveError) {
      kids.push(h('div', { class: 'alert alert-danger tb-banner', id: 'infraSaveError', style: 'margin-top:1rem;' }, [
        icon('exclamation-triangle'),
        h('span', { text: ' Save failed: ' + cur.saveError.message })
      ]));
    }

    return ctx.section(headTitle, 'hdd-network', kids, 'infraPlacementCard', tools);
  }

  MM.infra = baseView;
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = baseView;
  }
})();
