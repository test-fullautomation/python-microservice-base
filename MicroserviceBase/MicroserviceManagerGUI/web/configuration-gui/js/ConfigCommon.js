/**
 * @fileoverview Shared utilities and helpers for Testbench and Infrastructure
 * configuration stores and views.
 *
 * Provides:
 * - Data helpers: clone, canon, splitList
 * - Store lifecycle: createEmitter, createFailureHandler, setNotice, isDirty, canSave, saveErrorOf, deleteItem, loadVersions
 * - DOM helpers: h, icon, btn, confirmLeave, renderBannerFailure, renderBannerNotice, renderSidebarItem (browser only)
 *
 * Runs in browser (MM.configCommon) and Node (module.exports).
 *
 * @version 1.0.0
 */
(function (root, factory) {
  'use strict';
  var common = factory();
  if (typeof module === 'object' && module.exports) {
    module.exports = common;
  } else {
    var MM = root.MicroserviceManager = root.MicroserviceManager || {};
    MM.configCommon = common;
  }
})(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';

  // ------------------------------------------------------------ data helpers

  function clone(v) {
    return v === undefined ? undefined : JSON.parse(JSON.stringify(v));
  }

  /**
   * Deterministic JSON string with recursively sorted keys.
   * Used for comparing configuration payloads against baseline to detect dirty state.
   */
  function canon(v) {
    if (Array.isArray(v)) return '[' + v.map(canon).join(',') + ']';
    if (v && typeof v === 'object') {
      return '{' + Object.keys(v).sort().map(function (k) {
        return JSON.stringify(k) + ':' + canon(v[k]);
      }).join(',') + '}';
    }
    return JSON.stringify(v === undefined ? null : v);
  }

  /** Split comma-separated string into an array of non-empty trimmed tokens. */
  function splitList(text) {
    return String(text || '').split(',').map(function (s) { return s.trim(); })
      .filter(function (s) { return s; });
  }

  // ----------------------------------------------------------- store helpers

  /** Creates a pub/sub listener manager. */
  function createEmitter() {
    var listeners = [];
    return {
      subscribe: function (fn) {
        listeners.push(fn);
        return function () {
          listeners = listeners.filter(function (f) { return f !== fn; });
        };
      },
      emit: function (state) {
        listeners.forEach(function (fn) {
          try { fn(state); } catch (e) { /* view bug must not break store */ }
        });
      }
    };
  }

  /**
   * Manages service failure state and retry function for a store.
   */
  function createFailureHandler(state, emit) {
    var retryFn = null;
    return {
      fail: function (err, retry) {
        state.failure = {
          service: (err && err.service) || 'hub',
          code: (err && err.code) || 'UNKNOWN',
          message: (err && err.message) || String(err),
          canRetry: !!retry
        };
        retryFn = retry || null;
      },
      clear: function (service) {
        if (!service || (state.failure && state.failure.service === service)) {
          state.failure = null;
          retryFn = null;
        }
      },
      retry: function () {
        var fn = retryFn;
        state.failure = null;
        retryFn = null;
        emit();
        return fn ? fn() : Promise.resolve();
      },
      getRetryFn: function () {
        return retryFn;
      }
    };
  }

  /** Sets or clears state.notice */
  function setNotice(state, kind, text) {
    state.notice = text ? { kind: kind, text: text } : null;
  }

  /** Returns true if current configuration has unsaved changes compared to baseline. */
  function isDirty(cur, getPayload) {
    if (!cur || cur.readOnly) return false;
    if (cur.isNew) return true;
    return canon(getPayload(cur)) !== cur.baseline;
  }

  /** Returns true if the configuration can currently be saved. */
  function canSave(cur, isValid, dirty) {
    return !!cur && !cur.readOnly && !cur.saving && !!isValid && !!dirty;
  }

  /** Standardizes a hub save error into a clean display object. */
  function saveErrorOf(err) {
    return {
      code: (err && err.code) || 'UNKNOWN',
      service: (err && err.service) || 'hub',
      message: (err && err.message) || String(err),
      reason: (err && err.reason) || ''
    };
  }

  /**
   * Shared delete configuration workflow.
   * Handles local unsaved removal vs backend RPC call, cleanup from items list,
   * clearing state.current if active, notices, and error handling with retry.
   */
  function deleteItem(opts) {
    var api = opts.api;
    var type = opts.type;
    var id = String(opts.id || '').trim();
    var state = opts.state;
    var emit = opts.emit;
    var fail = opts.fail;
    var notice = opts.notice;
    var label = opts.label || type;
    var onLocalDelete = opts.onLocalDelete;

    if (!id) return Promise.resolve({ ok: false });

    var it = state.list.items.find(function (x) { return x.id === id; });
    var isUnsaved = it && (it.isNew || it.isDefault || it.latestVersion === 'new' || it.latestVersion === '0 (default)');

    var doLocalDelete = function () {
      state.list.items = state.list.items.filter(function (x) { return x.id !== id; });
      if (state.current && state.current.id === id) {
        state.current = null;
      }
      if (typeof onLocalDelete === 'function') {
        try { onLocalDelete(id); } catch (e) {}
      }
      notice('info', label + ' "' + id + '" deleted.');
      emit();
      return { ok: true, id: id };
    };

    if (isUnsaved) {
      return Promise.resolve(doLocalDelete());
    }

    return api.deleteConfiguration(type, id).then(function () {
      return doLocalDelete();
    }).catch(function (err) {
      if (err.code === 'NOT_FOUND') {
        return doLocalDelete();
      }
      fail(err, function () { return deleteItem(opts); });
      notice('danger', 'Could not delete ' + label.toLowerCase() + ': ' + err.message);
      emit();
      return { ok: false, error: err };
    });
  }

  /**
   * Shared load versions workflow.
   * Calls api.listConfigurationVersions, sorts descending, updates cur.versions.
   */
  function loadVersions(opts) {
    var api = opts.api;
    var type = opts.type;
    var cur = opts.cur;
    var emit = opts.emit;

    if (!cur || cur.isNew || cur.isDefault) return Promise.resolve([]);

    return api.listConfigurationVersions(type, cur.id).then(function (vs) {
      cur.versions = (vs || []).slice().sort(function (a, b) { return b - a; });
      cur.versionsError = null;
      if (cur.versions.length && !cur.latestVersion) {
        cur.latestVersion = cur.versions[0];
      }
      emit();
      return cur.versions;
    }).catch(function (err) {
      cur.versionsError = err.message;
      emit();
      return [];
    });
  }

  // ------------------------------------------------------------- DOM helpers

  function h(tag, attrs, kids) {
    if (typeof document === 'undefined') return null;
    var el = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      var v = attrs[k];
      if (v === undefined || v === null || v === false) return;
      if (k === 'class') el.className = v;
      else if (k === 'text') el.textContent = v;
      else if (k.indexOf('on') === 0) el.addEventListener(k.slice(2), v);
      else if (k === 'value') el.value = v;
      else if (k === 'checked' || k === 'disabled' || k === 'selected') el[k] = !!v;
      else el.setAttribute(k, v === true ? '' : v);
    });
    (kids || []).forEach(function (c) {
      if (c === null || c === undefined || c === false) return;
      el.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
    });
    return el;
  }

  function icon(name) {
    return h('i', { class: 'bi bi-' + name });
  }

  function btn(label, cls, onclick, extra) {
    var attrs = Object.assign({ type: 'button', class: 'btn btn-sm ' + cls, onclick: onclick }, extra || {});
    return h('button', attrs, [label]);
  }

  function confirmLeave(isChanged, entityLabel) {
    if (!isChanged) return true;
    if (typeof window === 'undefined' || !window.confirm) return true;
    return window.confirm('You have unsaved changes in this ' + (entityLabel || 'configuration') + '. Discard them?');
  }

  /**
   * Modern modal confirmation dialog (replaces browser native window.confirm).
   * Returns a Promise<boolean> (resolves true if confirmed, false if cancelled).
   */
  function confirmModal(opts) {
    if (typeof document === 'undefined' || !document.body) {
      return Promise.resolve(true);
    }
    return new Promise(function (resolve) {
      opts = opts || {};
      var titleText = opts.title || 'Confirm Action';
      var messageText = opts.message || 'Are you sure you want to proceed?';
      var confirmText = opts.confirmText || 'Confirm';
      var cancelText = opts.cancelText || 'Cancel';
      var variant = opts.confirmVariant || 'danger';
      var iconName = opts.icon || (variant === 'danger' ? 'trash3' : (variant === 'warning' ? 'exclamation-triangle' : 'check2'));
      var items = Array.isArray(opts.items) ? opts.items : [];

      var oldModal = document.getElementById('tbConfirmModalBackdrop');
      if (oldModal && oldModal.parentNode) {
        oldModal.parentNode.removeChild(oldModal);
      }

      var backdrop = h('div', {
        class: 'tb-modal-backdrop',
        id: 'tbConfirmModalBackdrop',
        role: 'dialog',
        'aria-modal': 'true',
        'aria-labelledby': 'tbConfirmModalTitle'
      });

      var card = h('div', { class: 'tb-modal-card' });

      var iconBox = h('div', { class: 'tb-modal-icon-box tb-modal-icon-' + variant }, [
        icon(iconName)
      ]);

      var closeBtn = h('button', {
        type: 'button',
        class: 'tb-modal-close-btn',
        'aria-label': 'Close dialog'
      }, [
        icon('x-lg')
      ]);

      var header = h('div', { class: 'tb-modal-header' }, [
        iconBox,
        closeBtn
      ]);

      var body = h('div', { class: 'tb-modal-body' }, [
        h('h3', { class: 'tb-modal-title', id: 'tbConfirmModalTitle', text: titleText }),
        h('p', { class: 'tb-modal-message', text: messageText })
      ]);

      if (items.length > 0) {
        var itemsWrap = h('div', { class: 'tb-modal-items-wrap' }, [
          h('div', { class: 'tb-modal-items-label', text: 'Selected items (' + items.length + '):' })
        ]);
        var itemsList = h('div', { class: 'tb-modal-items' });
        items.forEach(function (name) {
          itemsList.appendChild(h('span', { class: 'tb-modal-item-badge', title: name }, [
            icon('tag'),
            h('span', { text: name })
          ]));
        });
        itemsWrap.appendChild(itemsList);
        body.appendChild(itemsWrap);
      }

      var cancelBtn = h('button', {
        type: 'button',
        class: 'btn tb-modal-btn tb-modal-btn-cancel',
        id: 'tbConfirmModalCancel',
        text: cancelText
      });

      var confirmBtn = h('button', {
        type: 'button',
        class: 'btn tb-modal-btn tb-modal-btn-' + variant,
        id: 'tbConfirmModalConfirm',
        text: confirmText
      });

      var actions = h('div', { class: 'tb-modal-actions' }, [
        cancelBtn,
        confirmBtn
      ]);

      card.appendChild(header);
      card.appendChild(body);
      card.appendChild(actions);
      backdrop.appendChild(card);

      function cleanup(result) {
        document.removeEventListener('keydown', onKeyDown);
        backdrop.classList.add('closing');
        setTimeout(function () {
          if (backdrop.parentNode) {
            backdrop.parentNode.removeChild(backdrop);
          }
          resolve(result);
        }, 150);
      }

      function onKeyDown(e) {
        if (e.key === 'Escape') {
          e.preventDefault();
          cleanup(false);
        } else if (e.key === 'Enter') {
          e.preventDefault();
          cleanup(true);
        }
      }

      closeBtn.addEventListener('click', function () { cleanup(false); });
      cancelBtn.addEventListener('click', function () { cleanup(false); });
      confirmBtn.addEventListener('click', function () { cleanup(true); });

      backdrop.addEventListener('click', function (e) {
        if (e.target === backdrop) {
          cleanup(false);
        }
      });

      document.addEventListener('keydown', onKeyDown);
      document.body.appendChild(backdrop);

      setTimeout(function () {
        try { confirmBtn.focus(); } catch (err) {}
      }, 50);
    });
  }

  function renderBannerFailure(failure, onRetry, id) {
    if (!failure) return null;
    return h('div', { class: 'alert alert-danger tb-banner', id: id || 'tbFailure', role: 'alert' }, [
      icon('exclamation-octagon'),
      h('span', { text: ' ' + failure.message + ' ' }),
      failure.canRetry ? btn('Retry', 'btn-outline-danger', onRetry, { id: (id || 'tb') + 'Retry' }) : null
    ]);
  }

  /**
   * Smoothly dismisses a VS Code-style toast notification with exit animation.
   */
  function dismissToast(toastEl, onDismiss) {
    if (!toastEl || (toastEl.classList && toastEl.classList.contains('tb-toast-exit'))) return;
    if (toastEl._dismissTimer) {
      clearTimeout(toastEl._dismissTimer);
      toastEl._dismissTimer = null;
    }
    if (toastEl.classList) {
      toastEl.classList.add('tb-toast-exit');
      setTimeout(function () {
        if (toastEl.parentNode) {
          toastEl.parentNode.removeChild(toastEl);
        }
        if (typeof onDismiss === 'function') {
          onDismiss();
        }
      }, 250);
    } else {
      if (toastEl.parentNode) {
        toastEl.parentNode.removeChild(toastEl);
      }
      if (typeof onDismiss === 'function') {
        onDismiss();
      }
    }
  }

  /**
   * Renders a VS Code-style toast notification element with severity theme,
   * dismiss button, and auto-dismiss progress bar.
   */
  function renderToastNotice(notice, onDismiss, id, duration) {
    if (!notice) return null;
    var kind = notice.kind || 'info';
    var toastId = id || 'tbNotice';
    var dur = typeof duration === 'number' ? duration : 5000;

    var iconMap = {
      info: 'info-circle-fill',
      success: 'check-circle-fill',
      warning: 'exclamation-triangle-fill',
      danger: 'x-circle-fill',
      error: 'x-circle-fill'
    };
    var iconName = iconMap[kind] || 'info-circle-fill';

    var closeBtn = h('button', {
      type: 'button',
      class: 'tb-toast-close',
      'aria-label': 'Close notification',
      title: 'Dismiss'
    }, [
      icon('x-lg')
    ]);

    var progressBar = h('div', {
      class: 'tb-toast-progress-bar',
      style: dur > 0 ? 'animation-duration: ' + (dur / 1000) + 's;' : 'display: none;'
    });
    var progressTrack = h('div', { class: 'tb-toast-progress' }, [progressBar]);

    var toast = h('div', {
      class: 'tb-toast-item tb-toast-' + kind,
      id: toastId,
      role: 'status',
      'aria-live': kind === 'danger' || kind === 'error' ? 'assertive' : 'polite'
    }, [
      h('div', { class: 'tb-toast-icon' }, [icon(iconName)]),
      h('div', { class: 'tb-toast-content' }, [
        h('div', { class: 'tb-toast-message', text: notice.text })
      ]),
      closeBtn,
      progressTrack
    ]);

    if (!toast) return null;

    toast.dataset.text = notice.text || '';
    toast.dataset.kind = kind;

    function triggerClose() {
      dismissToast(toast, onDismiss);
    }

    if (closeBtn && typeof closeBtn.addEventListener === 'function') {
      closeBtn.addEventListener('click', function (e) {
        e.stopPropagation();
        triggerClose();
      });
    }

    if (typeof window !== 'undefined' && dur > 0 && typeof toast.addEventListener === 'function') {
      var startTime = Date.now();
      var remaining = dur;

      function startTimer() {
        if (toast.classList.contains('tb-toast-exit')) return;
        startTime = Date.now();
        toast._dismissTimer = setTimeout(function () {
          triggerClose();
        }, remaining);
      }

      function pauseTimer() {
        if (toast._dismissTimer) {
          clearTimeout(toast._dismissTimer);
          toast._dismissTimer = null;
          remaining -= (Date.now() - startTime);
          if (remaining < 400) remaining = 400;
        }
      }

      toast.addEventListener('mouseenter', pauseTimer);
      toast.addEventListener('mouseleave', function () {
        startTimer();
      });

      startTimer();
    }

    return toast;
  }

  function renderBannerNotice(notice, onDismiss, id) {
    return renderToastNotice(notice, onDismiss, id);
  }

  function renderSidebarItem(opts) {
    var it = opts.item;
    var isActive = !!opts.isActive;
    var isSelected = !!opts.isSelected;
    var selectMode = !!opts.selectMode;
    var onSelect = opts.onSelect;
    var onToggleSelect = opts.onToggleSelect;

    var kids = [];
    if (selectMode) {
      kids.push(h('input', {
        type: 'checkbox',
        class: 'form-check-input tb-item-check',
        checked: isSelected,
        title: 'Select ' + (it.name || it.id),
        'aria-label': 'Select ' + (it.name || it.id),
        onclick: function (e) {
          e.stopPropagation();
          if (typeof onToggleSelect === 'function') onToggleSelect(it.id);
        }
      }));
    }

    kids.push(h('div', { class: 'tb-item-info' }, [
      h('span', { class: 'tb-item-name', text: it.name || it.id, title: 'Name: ' + (it.name || it.id) }),
      h('span', { class: 'tb-item-id', text: it.id, title: 'ID: ' + it.id })
    ]));

    kids.push(h('span', { class: 'badge tb-ver', text: typeof it.latestVersion === 'number' ? 'v' + it.latestVersion : it.latestVersion }));

    return h('div', {
      class: 'tb-item' + (isActive ? ' active' : '') + (isSelected ? ' selected' : '') + (selectMode ? ' in-select-mode' : ''),
      role: 'button',
      tabindex: '0',
      onclick: function (e) {
        if (selectMode) {
          if (typeof onToggleSelect === 'function') onToggleSelect(it.id);
          return;
        }
        if (e.ctrlKey || e.metaKey) {
          if (typeof onToggleSelect === 'function') {
            onToggleSelect(it.id);
            return;
          }
        }
        if (typeof onSelect === 'function') onSelect(it.id);
      }
    }, kids);
  }

  function renderVersionBar(opts) {
    if (typeof document === 'undefined') return null;
    var cur = opts.cur;
    var store = opts.store;
    var confirmLeave = opts.confirmLeave;
    var idPrefix = opts.idPrefix || 'tb';
    var live = opts.live || function (fn) { fn(); };

    if (!cur) return null;

    var bar = h('div', { class: 'tb-version-bar', id: idPrefix + 'VersionBar' });

    // Left side: 2 read-only form inputs for id and name with pencil edit icon behind each
    var leftWrap = h('div', { class: 'tb-version-bar-left' });

    function createEditInputGroup(field, labelText, value, isMono, onSaveValue, placeholderText) {
      var fieldPill = h('div', {
        class: 'tb-pill-field' + (cur.readOnly ? ' disabled' : ''),
        id: idPrefix + field.charAt(0).toUpperCase() + field.slice(1) + 'Field'
      });

      var badge = h('span', { class: 'tb-pill-tag', text: labelText });

      var input = h('input', {
        type: 'text',
        class: 'tb-pill-input' + (isMono ? ' tb-font-mono' : ''),
        id: idPrefix + field.charAt(0).toUpperCase() + field.slice(1) + 'Input',
        value: value || '',
        placeholder: placeholderText || '',
        readOnly: true,
        spellcheck: false,
        autocomplete: 'off',
        title: labelText + ' (' + (cur.readOnly ? 'read-only' : 'click or pencil to edit') + ')',
        'aria-label': labelText
      });

      var btnIcon = icon('pencil');
      var editBtn = h('button', {
        type: 'button',
        class: 'tb-pill-action',
        id: idPrefix + field.charAt(0).toUpperCase() + field.slice(1) + 'EditBtn',
        title: cur.readOnly ? 'Read-only version' : 'Edit ' + labelText,
        disabled: cur.readOnly
      }, [btnIcon]);

      function enableEdit() {
        if (cur.readOnly) return;
        input.readOnly = false;
        fieldPill.classList.add('editing');
        editBtn.classList.add('active');
        btnIcon.className = 'bi bi-check-lg';
        editBtn.title = 'Save ' + labelText;
        input.focus();
        input.select();
      }

      function finishEdit() {
        if (input.readOnly) return;
        input.readOnly = true;
        fieldPill.classList.remove('editing');
        editBtn.classList.remove('active');
        btnIcon.className = 'bi bi-pencil';
        editBtn.title = 'Edit ' + labelText;
        var val = input.value.trim();
        if (typeof onSaveValue === 'function') {
          onSaveValue(val);
        }
      }

      fieldPill.addEventListener('click', function (e) {
        if (e.target === editBtn || editBtn.contains(e.target)) return;
        if (input.readOnly && !cur.readOnly) {
          enableEdit();
        }
      });

      editBtn.addEventListener('click', function (e) {
        e.preventDefault();
        e.stopPropagation();
        if (input.readOnly) {
          enableEdit();
        } else {
          finishEdit();
        }
      });

      input.addEventListener('dblclick', function () {
        if (input.readOnly && !cur.readOnly) enableEdit();
      });

      input.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') {
          e.preventDefault();
          finishEdit();
        } else if (e.key === 'Escape') {
          e.preventDefault();
          input.value = value || '';
          input.readOnly = true;
          fieldPill.classList.remove('editing');
          editBtn.classList.remove('active');
          btnIcon.className = 'bi bi-pencil';
        }
      });

      input.addEventListener('blur', function () {
        finishEdit();
      });

      fieldPill.appendChild(badge);
      fieldPill.appendChild(input);
      fieldPill.appendChild(editBtn);

      return fieldPill;
    }

    var idGroup = createEditInputGroup('id', 'ID', cur.id, true, function (newId) {
      if (!newId) {
        var el = typeof document !== 'undefined' ? document.getElementById(idPrefix + 'IdInput') : null;
        if (el) el.value = cur.id || '';
        return;
      }
      if (store && typeof store.setId === 'function') {
        store.setId(newId);
      } else {
        cur.id = newId;
        if (store && store.emit) store.emit();
      }
    }, 'id');

    var nameGroup = createEditInputGroup('name', 'Name', cur.name || '', false, function (newName) {
      var val = (newName !== undefined && newName !== null) ? String(newName).trim() : '';
      if (!val) {
        val = cur.id || '';
        var el = typeof document !== 'undefined' ? document.getElementById(idPrefix + 'NameInput') : null;
        if (el) el.value = val;
      }
      if (store && typeof store.setName === 'function') {
        store.setName(val);
      } else {
        cur.name = val;
        if (store && store.emit) store.emit();
      }
    }, 'name');

    leftWrap.appendChild(idGroup);
    leftWrap.appendChild(nameGroup);
    bar.appendChild(leftWrap);

    // Right side: Modern Version Select
    var rightWrap = h('div', { class: 'tb-version-bar-right' });
    var select = h('select', {
      class: 'form-select form-select-sm tb-version-select tb-hidden-select',
      id: idPrefix + 'VersionSelect',
      title: 'Select configuration version',
      'aria-label': 'Select configuration version'
    });

    var activeVer = null;
    if (store && typeof store.getActiveVersion === 'function') {
      activeVer = store.getActiveVersion(cur.id);
    }
    if (activeVer === undefined || activeVer === null) {
      var itInList = store && store.state && store.state.list && store.state.list.items && store.state.list.items.find(function (x) { return x.id === cur.id; });
      if (itInList && itInList.activeVersion !== undefined) {
        activeVer = itInList.activeVersion;
      }
    }

    var latestVer = cur.latestVersion || (cur.versions && cur.versions.length ? cur.versions[0] : cur.version);
    var inUseVersion = cur.readOnly
      ? (activeVer !== undefined && activeVer !== null ? activeVer : (cur.latestVersion || latestVer))
      : (cur.version || activeVer || latestVer);

    var versionItems = [];
    if (cur.isNew) {
      select.appendChild(h('option', { value: 'new', selected: true }, ['Version: Draft (new)']));
      select.disabled = true;
      versionItems.push({
        val: 'new',
        text: 'Draft (new)',
        isSelected: true
      });
    } else if (cur.isDefault) {
      select.appendChild(h('option', { value: '0', selected: true }, ['Version: v0 (default)']));
      select.disabled = true;
      versionItems.push({
        val: '0',
        text: 'v0 (default)',
        isSelected: true
      });
    } else if (cur.versions && cur.versions.length) {
      cur.versions.forEach(function (v) {
        var isInUse = (v === inUseVersion);
        var isSelected = cur.readOnly ? (cur.viewingVersion === v) : isInUse;
        var optText = 'Version: v' + v + (isInUse ? ' (current)' : '');
        select.appendChild(h('option', { value: String(v), selected: isSelected }, [optText]));
        versionItems.push({
          val: String(v),
          text: 'v' + v + (isInUse ? ' (current)' : ''),
          isInUse: isInUse,
          isSelected: isSelected
        });
      });
    } else {
      var vNum = cur.version || 1;
      select.appendChild(h('option', { value: String(vNum), selected: true }, [
        'Version: v' + vNum + ' (current)'
      ]));
      versionItems.push({
        val: String(vNum),
        text: 'v' + vNum + ' (current)',
        isInUse: true,
        isSelected: true
      });
    }

    // Modern Custom Select UI
    var customSelectWrap = h('div', {
      class: 'tb-custom-select tb-version-custom-select',
      id: idPrefix + 'VersionCustomSelect'
    });

    var triggerIcon = icon('clock-history');
    triggerIcon.className += ' tb-custom-select-trigger-icon';

    var triggerLabel = h('span', { class: 'tb-custom-select-trigger-label' });

    var arrowIcon = icon('chevron-down');
    arrowIcon.className += ' tb-custom-select-arrow';

    var hasMultiple = !select.disabled && versionItems.length > 1;

    var triggerBtnKids = [
      h('div', { class: 'tb-custom-select-trigger-left' }, [
        triggerIcon,
        triggerLabel
      ])
    ];
    if (hasMultiple) {
      triggerBtnKids.push(arrowIcon);
    }

    var triggerBtn = h('button', {
      type: 'button',
      class: 'tb-custom-select-trigger tb-version-trigger' + (select.disabled ? ' disabled' : ''),
      'aria-haspopup': 'listbox',
      'aria-expanded': 'false',
      disabled: select.disabled
    }, triggerBtnKids);

    var menu = h('div', { class: 'tb-custom-select-menu', role: 'listbox' });

    function syncTrigger() {
      var curVal = select.value;
      var found = null;
      for (var j = 0; j < versionItems.length; j++) {
        if (versionItems[j].val === curVal) {
          found = versionItems[j];
          break;
        }
      }
      if (!found && versionItems.length > 0) {
        found = versionItems[0];
      }
      if (found) {
        triggerLabel.textContent = found.text;
      }

      var items = menu.querySelectorAll('.tb-custom-select-item');
      for (var k = 0; k < items.length; k++) {
        var el = items[k];
        if (el.getAttribute('data-value') === curVal) {
          el.classList.add('selected');
        } else {
          el.classList.remove('selected');
        }
      }
    }

    function openMenu() {
      if (select.disabled || !hasMultiple) return;
      var allOpen = (typeof document !== 'undefined' && typeof document.querySelectorAll === 'function')
        ? document.querySelectorAll('.tb-custom-select.is-open')
        : [];
      for (var m = 0; m < allOpen.length; m++) {
        allOpen[m].classList.remove('is-open');
      }
      customSelectWrap.classList.add('is-open');
      triggerBtn.setAttribute('aria-expanded', 'true');
      if (typeof document !== 'undefined' && typeof document.addEventListener === 'function') {
        document.addEventListener('click', onDocClick, true);
      }
    }

    function closeMenu() {
      customSelectWrap.classList.remove('is-open');
      triggerBtn.setAttribute('aria-expanded', 'false');
      if (typeof document !== 'undefined' && typeof document.removeEventListener === 'function') {
        document.removeEventListener('click', onDocClick, true);
      }
    }

    function toggleMenu() {
      if (customSelectWrap.classList.contains('is-open')) {
        closeMenu();
      } else {
        openMenu();
      }
    }

    function onDocClick(e) {
      if (customSelectWrap.contains && !customSelectWrap.contains(e.target)) {
        closeMenu();
      }
    }

    if (hasMultiple) {
      triggerBtn.addEventListener('click', function (e) {
        if (typeof e.stopPropagation === 'function') e.stopPropagation();
        toggleMenu();
      });
    }

    versionItems.forEach(function (item) {
      var checkIcon = icon('check2');
      checkIcon.className += ' tb-custom-select-check';

      var labelSpan = h('span', { class: 'tb-custom-select-item-label', text: item.text });

      var menuRow = h('div', {
        class: 'tb-custom-select-item' + (item.isSelected ? ' selected' : ''),
        role: 'option',
        'data-value': item.val,
        onclick: function (e) {
          if (e && typeof e.stopPropagation === 'function') e.stopPropagation();
          closeMenu();
          if (select.value === item.val) return;
          select.value = item.val;
          syncTrigger();

          if (typeof select.dispatchEvent === 'function' && typeof Event === 'function') {
            select.dispatchEvent(new Event('change', { bubbles: true }));
          } else if (select._listeners && select._listeners['change']) {
            select._listeners['change'].forEach(function (fn) {
              fn({ target: select });
            });
          }
        }
      }, [
        h('div', { class: 'tb-custom-select-item-left' }, [labelSpan]),
        h('div', { class: 'tb-custom-select-item-right' }, [checkIcon])
      ]);
      menu.appendChild(menuRow);
    });

    syncTrigger();

    var isChanged = opts.isChanged;
    var itemLabel = opts.itemLabel || 'configuration';

    select.addEventListener('change', function (e) {
      var v = parseInt(e.target.value, 10);
      if (isNaN(v)) return;
      var active = cur.readOnly ? cur.viewingVersion : inUseVersion;

      function proceed() {
        if (v === inUseVersion && !cur.readOnly) {
          return;
        }
        if (v === inUseVersion) {
          store.open(cur.id, inUseVersion);
        } else {
          store.openVersion(v);
        }
      }

      if (typeof isChanged === 'function' && isChanged()) {
        confirmModal({
          title: 'Discard Changes',
          message: 'You have unsaved changes in this ' + itemLabel + '. Do you want to discard them?',
          confirmText: 'Discard Changes',
          confirmVariant: 'warning',
          icon: 'exclamation-triangle'
        }).then(function (discard) {
          if (!discard) {
            select.value = String(active);
            syncTrigger();
            return;
          }
          proceed();
        });
        return;
      }

      if (typeof confirmLeave === 'function' && !confirmLeave()) {
        select.value = String(active);
        syncTrigger();
        return;
      }
      proceed();
    });

    customSelectWrap.appendChild(select);
    customSelectWrap.appendChild(triggerBtn);
    if (hasMultiple) {
      customSelectWrap.appendChild(menu);
    }

    rightWrap.appendChild(customSelectWrap);

    if (cur.versionsError) {
      rightWrap.appendChild(h('span', { class: 'tb-error text-danger' }, [
        icon('exclamation-triangle'),
        h('span', { text: ' ' + cur.versionsError })
      ]));
      rightWrap.appendChild(btn('Retry', 'btn-outline-danger', function () {
        store.loadVersions();
      }, { id: idPrefix + 'RetryVersions' }));
    }

    bar.appendChild(rightWrap);
    return bar;
  }

  /**
   * Manages group assignments persisted in localStorage or memory storage.
   *
   * @param {string} storageKey Storage key (e.g. 'mm_tb_groups')
   * @param {Object} [storage] Storage instance with getItem/setItem (defaults to window.localStorage)
   */
  function createGroupManager(storageKey, storage) {
    var store = storage || (typeof window !== 'undefined' ? window.localStorage : null);
    var namesKey = storageKey + '_all_names';

    function load() {
      try {
        if (!store) return {};
        var raw = store.getItem(storageKey);
        return raw ? JSON.parse(raw) : {};
      } catch (e) {
        return {};
      }
    }

    function save(map) {
      try {
        if (!store) return;
        store.setItem(storageKey, JSON.stringify(map || {}));
      } catch (e) {}
    }

    function loadNames() {
      try {
        if (!store) return [];
        var raw = store.getItem(namesKey);
        var arr = raw ? JSON.parse(raw) : [];
        return Array.isArray(arr) ? arr : [];
      } catch (e) {
        return [];
      }
    }

    function saveNames(names) {
      try {
        if (!store) return;
        store.setItem(namesKey, JSON.stringify(names || []));
      } catch (e) {}
    }

    function getKnownNames(map) {
      var saved = loadNames();
      var set = {};
      var changed = false;
      saved.forEach(function (n) {
        if (n && typeof n === 'string') {
          var t = n.trim();
          if (t) set[t] = true;
        }
      });
      if (map) {
        Object.keys(map).forEach(function (id) {
          if (map[id] && typeof map[id] === 'string') {
            var t = map[id].trim();
            if (t) {
              if (!set[t]) {
                set[t] = true;
                changed = true;
              }
            }
          }
        });
      }
      try {
        var colKey = storageKey.replace(/_groups$/, '_collapsed_groups');
        var colRaw = store && store.getItem(colKey);
        if (colRaw) {
          var colObj = JSON.parse(colRaw);
          if (colObj && typeof colObj === 'object') {
            Object.keys(colObj).forEach(function (k) {
              if (k && k !== '__ungrouped__') {
                var t = k.trim();
                if (t && !set[t]) {
                  set[t] = true;
                  changed = true;
                }
              }
            });
          }
        }
      } catch (e) {}
      var res = Object.keys(set).sort();
      if (changed) {
        saveNames(res);
      }
      return res;
    }

    return {
      getAll: function () {
        return load();
      },
      getGroup: function (id) {
        var map = load();
        return map[id] || null;
      },
      addGroup: function (groupName) {
        var trimmed = (groupName !== undefined && groupName !== null) ? String(groupName).trim() : '';
        if (!trimmed) return;
        var map = load();
        var names = getKnownNames(map);
        if (names.indexOf(trimmed) === -1) {
          names.push(trimmed);
          names.sort();
          saveNames(names);
        }
        return names;
      },
      setGroup: function (id, groupName) {
        var map = load();
        getKnownNames(map);
        var trimmed = (groupName !== undefined && groupName !== null) ? String(groupName).trim() : '';
        if (trimmed) {
          map[id] = trimmed;
          var names = getKnownNames(map);
          if (names.indexOf(trimmed) === -1) {
            names.push(trimmed);
            names.sort();
          }
          saveNames(names);
        } else {
          delete map[id];
        }
        save(map);
        return map;
      },
      removeGroup: function (id) {
        var map = load();
        getKnownNames(map);
        delete map[id];
        save(map);
        return map;
      },
      renameGroup: function (oldName, newName) {
        var map = load();
        var trimmed = (newName !== undefined && newName !== null) ? String(newName).trim() : '';
        Object.keys(map).forEach(function (id) {
          if (map[id] === oldName) {
            if (trimmed) {
              map[id] = trimmed;
            } else {
              delete map[id];
            }
          }
        });
        save(map);

        var names = getKnownNames(map);
        var nextNames = [];
        names.forEach(function (g) {
          if (g === oldName) {
            if (trimmed && nextNames.indexOf(trimmed) === -1) nextNames.push(trimmed);
          } else {
            if (nextNames.indexOf(g) === -1) nextNames.push(g);
          }
        });
        saveNames(nextNames.sort());
        return map;
      },
      deleteGroup: function (groupName) {
        var map = load();
        Object.keys(map).forEach(function (id) {
          if (map[id] === groupName) {
            delete map[id];
          }
        });
        save(map);

        var names = getKnownNames(map);
        var filtered = names.filter(function (g) { return g !== groupName; });
        saveNames(filtered);
        try {
          var colKey = storageKey.replace(/_groups$/, '_collapsed_groups');
          var colRaw = store && store.getItem(colKey);
          if (colRaw) {
            var colObj = JSON.parse(colRaw);
            if (colObj && colObj[groupName] !== undefined) {
              delete colObj[groupName];
              store.setItem(colKey, JSON.stringify(colObj));
            }
          }
        } catch (e) {}
        return map;
      },
      getGroupNames: function () {
        var map = load();
        return getKnownNames(map);
      }
    };
  }

  return {
    clone: clone,
    canon: canon,
    splitList: splitList,
    createEmitter: createEmitter,
    createFailureHandler: createFailureHandler,
    setNotice: setNotice,
    isDirty: isDirty,
    canSave: canSave,
    saveErrorOf: saveErrorOf,
    deleteItem: deleteItem,
    loadVersions: loadVersions,
    h: h,
    icon: icon,
    btn: btn,
    confirmLeave: confirmLeave,
    confirmModal: confirmModal,
    renderBannerFailure: renderBannerFailure,
    renderBannerNotice: renderBannerNotice,
    renderToastNotice: renderToastNotice,
    dismissToast: dismissToast,
    renderSidebarItem: renderSidebarItem,
    renderVersionBar: renderVersionBar,
    createGroupManager: createGroupManager
  };
});
