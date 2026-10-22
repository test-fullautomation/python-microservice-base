/**
 * @fileoverview Testbench & Infrastructure shared coordinator.
 *
 * Coordinates the shared sidebar (#testbenchSidebar) containing sub-tabs for
 * Testbenches and Infrastructure, as well as the active content area.
 *
 * @version 1.0.0
 */
(function () {
  'use strict';

  var MM = window.MicroserviceManager = window.MicroserviceManager || {};

  var activeTab = 'tb'; // 'tb' | 'infra'
  var initialized = false;

  function ensureSidebarDOM() {
    var sideEl = document.getElementById('testbenchSidebar');
    if (!sideEl) return;

    if (!document.getElementById('tbSideSwitch')) {
      var switchEl = document.createElement('div');
      switchEl.className = 'tb-side-switch';
      switchEl.id = 'tbSideSwitch';

      var btnTb = document.createElement('button');
      btnTb.type = 'button';
      btnTb.className = 'tb-side-tab active';
      btnTb.id = 'tbSideTabTb';
      btnTb.innerHTML = '<i class="bi bi-boxes"></i><span>Testbenches</span>';

      var btnInfra = document.createElement('button');
      btnInfra.type = 'button';
      btnInfra.className = 'tb-side-tab';
      btnInfra.id = 'tbSideTabInfra';
      btnInfra.innerHTML = '<i class="bi bi-hdd-network"></i><span>Infrastructure</span>';

      switchEl.appendChild(btnTb);
      switchEl.appendChild(btnInfra);

      var paneTb = document.createElement('div');
      paneTb.id = 'testbenchSidePane';
      paneTb.className = 'tb-side-pane';

      var paneInfra = document.createElement('div');
      paneInfra.id = 'infraSidePane';
      paneInfra.className = 'tb-side-pane';
      paneInfra.style.display = 'none';

      sideEl.textContent = '';
      sideEl.appendChild(switchEl);
      sideEl.appendChild(paneTb);
      sideEl.appendChild(paneInfra);
    }
  }

  function init() {
    ensureSidebarDOM();

    var tabTb = document.getElementById('tbSideTabTb');
    var tabInfra = document.getElementById('tbSideTabInfra');

    if (tabTb && !tabTb.__wired) {
      tabTb.__wired = true;
      tabTb.addEventListener('click', function () { switchSubTab('tb'); });
    }
    if (tabInfra && !tabInfra.__wired) {
      tabInfra.__wired = true;
      tabInfra.addEventListener('click', function () { switchSubTab('infra'); });
    }
    initialized = true;
  }

  function switchSubTab(tab, openId) {
    init();
    if (tab === activeTab && !openId) return;

    function proceed() {
      activeTab = tab;
      syncView(openId);
    }

    if (activeTab === 'tb' && MM.testbench && MM.testbench.isDirty && MM.testbench.isDirty()) {
      if (MM.ConfigCommon && MM.ConfigCommon.confirmModal) {
        MM.ConfigCommon.confirmModal({
          title: 'Discard Changes',
          message: 'You have unsaved changes in this testbench. Do you want to discard them?',
          confirmText: 'Discard Changes',
          confirmVariant: 'warning',
          icon: 'exclamation-triangle'
        }).then(function (discard) {
          if (discard) proceed();
        });
        return;
      }
      if (!window.confirm('You have unsaved changes in this testbench. Discard them?')) return;
    } else if (activeTab === 'infra' && MM.infra && MM.infra.isDirty && MM.infra.isDirty()) {
      if (MM.ConfigCommon && MM.ConfigCommon.confirmModal) {
        MM.ConfigCommon.confirmModal({
          title: 'Discard Changes',
          message: 'You have unsaved changes in this infrastructure configuration. Do you want to discard them?',
          confirmText: 'Discard Changes',
          confirmVariant: 'warning',
          icon: 'exclamation-triangle'
        }).then(function (discard) {
          if (discard) proceed();
        });
        return;
      }
      if (!window.confirm('You have unsaved changes in this infrastructure configuration. Discard them?')) return;
    }

    proceed();
  }

  function syncView(openId) {
    var tabTb = document.getElementById('tbSideTabTb');
    var tabInfra = document.getElementById('tbSideTabInfra');
    var paneTb = document.getElementById('testbenchSidePane');
    var paneInfra = document.getElementById('infraSidePane');
    var contentTb = document.getElementById('testbenchContent');
    var contentInfra = document.getElementById('infraContent');

    if (tabTb) tabTb.classList.toggle('active', activeTab === 'tb');
    if (tabInfra) tabInfra.classList.toggle('active', activeTab === 'infra');

    if (paneTb) paneTb.style.display = activeTab === 'tb' ? 'flex' : 'none';
    if (paneInfra) paneInfra.style.display = activeTab === 'infra' ? 'flex' : 'none';

    if (contentTb) contentTb.style.display = activeTab === 'tb' ? '' : 'none';
    if (contentInfra) contentInfra.style.display = activeTab === 'infra' ? '' : 'none';

    if (activeTab === 'tb') {
      if (MM.testbench) MM.testbench.activate();
      if (openId && MM.testbenchStore) MM.testbenchStore.open(openId);
    } else {
      if (MM.infra) MM.infra.activate();
      if (openId && MM.infraStore) MM.infraStore.open(openId);
    }
    updateCounts();
  }

  function updateCounts() {
    var countTb = document.getElementById('tbSideCountTb');
    var countInfra = document.getElementById('tbSideCountInfra');
    if (countTb && MM.testbenchStore && MM.testbenchStore.state) {
      countTb.textContent = String(MM.testbenchStore.state.list.items.length);
    }
    if (countInfra && MM.infraStore && MM.infraStore.state) {
      countInfra.textContent = String(MM.infraStore.state.list.items.length);
    }
  }

  MM.testbenchConfig = {
    activate: function () {
      init();
      if (MM.testbench) MM.testbench.activate();
      if (MM.infra) MM.infra.activate();
      syncView();
    },
    switchSubTab: switchSubTab,
    updateCounts: updateCounts,
    getActiveSubTab: function () { return activeTab; }
  };
})();
