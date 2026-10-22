/**
 * @fileoverview Base view for configuration editors (Testbench and Infrastructure).
 *
 * Provides a standardized, reusable view lifecycle, sidebar navigation with
 * search dropdown & item management, error summary, version bar, and status
 * handling based on the Testbench view reference design.
 *
 * @version 1.0.0
 */
(function () {
  'use strict';

  var MM = (typeof window !== 'undefined' && window.MicroserviceManager) ? window.MicroserviceManager : {};
  var Common = (MM && MM.configCommon) ||
               (typeof require !== 'undefined' ? require('./ConfigCommon.js') : {});

  var h = Common.h;
  var icon = Common.icon;
  var btn = Common.btn;

  function serviceLabel(s) {
    return s === 'catalog' ? 'Catalog' : 'Configuration Hub';
  }

  function section(title, iconName, kids, id, tools) {
    var headLeft = [icon(iconName)];
    if (typeof title === 'string') {
      headLeft.push(h('h2', { text: title }));
    } else if (Array.isArray(title)) {
      headLeft = headLeft.concat(title);
    } else if (title) {
      headLeft.push(title);
    }

    var headKids = [h('div', { class: 'tb-card-head-left' }, headLeft)];
    if (tools && tools.length) {
      headKids.push(h('div', { class: 'tb-card-head-right' }, tools));
    }

    return h('section', { class: 'tb-card', id: id }, [
      h('div', { class: 'tb-card-head' }, headKids)
    ].concat(kids));
  }

  /**
   * Creates a configured base view instance.
   *
   * @param {Object} spec View specification
   */
  function createBaseView(spec) {
    var idPrefix = spec.idPrefix || 'tb';
    var title = spec.title || 'Configurations';
    var iconName = spec.iconName || 'boxes';
    var itemLabel = spec.itemLabel || 'configuration';
    var sidePaneId = spec.sidePaneId;
    var fallbackSideId = spec.fallbackSideId;
    var contentId = spec.contentId;
    var searchPlaceholder = spec.searchPlaceholder || 'Search or enter ID…';
    var emptyTitle = spec.emptyTitle || 'No items created yet';
    var emptySubtext = spec.emptySubtext || 'Use + to create the first one.';
    var hasNameInput = !!spec.hasNameInput;

    var store = null;
    var sideEl = null;
    var mainEl = null;
    var typing = false;

    var groupMgr = Common.createGroupManager('mm_' + idPrefix + '_groups', spec.storage || (typeof window !== 'undefined' ? window.localStorage : null));
    var collapseKey = 'mm_' + idPrefix + '_collapsed_groups';
    var groupSortKey = 'mm_' + idPrefix + '_group_sort';
    var groupsOrderKey = 'mm_' + idPrefix + '_groups_order';

    function loadCollapsedGroups() {
      try {
        var s = spec.storage || (typeof window !== 'undefined' ? window.localStorage : null);
        if (!s) return {};
        var raw = s.getItem(collapseKey);
        return raw ? JSON.parse(raw) : {};
      } catch (e) {
        return {};
      }
    }

    function saveCollapsedGroups(map) {
      try {
        var s = spec.storage || (typeof window !== 'undefined' ? window.localStorage : null);
        if (!s) return;
        s.setItem(collapseKey, JSON.stringify(map || {}));
      } catch (e) {}
    }

    function loadGroupSort() {
      try {
        var s = spec.storage || (typeof window !== 'undefined' ? window.localStorage : null);
        if (!s) return {};
        var raw = s.getItem(groupSortKey);
        return raw ? JSON.parse(raw) : {};
      } catch (e) {
        return {};
      }
    }

    function saveGroupSort(map) {
      try {
        var s = spec.storage || (typeof window !== 'undefined' ? window.localStorage : null);
        if (!s) return;
        s.setItem(groupSortKey, JSON.stringify(map || {}));
      } catch (e) {}
    }

    function loadGroupsOrder() {
      try {
        var s = spec.storage || (typeof window !== 'undefined' ? window.localStorage : null);
        if (!s) return 'asc';
        var raw = s.getItem(groupsOrderKey);
        return raw === 'desc' ? 'desc' : 'asc';
      } catch (e) {
        return 'asc';
      }
    }

    function saveGroupsOrder(order) {
      try {
        var s = spec.storage || (typeof window !== 'undefined' ? window.localStorage : null);
        if (!s) return;
        s.setItem(groupsOrderKey, order === 'desc' ? 'desc' : 'asc');
      } catch (e) {}
    }

    var ui = Object.assign({
      creating: false,
      createErr: null,
      newId: '',
      newName: '',
      searchQuery: '',
      searchOpen: false,
      selectMode: false,
      selectedIds: [],
      activeMenuId: null,
      activeGroupMenu: null,
      groupSort: loadGroupSort(),
      groupsOrder: loadGroupsOrder(),
      collapsedGroups: loadCollapsedGroups()
    }, spec.initialUI || {});

    function closeActiveMenu() {
      if (typeof document !== 'undefined') {
        var old = document.getElementById(idPrefix + 'ItemMenu');
        if (old && old.parentNode) old.parentNode.removeChild(old);
        var oldGrp = document.getElementById(idPrefix + 'GroupMenu');
        if (oldGrp && oldGrp.parentNode) oldGrp.parentNode.removeChild(oldGrp);
        var oldBtn = (typeof document.querySelector === 'function') ? document.querySelector('.tb-item-opt-btn.active') : null;
        if (oldBtn) oldBtn.classList.remove('active');
        var oldGrpBtn = (typeof document.querySelector === 'function') ? document.querySelector('.tb-group-opt-btn.active') : null;
        if (oldGrpBtn) oldGrpBtn.classList.remove('active');
      }
      ui.activeMenuId = null;
      ui.activeGroupMenu = null;
    }

    function sortItemsList(items, order) {
      if (!items || !items.length || !order) return items;
      return items.slice().sort(function (a, b) {
        var nameA = String(a.name || a.id || '').toLowerCase();
        var nameB = String(b.name || b.id || '').toLowerCase();
        var comp = nameA.localeCompare(nameB, undefined, { numeric: true, sensitivity: 'base' });
        return (order === 'desc') ? -comp : comp;
      });
    }

    function toggleItemMenu(it, optBtn) {
      if (ui.activeMenuId === it.id) {
        closeActiveMenu();
        return;
      }
      closeActiveMenu();
      ui.activeMenuId = it.id;
      if (optBtn) optBtn.classList.add('active');

      var curGroup = groupMgr.getGroup(it.id);

      var menu = h('div', {
        class: 'tb-item-menu',
        id: idPrefix + 'ItemMenu',
        role: 'menu'
      });

      // 1. Duplicate
      var dupBtn = h('button', {
        type: 'button',
        class: 'tb-item-menu-item',
        id: idPrefix + 'MenuDup_' + it.id,
        role: 'menuitem',
        onclick: function (e) {
          e.stopPropagation();
          closeActiveMenu();
          promptDuplicate(it);
        }
      }, [
        icon('copy'),
        h('span', { text: 'Duplicate...' })
      ]);
      menu.appendChild(dupBtn);

      // 2. Group
      var grpBtn = h('button', {
        type: 'button',
        class: 'tb-item-menu-item',
        id: idPrefix + 'MenuGroup_' + it.id,
        role: 'menuitem',
        onclick: function (e) {
          e.stopPropagation();
          closeActiveMenu();
          promptGroup([it.id]);
        }
      }, [
        icon(curGroup ? 'folder2' : 'folder-plus'),
        h('span', { text: curGroup ? ('Change Group (' + curGroup + ')...') : 'Assign Group...' })
      ]);
      menu.appendChild(grpBtn);

      // 3. Remove from group (if grouped)
      if (curGroup) {
        var ungrpBtn = h('button', {
          type: 'button',
          class: 'tb-item-menu-item',
          id: idPrefix + 'MenuUngroup_' + it.id,
          role: 'menuitem',
          onclick: function (e) {
            e.stopPropagation();
            closeActiveMenu();
            groupMgr.removeGroup(it.id);
            renderSide();
            Common.setNotice(store.state, 'info', 'Removed "' + (it.name || it.id) + '" from group.');
            store.emit();
          }
        }, [
          icon('folder-x'),
          h('span', { text: 'Remove from Group' })
        ]);
        menu.appendChild(ungrpBtn);
      }

      menu.appendChild(h('div', { class: 'tb-item-menu-divider' }));

      // 4. Delete
      var delBtn = h('button', {
        type: 'button',
        class: 'tb-item-menu-item danger',
        id: idPrefix + 'MenuDel_' + it.id,
        role: 'menuitem',
        onclick: function (e) {
          e.stopPropagation();
          closeActiveMenu();
          Common.confirmModal({
            title: 'Delete ' + itemLabel,
            message: 'Are you sure you want to delete ' + itemLabel + ' "' + it.id + '"? This action cannot be undone.',
            confirmText: 'Delete',
            confirmVariant: 'danger',
            icon: 'trash3'
          }).then(function (ok) {
            if (!ok) return;
            store.deleteItem(it.id).then(function () {
              groupMgr.removeGroup(it.id);
              renderSide();
              renderMain();
            });
          });
        }
      }, [
        icon('trash3'),
        h('span', { text: 'Delete' })
      ]);
      menu.appendChild(delBtn);

      if (typeof document !== 'undefined') {
        var rect = (optBtn && typeof optBtn.getBoundingClientRect === 'function')
          ? optBtn.getBoundingClientRect()
          : { bottom: 0, right: 180, left: 0, top: 0 };
        var top = rect.bottom + 4;
        var left = rect.right - 180;
        if (left < 10) left = 10;
        if (typeof window !== 'undefined' && left + 185 > window.innerWidth) {
          left = window.innerWidth - 190;
        }
        menu.style.top = top + 'px';
        menu.style.left = left + 'px';

        if (document.body && typeof document.body.appendChild === 'function') {
          document.body.appendChild(menu);
        }

        var onDocClick = function (e) {
          if (!menu.contains(e.target) && e.target !== optBtn && !optBtn.contains(e.target)) {
            closeActiveMenu();
            document.removeEventListener('click', onDocClick);
            document.removeEventListener('keydown', onDocKeyDown);
          }
        };
        var onDocKeyDown = function (e) {
          if (e.key === 'Escape') {
            closeActiveMenu();
            document.removeEventListener('click', onDocClick);
            document.removeEventListener('keydown', onDocKeyDown);
          }
        };
        setTimeout(function () {
          document.addEventListener('click', onDocClick);
          document.addEventListener('keydown', onDocKeyDown);
        }, 10);
      }
    }

    function toggleGroupMenu(groupName, itemsInGroup, optBtn) {
      if (ui.activeGroupMenu === groupName) {
        closeActiveMenu();
        return;
      }
      closeActiveMenu();
      ui.activeGroupMenu = groupName;
      if (optBtn && optBtn.classList) optBtn.classList.add('active');

      var isUngrouped = groupName === '__ungrouped__';
      var curItemSort = (ui.groupSort && ui.groupSort[groupName]) || null;
      var curGroupsOrder = ui.groupsOrder || 'asc';
      var safeGrpId = groupName.replace(/\s+/g, '_');

      var menu = h('div', {
        class: 'tb-item-menu tb-group-menu',
        id: idPrefix + 'GroupMenu',
        role: 'menu'
      });

      menu.appendChild(h('div', {
        class: 'tb-group-menu-title',
        text: isUngrouped ? 'Ungrouped' : groupName
      }));

      // 1. Sort items in group A -> Z
      var sortAzBtn = h('button', {
        type: 'button',
        class: 'tb-item-menu-item' + (curItemSort === 'asc' ? ' active' : ''),
        id: idPrefix + 'GroupMenuSortAZ_' + safeGrpId,
        role: 'menuitem',
        onclick: function (e) {
          e.stopPropagation();
          closeActiveMenu();
          ui.groupSort = ui.groupSort || {};
          ui.groupSort[groupName] = 'asc';
          saveGroupSort(ui.groupSort);
          renderSide();
        }
      }, [
        icon('sort-alpha-down'),
        h('span', { text: 'Sort Items (A → Z)' }),
        curItemSort === 'asc' ? h('span', { class: 'tb-menu-check', text: '✓' }) : null
      ].filter(Boolean));
      menu.appendChild(sortAzBtn);

      // 2. Sort items in group Z -> A
      var sortZaBtn = h('button', {
        type: 'button',
        class: 'tb-item-menu-item' + (curItemSort === 'desc' ? ' active' : ''),
        id: idPrefix + 'GroupMenuSortZA_' + safeGrpId,
        role: 'menuitem',
        onclick: function (e) {
          e.stopPropagation();
          closeActiveMenu();
          ui.groupSort = ui.groupSort || {};
          ui.groupSort[groupName] = 'desc';
          saveGroupSort(ui.groupSort);
          renderSide();
        }
      }, [
        icon('sort-alpha-up'),
        h('span', { text: 'Sort Items (Z → A)' }),
        curItemSort === 'desc' ? h('span', { class: 'tb-menu-check', text: '✓' }) : null
      ].filter(Boolean));
      menu.appendChild(sortZaBtn);

      menu.appendChild(h('div', { class: 'tb-item-menu-divider' }));

      // 3. Sort groups A -> Z
      var sortGroupsAzBtn = h('button', {
        type: 'button',
        class: 'tb-item-menu-item' + (curGroupsOrder === 'asc' ? ' active' : ''),
        id: idPrefix + 'GroupMenuSortGroupsAZ_' + safeGrpId,
        role: 'menuitem',
        onclick: function (e) {
          e.stopPropagation();
          closeActiveMenu();
          ui.groupsOrder = 'asc';
          saveGroupsOrder(ui.groupsOrder);
          renderSide();
        }
      }, [
        icon('sort-down'),
        h('span', { text: 'Sort Groups (A → Z)' }),
        curGroupsOrder === 'asc' ? h('span', { class: 'tb-menu-check', text: '✓' }) : null
      ].filter(Boolean));
      menu.appendChild(sortGroupsAzBtn);

      // 4. Sort groups Z -> A
      var sortGroupsZaBtn = h('button', {
        type: 'button',
        class: 'tb-item-menu-item' + (curGroupsOrder === 'desc' ? ' active' : ''),
        id: idPrefix + 'GroupMenuSortGroupsZA_' + safeGrpId,
        role: 'menuitem',
        onclick: function (e) {
          e.stopPropagation();
          closeActiveMenu();
          ui.groupsOrder = 'desc';
          saveGroupsOrder(ui.groupsOrder);
          renderSide();
        }
      }, [
        icon('sort-up'),
        h('span', { text: 'Sort Groups (Z → A)' }),
        curGroupsOrder === 'desc' ? h('span', { class: 'tb-menu-check', text: '✓' }) : null
      ].filter(Boolean));
      menu.appendChild(sortGroupsZaBtn);

      // 5. Delete group
      if (!isUngrouped) {
        menu.appendChild(h('div', { class: 'tb-item-menu-divider' }));

        var delGrpBtn = h('button', {
          type: 'button',
          class: 'tb-item-menu-item danger',
          id: idPrefix + 'GroupMenuDel_' + safeGrpId,
          role: 'menuitem',
          onclick: function (e) {
            e.stopPropagation();
            closeActiveMenu();
            var count = (itemsInGroup || []).length;
            var msg = count > 0
              ? ('Delete group "' + groupName + '"? Its ' + count + ' item(s) will be moved to Ungrouped.')
              : ('Delete empty group "' + groupName + '"?');

            function doDelete() {
              groupMgr.deleteGroup(groupName);
              if (ui.groupSort && ui.groupSort[groupName]) {
                delete ui.groupSort[groupName];
                saveGroupSort(ui.groupSort);
              }
              renderSide();
            }

            if (typeof window !== 'undefined' && typeof window.confirm === 'function' && !window.confirm(msg)) {
              return;
            }
            doDelete();
          }
        }, [
          icon('trash3'),
          h('span', { text: 'Delete Group' })
        ]);
        menu.appendChild(delGrpBtn);
      }

      if (typeof document !== 'undefined') {
        var rect = (optBtn && typeof optBtn.getBoundingClientRect === 'function')
          ? optBtn.getBoundingClientRect()
          : { bottom: 0, right: 180, left: 0, top: 0 };
        var top = (rect.bottom || 0) + 4;
        var left = (rect.right || 180) - 180;
        if (left < 10) left = 10;
        if (typeof window !== 'undefined' && window.innerWidth && left + 185 > window.innerWidth) {
          left = window.innerWidth - 190;
        }
        menu.style.top = top + 'px';
        menu.style.left = left + 'px';

        if (document.body && typeof document.body.appendChild === 'function') {
          document.body.appendChild(menu);
        }

        var onDocClick = function (e) {
          if (!menu.contains(e.target) && (!optBtn || (e.target !== optBtn && !optBtn.contains(e.target)))) {
            closeActiveMenu();
            if (typeof document.removeEventListener === 'function') {
              document.removeEventListener('click', onDocClick);
              document.removeEventListener('keydown', onDocKeyDown);
            }
          }
        };
        var onDocKeyDown = function (e) {
          if (e.key === 'Escape') {
            closeActiveMenu();
            if (typeof document.removeEventListener === 'function') {
              document.removeEventListener('click', onDocClick);
              document.removeEventListener('keydown', onDocKeyDown);
            }
          }
        };
        setTimeout(function () {
          if (typeof document.addEventListener === 'function') {
            document.addEventListener('click', onDocClick);
            document.addEventListener('keydown', onDocKeyDown);
          }
        }, 10);
      }
    }

    function promptDuplicate(it) {
      function doShow() {
        showDuplicateDialog(it);
      }
      if (isChanged()) {
        Common.confirmModal({
          title: 'Discard Changes',
          message: 'You have unsaved changes in this ' + itemLabel + '. Duplicating will switch to the new copy and discard unsaved changes. Do you want to continue?',
          confirmText: 'Continue',
          confirmVariant: 'warning',
          icon: 'exclamation-triangle'
        }).then(function (ok) {
          if (ok) doShow();
        });
      } else {
        doShow();
      }
    }

    function showDuplicateDialog(it) {
      if (typeof document === 'undefined') return;

      var existingIds = (store.state.list.items || []).map(function (x) { return x.id; });
      function suggestCopyId(sourceId, existing) {
        var base = sourceId + '_copy';
        if (existing.indexOf(base) === -1) return base;
        var i = 2;
        while (existing.indexOf(base + '_' + i) !== -1) {
          i++;
        }
        return base + '_' + i;
      }
      var defaultId = suggestCopyId(it.id, existingIds);
      var suffix = defaultId.slice(it.id.length);
      var defaultName = (it.name || it.id) + suffix;
      var curGroup = groupMgr.getGroup(it.id);
      var allGroups = groupMgr.getGroupNames();

      var backdrop = h('div', {
        class: 'tb-modal-backdrop',
        id: idPrefix + 'DuplicateModalBackdrop',
        role: 'dialog',
        'aria-modal': 'true'
      });

      var card = h('div', { class: 'tb-modal-card' });
      var iconBox = h('div', { class: 'tb-modal-icon-box tb-modal-icon-primary' }, [icon('copy')]);
      var closeBtn = h('button', {
        type: 'button',
        class: 'tb-modal-close-btn',
        'aria-label': 'Close'
      }, [icon('x-lg')]);

      var header = h('div', { class: 'tb-modal-header' }, [iconBox, closeBtn]);

      var titleText = 'Duplicate ' + (itemLabel.charAt(0).toUpperCase() + itemLabel.slice(1));
      var body = h('div', { class: 'tb-modal-body' }, [
        h('h3', { class: 'tb-modal-title', text: titleText }),
        h('div', { class: 'tb-modal-source-badge' }, [
          icon('box-seam'),
          h('span', { class: 'tb-modal-source-label', text: 'Source: ' }),
          h('span', { class: 'tb-modal-source-name', text: (it.name || it.id) + ' (' + it.id + ')' })
        ])
      ]);

      var idIn = h('input', {
        type: 'text',
        class: 'form-control form-control-sm tb-modal-input',
        id: idPrefix + 'DuplicateIdInput',
        value: defaultId
      });
      var idGroup = h('div', { class: 'tb-modal-form-group' }, [
        h('label', { class: 'tb-modal-label', text: 'New Configuration ID *' }),
        idIn
      ]);
      body.appendChild(idGroup);

      var nameIn = null;
      var nameManuallyEdited = false;
      if (hasNameInput) {
        nameIn = h('input', {
          type: 'text',
          class: 'form-control form-control-sm tb-modal-input',
          id: idPrefix + 'DuplicateNameInput',
          value: defaultName
        });
        nameIn.addEventListener('input', function () {
          nameManuallyEdited = !!(nameIn.value && nameIn.value.trim());
        });
        var nameGroup = h('div', { class: 'tb-modal-form-group' }, [
          h('label', { class: 'tb-modal-label', text: 'New Configuration Name' }),
          nameIn
        ]);
        body.appendChild(nameGroup);
      }

      idIn.addEventListener('input', function () {
        if (!nameManuallyEdited && nameIn) {
          if (!it.name || it.name === it.id) {
            nameIn.value = idIn.value;
          } else {
            var prefix = it.id;
            if (idIn.value.indexOf(prefix) === 0) {
              nameIn.value = it.name + idIn.value.slice(prefix.length);
            } else {
              nameIn.value = idIn.value;
            }
          }
        }
      });

      var grpSelect = null;
      var newGrpIn = null;
      var closeGrpMenu = null;
      var groupList = allGroups.slice();
      if (curGroup && groupList.indexOf(curGroup) === -1) {
        groupList.unshift(curGroup);
      }
      grpSelect = h('select', {
          class: 'form-select form-select-sm tb-modal-select tb-hidden-select',
          id: idPrefix + 'DuplicateGroupSelect',
          style: 'display: none;'
        });
        groupList.forEach(function (g) {
          grpSelect.appendChild(h('option', { value: g, selected: (curGroup === g) }, [g]));
        });
        grpSelect.appendChild(h('option', { value: '__none__', selected: !curGroup }, ['Ungrouped']));
        grpSelect.appendChild(h('option', { value: '__new__' }, ['+ Create new group...']));

        newGrpIn = h('input', {
          type: 'text',
          class: 'form-control form-control-sm tb-modal-input',
          id: idPrefix + 'DuplicateNewGroupInput',
          placeholder: 'Enter new group name',
          style: 'display: none; margin-top: 6px;'
        });

        grpSelect.addEventListener('change', function () {
          newGrpIn.style.display = grpSelect.value === '__new__' ? '' : 'none';
          if (grpSelect.value === '__new__') newGrpIn.focus();
        });

        // Modern Custom Group Select UI
        var customGrpWrap = h('div', {
          class: 'tb-custom-select tb-group-custom-select',
          id: idPrefix + 'DuplicateGroupCustomSelect'
        });

        var grpTriggerIcon = icon(curGroup ? 'folder2' : 'dash-circle');
        grpTriggerIcon.className += ' tb-custom-select-trigger-icon';

        var grpTriggerLabel = h('span', {
          class: 'tb-custom-select-trigger-label',
          text: curGroup ? curGroup : 'Ungrouped'
        });

        var grpArrow = icon('chevron-down');
        grpArrow.className += ' tb-custom-select-arrow';

        var grpTriggerBtn = h('button', {
          type: 'button',
          class: 'tb-custom-select-trigger',
          'aria-haspopup': 'listbox',
          'aria-expanded': 'false'
        }, [
          h('div', { class: 'tb-custom-select-trigger-left' }, [
            grpTriggerIcon,
            grpTriggerLabel
          ]),
          grpArrow
        ]);

        var grpMenu = h('div', { class: 'tb-custom-select-menu', role: 'listbox' });

        function updateGrpTrigger(val) {
          if (val === '__none__') {
            grpTriggerLabel.textContent = 'Ungrouped';
            grpTriggerIcon.className = 'bi bi-dash-circle tb-custom-select-trigger-icon';
          } else if (val === '__new__') {
            grpTriggerLabel.textContent = '+ Create new group...';
            grpTriggerIcon.className = 'bi bi-plus-circle tb-custom-select-trigger-icon text-accent';
          } else {
            grpTriggerLabel.textContent = val;
            grpTriggerIcon.className = 'bi bi-folder2 tb-custom-select-trigger-icon';
          }

          var items = grpMenu.querySelectorAll('.tb-custom-select-item');
          for (var i = 0; i < items.length; i++) {
            var el = items[i];
            if (el.getAttribute('data-value') === val) {
              el.classList.add('selected');
            } else {
              el.classList.remove('selected');
            }
          }
        }

        function createGrpOptionItem(val, labelText, iconName, isNew) {
          var itemIcon = icon(iconName);
          itemIcon.className += ' tb-custom-select-item-icon';
          var isSel = (val === curGroup) || (!curGroup && val === '__none__');

          var chk = icon('check2');
          chk.className += ' tb-custom-select-check';

          return h('div', {
            class: 'tb-custom-select-item' + (isSel ? ' selected' : '') + (isNew ? ' tb-custom-select-item-new' : ''),
            role: 'option',
            'data-value': val,
            onclick: function (e) {
              if (e && typeof e.stopPropagation === 'function') e.stopPropagation();
              grpSelect.value = val;
              updateGrpTrigger(val);
              closeGrpMenu();

              if (typeof grpSelect.dispatchEvent === 'function' && typeof Event === 'function') {
                grpSelect.dispatchEvent(new Event('change', { bubbles: true }));
              } else if (grpSelect._listeners && grpSelect._listeners['change']) {
                grpSelect._listeners['change'].forEach(function (fn) {
                  fn({ target: grpSelect });
                });
              }
            }
          }, [
            h('div', { class: 'tb-custom-select-item-left' }, [
              itemIcon,
              h('span', { class: 'tb-custom-select-item-label', text: labelText })
            ]),
            h('div', { class: 'tb-custom-select-item-right' }, [
              chk
            ])
          ]);
        }

        groupList.forEach(function (g) {
          grpMenu.appendChild(createGrpOptionItem(g, g, 'folder2', false));
        });

        grpMenu.appendChild(h('div', { class: 'tb-custom-select-divider' }));
        grpMenu.appendChild(createGrpOptionItem('__none__', 'Ungrouped', 'dash-circle', false));
        grpMenu.appendChild(createGrpOptionItem('__new__', '+ Create new group...', 'plus-circle', true));

        function openGrpMenu() {
          var allOpen = (typeof document !== 'undefined' && typeof document.querySelectorAll === 'function')
            ? document.querySelectorAll('.tb-custom-select.is-open')
            : [];
          for (var m = 0; m < allOpen.length; m++) {
            allOpen[m].classList.remove('is-open');
          }
          customGrpWrap.classList.add('is-open');
          grpTriggerBtn.setAttribute('aria-expanded', 'true');
          if (typeof document !== 'undefined' && typeof document.addEventListener === 'function') {
            document.addEventListener('click', onGrpDocClick, true);
          }
        }

        closeGrpMenu = function () {
          customGrpWrap.classList.remove('is-open');
          grpTriggerBtn.setAttribute('aria-expanded', 'false');
          if (typeof document !== 'undefined' && typeof document.removeEventListener === 'function') {
            document.removeEventListener('click', onGrpDocClick, true);
          }
        };

        function toggleGrpMenu() {
          if (customGrpWrap.classList.contains('is-open')) {
            closeGrpMenu();
          } else {
            openGrpMenu();
          }
        }

        function onGrpDocClick(e) {
          if (customGrpWrap.contains && !customGrpWrap.contains(e.target)) {
            closeGrpMenu();
          }
        }

        grpTriggerBtn.addEventListener('click', function (e) {
          if (typeof e.stopPropagation === 'function') e.stopPropagation();
          toggleGrpMenu();
        });

        customGrpWrap.appendChild(grpSelect);
        customGrpWrap.appendChild(grpTriggerBtn);
        customGrpWrap.appendChild(grpMenu);

        var grpGroup = h('div', { class: 'tb-modal-form-group' }, [
          h('label', { class: 'tb-modal-label', text: 'Group' }),
          customGrpWrap,
          newGrpIn
        ]);
        body.appendChild(grpGroup);

      var errDiv = h('div', {
        class: 'tb-error text-danger',
        id: idPrefix + 'DuplicateError',
        style: 'display:none; font-size:.8rem; margin-top:.5rem;'
      });
      body.appendChild(errDiv);

      var cancelBtn = h('button', {
        type: 'button',
        class: 'btn tb-modal-btn tb-modal-btn-cancel',
        id: idPrefix + 'DuplicateCancelBtn',
        text: 'Cancel'
      });
      var confirmBtn = h('button', {
        type: 'button',
        class: 'btn tb-modal-btn tb-modal-btn-primary',
        id: idPrefix + 'DuplicateConfirmBtn'
      }, [
        icon('copy'),
        h('span', { text: ' Duplicate' })
      ]);

      var actions = h('div', { class: 'tb-modal-actions' }, [cancelBtn, confirmBtn]);

      card.appendChild(header);
      card.appendChild(body);
      card.appendChild(actions);
      backdrop.appendChild(card);

      function cleanup() {
        if (typeof closeGrpMenu === 'function') closeGrpMenu();
        document.removeEventListener('keydown', onKeyDown);
        backdrop.classList.add('closing');
        setTimeout(function () {
          if (backdrop.parentNode) backdrop.parentNode.removeChild(backdrop);
        }, 150);
      }

      function submit() {
        var newId = (idIn.value || '').trim();
        var rawName = nameIn ? (nameIn.value || '').trim() : '';
        var newName = rawName || newId;

        if (!newId) {
          errDiv.textContent = 'Configuration ID is required.';
          errDiv.style.display = '';
          idIn.focus();
          return;
        }
        if (existingIds.some(function (x) { return x.toLowerCase() === newId.toLowerCase(); })) {
          errDiv.textContent = 'A configuration with ID "' + newId + '" already exists.';
          errDiv.style.display = '';
          idIn.focus();
          return;
        }

        var targetGroup = null;
        if (grpSelect) {
          if (grpSelect.value === '__src__') targetGroup = curGroup;
          else if (grpSelect.value === '__none__') targetGroup = null;
          else if (grpSelect.value === '__new__') targetGroup = (newGrpIn.value || '').trim();
          else targetGroup = grpSelect.value;
        }

        cleanup();

        var dupCall = (typeof store.duplicate === 'function')
          ? store.duplicate(it.id, newId, newName)
          : Promise.reject(new Error('duplicate not supported'));

        dupCall.then(function (res) {
          if (res && res.ok) {
            if (targetGroup) {
              groupMgr.setGroup(newId, targetGroup);
            }
            renderSide();
            renderMain();
          } else if (res && res.message) {
            Common.setNotice(store.state, 'danger', res.message);
            store.emit();
          }
        }).catch(function (e) {
          Common.setNotice(store.state, 'danger', (e && e.message) || String(e));
          store.emit();
        });
      }

      function onKeyDown(e) {
        if (e.key === 'Escape') {
          e.preventDefault();
          cleanup();
        } else if (e.key === 'Enter') {
          e.preventDefault();
          submit();
        }
      }

      closeBtn.addEventListener('click', cleanup);
      cancelBtn.addEventListener('click', cleanup);
      confirmBtn.addEventListener('click', submit);
      backdrop.addEventListener('click', function (e) {
        if (e.target === backdrop) cleanup();
      });

      document.addEventListener('keydown', onKeyDown);
      document.body.appendChild(backdrop);
      setTimeout(function () {
        try { idIn.focus(); idIn.select(); } catch (e) {}
      }, 50);
    }

    function promptGroup(ids) {
      if (typeof document === 'undefined' || !ids || !ids.length) return;

      var allGroups = groupMgr.getGroupNames();
      var isSingle = (ids.length === 1);
      var singleId = isSingle ? ids[0] : null;
      var curItem = isSingle ? (store.state.list.items.find(function (x) { return x.id === singleId; }) || { id: singleId }) : null;
      var curGroup = isSingle ? groupMgr.getGroup(singleId) : null;

      var backdrop = h('div', {
        class: 'tb-modal-backdrop',
        id: idPrefix + 'GroupModalBackdrop',
        role: 'dialog',
        'aria-modal': 'true'
      });

      var card = h('div', { class: 'tb-modal-card' });
      var iconBox = h('div', { class: 'tb-modal-icon-box tb-modal-icon-primary' }, [icon('folder2')]);
      var closeBtn = h('button', {
        type: 'button',
        class: 'tb-modal-close-btn',
        'aria-label': 'Close'
      }, [icon('x-lg')]);

      var header = h('div', { class: 'tb-modal-header' }, [iconBox, closeBtn]);

      var titleText = isSingle ? 'Assign to Group' : ('Assign ' + ids.length + ' Items to Group');
      var body = h('div', { class: 'tb-modal-body' }, [
        h('h3', { class: 'tb-modal-title', text: titleText }),
        h('p', {
          class: 'tb-modal-message',
          text: isSingle
            ? ('Organize "' + (curItem.name || curItem.id) + '" into a group category.')
            : ('Assign selected ' + ids.length + ' ' + itemLabel + 's to a group category.')
        })
      ]);

      var selectEl = null;
      var inputEl = null;

      if (allGroups.length > 0) {
        selectEl = h('select', {
          class: 'form-select form-select-sm tb-modal-select',
          id: idPrefix + 'GroupSelect'
        });
        selectEl.appendChild(h('option', { value: '' }, ['-- Choose existing group --']));
        allGroups.forEach(function (g) {
          selectEl.appendChild(h('option', { value: g, selected: (curGroup === g) }, [g]));
        });
        selectEl.appendChild(h('option', { value: '__new__' }, ['+ Create new group...']));
        if (curGroup) {
          selectEl.appendChild(h('option', { value: '__none__' }, ['Remove from group']));
        }

        inputEl = h('input', {
          type: 'text',
          class: 'form-control form-control-sm tb-modal-input',
          id: idPrefix + 'NewGroupInput',
          placeholder: 'Or enter new group name (e.g. Production, Testing)',
          style: 'display: none; margin-top: 6px;'
        });

        selectEl.addEventListener('change', function () {
          var isNew = (selectEl.value === '__new__');
          inputEl.style.display = isNew ? '' : 'none';
          if (isNew) {
            inputEl.value = '';
            if (typeof inputEl.focus === 'function') inputEl.focus();
          } else {
            inputEl.value = '';
          }
        });

        body.appendChild(h('div', { class: 'tb-modal-form-group' }, [
          h('label', { class: 'tb-modal-label', text: 'Select Group' }),
          selectEl,
          inputEl
        ]));
      } else {
        inputEl = h('input', {
          type: 'text',
          class: 'form-control form-control-sm tb-modal-input',
          id: idPrefix + 'NewGroupInput',
          placeholder: 'Group name (e.g. Production, Testing, Lab 1)'
        });
        body.appendChild(h('div', { class: 'tb-modal-form-group' }, [
          h('label', { class: 'tb-modal-label', text: 'New Group Name' }),
          inputEl
        ]));
      }

      var cancelBtn = h('button', {
        type: 'button',
        class: 'btn tb-modal-btn tb-modal-btn-cancel',
        id: idPrefix + 'GroupCancelBtn',
        text: 'Cancel'
      });

      var actionBtns = [cancelBtn];

      if (isSingle && curGroup) {
        var ungrpBtn = h('button', {
          type: 'button',
          class: 'btn tb-modal-btn tb-modal-btn-warning',
          id: idPrefix + 'GroupRemoveBtn',
          text: 'Remove from Group'
        });
        ungrpBtn.addEventListener('click', function () {
          cleanup();
          groupMgr.removeGroup(singleId);
          renderSide();
          Common.setNotice(store.state, 'info', 'Removed "' + (curItem.name || curItem.id) + '" from group.');
          store.emit();
        });
        actionBtns.push(ungrpBtn);
      }

      var saveBtn = h('button', {
        type: 'button',
        class: 'btn tb-modal-btn tb-modal-btn-primary',
        id: idPrefix + 'GroupSaveBtn'
      }, [
        icon('check2'),
        h('span', { text: ' Save Group' })
      ]);
      actionBtns.push(saveBtn);

      var actions = h('div', { class: 'tb-modal-actions' }, actionBtns);

      card.appendChild(header);
      card.appendChild(body);
      card.appendChild(actions);
      backdrop.appendChild(card);

      function cleanup() {
        document.removeEventListener('keydown', onKeyDown);
        backdrop.classList.add('closing');
        setTimeout(function () {
          if (backdrop.parentNode) backdrop.parentNode.removeChild(backdrop);
        }, 150);
      }

      function submit() {
        var chosen = '';
        var rawInput = inputEl ? (inputEl.value || '').trim() : '';
        if (rawInput) {
          chosen = rawInput;
        } else if (selectEl) {
          if (selectEl.value === '__none__') {
            chosen = '';
          } else if (selectEl.value && selectEl.value !== '__new__') {
            chosen = selectEl.value;
          }
        }

        cleanup();

        if (chosen) {
          if (typeof groupMgr.addGroup === 'function') groupMgr.addGroup(chosen);
          ids.forEach(function (id) {
            groupMgr.setGroup(id, chosen);
          });
          Common.setNotice(store.state, 'info', isSingle
            ? ('Assigned "' + (curItem.name || curItem.id) + '" to group "' + chosen + '".')
            : ('Assigned ' + ids.length + ' items to group "' + chosen + '".'));
        } else if (selectEl && selectEl.value === '__none__') {
          ids.forEach(function (id) {
            groupMgr.removeGroup(id);
          });
          Common.setNotice(store.state, 'info', isSingle
            ? ('Removed "' + (curItem.name || curItem.id) + '" from group.')
            : ('Removed ' + ids.length + ' items from groups.'));
        }

        if (ui.selectMode) {
          ui.selectMode = false;
          ui.selectedIds = [];
        }
        renderSide();
        store.emit();
      }

      function onKeyDown(e) {
        if (e.key === 'Escape') {
          e.preventDefault();
          cleanup();
        } else if (e.key === 'Enter') {
          e.preventDefault();
          submit();
        }
      }

      closeBtn.addEventListener('click', cleanup);
      cancelBtn.addEventListener('click', cleanup);
      saveBtn.addEventListener('click', submit);
      backdrop.addEventListener('click', function (e) {
        if (e.target === backdrop) cleanup();
      });

      document.addEventListener('keydown', onKeyDown);
      document.body.appendChild(backdrop);
      setTimeout(function () {
        try {
          if (inputEl) inputEl.focus();
          else if (selectEl) selectEl.focus();
        } catch (e) {}
      }, 50);
    }

    function live(fn) {
      typing = true;
      try { fn(); } finally { typing = false; }
    }

    function isChanged() {
      if (typeof spec.isDirty === 'function') return spec.isDirty(store);
      if (!store) return false;
      if (typeof store.isDirty === 'function') return store.isDirty();
      if (typeof store.isChanged === 'function') return store.isChanged();
      return false;
    }

    function confirmLeave() {
      return Common.confirmLeave(isChanged(), itemLabel);
    }

    function openItem(id) {
      if (store.state.current && store.state.current.id === id && !store.state.current.readOnly) return;
      if (isChanged()) {
        Common.confirmModal({
          title: 'Discard Changes',
          message: 'You have unsaved changes in this ' + itemLabel + '. Do you want to discard them?',
          confirmText: 'Discard Changes',
          confirmVariant: 'warning',
          icon: 'exclamation-triangle'
        }).then(function (discard) {
          if (!discard) return;
          ui.searchOpen = false;
          if (typeof spec.onBeforeOpen === 'function') spec.onBeforeOpen(ui);
          store.open(id);
        });
        return;
      }
      ui.searchOpen = false;
      if (typeof spec.onBeforeOpen === 'function') spec.onBeforeOpen(ui);
      store.open(id);
    }

    // -------------------------------------------------------- Sidebar Rendering
    function renderSide() {
      if (!sideEl) return;
      var st = store.state;
      sideEl.textContent = '';

      var existingMap = {};
      (st.list.items || []).forEach(function (x) { existingMap[x.id] = true; });
      ui.selectedIds = (ui.selectedIds || []).filter(function (id) { return existingMap[id]; });

      function deleteSelected() {
        var ids = ui.selectedIds.slice();
        if (!ids.length) return;
        var count = ids.length;
        var titleText = count === 1 ? ('Delete ' + itemLabel) : ('Delete ' + count + ' ' + itemLabel + 's');
        var promptText = count === 1
          ? ('Are you sure you want to delete ' + itemLabel + ' "' + ids[0] + '"? This action cannot be undone.')
          : ('Are you sure you want to delete ' + count + ' ' + itemLabel + 's? This action cannot be undone.');

        Common.confirmModal({
          title: titleText,
          message: promptText,
          items: ids,
          confirmText: 'Delete' + (count > 1 ? (' (' + count + ')') : ''),
          confirmVariant: 'danger',
          icon: 'trash3'
        }).then(function (confirmed) {
          if (!confirmed) return;
          var chain = Promise.resolve();
          ids.forEach(function (id) {
            chain = chain.then(function () {
              return store.deleteItem(id);
            });
          });
          chain.then(function () {
            ids.forEach(function (id) { groupMgr.removeGroup(id); });
            ui.selectedIds = [];
            ui.selectMode = false;
            renderSide();
            renderMain();
          }).catch(function () {
            ids.forEach(function (id) { groupMgr.removeGroup(id); });
            ui.selectedIds = [];
            renderSide();
            renderMain();
          });
        });
      }

      function toggleSelect(id) {
        var idx = ui.selectedIds.indexOf(id);
        if (idx >= 0) {
          ui.selectedIds.splice(idx, 1);
        } else {
          ui.selectedIds.push(id);
        }
        renderSide();
      }

      function toggleSelectAll() {
        if (ui.selectedIds.length === st.list.items.length && st.list.items.length > 0) {
          ui.selectedIds = [];
        } else {
          ui.selectedIds = st.list.items.map(function (x) { return x.id; });
        }
        renderSide();
      }

      var hasItems = st.list.items && st.list.items.length > 0;

      var head = h('div', { class: 'tb-side-head' }, [
        icon(iconName),
        h('span', { class: 'tb-side-title', text: title }),
        h('button', {
          type: 'button',
          class: 'btn btn-sm tb-icon-btn tb-select-toggle-btn' + (ui.selectMode ? ' active' : ''),
          id: idPrefix + 'SelectToggleBtn',
          title: ui.selectMode ? 'Close selection' : 'Select items',
          disabled: !hasItems,
          onclick: function () {
            ui.selectMode = !ui.selectMode;
            if (!ui.selectMode) ui.selectedIds = [];
            renderSide();
          }
        }, [icon('check2-square')]),
        h('button', {
          type: 'button', class: 'btn btn-sm tb-icon-btn', id: idPrefix + 'RefreshList',
          title: 'Reload the list',
          onclick: function () { store.loadList(); }
        }, [icon('arrow-clockwise')]),
        h('button', {
          type: 'button', class: 'btn btn-sm tb-icon-btn' + (ui.creatingGroup ? ' active' : ''),
          id: idPrefix + 'NewGroupBtn',
          title: ui.creatingGroup ? 'Cancel new group' : 'Create new group',
          onclick: function () {
            ui.creatingGroup = !ui.creatingGroup;
            ui.creating = false;
            ui.newGroupName = '';
            ui.createGroupErr = null;
            renderSide();
          }
        }, [icon('folder-plus')]),
        h('button', {
          type: 'button', class: 'btn btn-sm tb-icon-btn' + (ui.creating ? ' active' : ''),
          id: idPrefix + 'NewBtn',
          title: ui.creating ? ('Cancel new ' + itemLabel) : ('Create new ' + itemLabel),
          onclick: function () {
            ui.creating = !ui.creating;
            ui.creatingGroup = false;
            ui.createErr = null;
            renderSide();
          }
        }, [icon('plus-lg')])
      ]);
      sideEl.appendChild(head);

      if (ui.creatingGroup) {
        var grpIn = h('input', {
          class: 'form-control form-control-sm', id: idPrefix + 'NewGroupName',
          placeholder: 'group name (e.g. Production, Lab 1)', value: ui.newGroupName || '',
          oninput: function (e) { ui.newGroupName = e.target.value; }
        });
        var createGrp = function () {
          var val = String(ui.newGroupName || '').trim();
          if (!val) {
            ui.createGroupErr = 'Group name is required.';
            renderSide();
            return;
          }
          groupMgr.addGroup(val);
          ui.creatingGroup = false;
          ui.newGroupName = '';
          ui.createGroupErr = null;
          renderSide();
        };
        grpIn.addEventListener('keydown', function (e) {
          if (e.key === 'Enter') createGrp();
          else if (e.key === 'Escape') { ui.creatingGroup = false; ui.createGroupErr = null; renderSide(); }
        });
        var grpFields = [grpIn];
        if (ui.createGroupErr) {
          grpFields.push(h('div', { class: 'tb-error', id: idPrefix + 'CreateGroupError', text: ui.createGroupErr }));
        }
        grpFields.push(h('div', { class: 'tb-row' }, [
          btn('Add Group', 'btn-primary', createGrp, { id: idPrefix + 'CreateGroupBtn' }),
          btn('Cancel', 'btn-outline-secondary', function () { ui.creatingGroup = false; ui.createGroupErr = null; renderSide(); })
        ]));
        sideEl.appendChild(h('div', { class: 'tb-create' }, grpFields));
      }

      if (ui.creating) {
        var idIn = h('input', {
          class: 'form-control form-control-sm', id: idPrefix + 'NewId',
          placeholder: spec.idPlaceholder || 'id (e.g. tower_1)', value: ui.newId,
          oninput: function (e) { ui.newId = e.target.value; }
        });

        var nameIn = null;
        if (hasNameInput) {
          nameIn = h('input', {
            class: 'form-control form-control-sm', id: idPrefix + 'NewName',
            placeholder: spec.namePlaceholder || 'name (defaults to ID if not entered)', value: ui.newName,
            oninput: function (e) { ui.newName = e.target.value; }
          });
        }

        var create = function () {
          if (ui.savingNew) return;
          var id = String(ui.newId || '').trim();
          var rawName = hasNameInput ? String(ui.newName || '').trim() : '';
          var name = rawName || id;

          function handleResult(r) {
            ui.savingNew = false;
            if (r && r.ok) {
              ui.creating = false; ui.newId = ''; ui.newName = ''; ui.createErr = null;
            } else if (r && (r.message || (r.error && r.error.message))) {
              ui.createErr = r.message || (r.error && r.error.message);
            }
            renderSide();
            renderMain();
          }

          ui.savingNew = true;
          renderSide();

          if (typeof spec.onCreate === 'function') {
            var r = spec.onCreate(store, id, name, ui);
            if (r && typeof r.then === 'function') {
              r.then(handleResult).catch(function (err) {
                ui.savingNew = false;
                ui.createErr = (err && err.message) || String(err);
                renderSide();
                renderMain();
              });
              return;
            }
            handleResult(r);
          } else {
            var res = store.createNew ? store.createNew(id, name) : { ok: true };
            if (res && typeof res.then === 'function') {
              res.then(handleResult).catch(function (err) {
                ui.savingNew = false;
                ui.createErr = (err && err.message) || String(err);
                renderSide();
                renderMain();
              });
              return;
            }
            if (res && res.ok && store.save) {
              var sRes = store.save();
              if (sRes && typeof sRes.then === 'function') {
                sRes.then(function (sr) {
                  ui.savingNew = false;
                  if (sr && sr.ok === false) {
                    ui.createErr = (sr.error && sr.error.message) || 'Failed to save';
                  } else {
                    ui.creating = false; ui.newId = ''; ui.newName = ''; ui.createErr = null;
                  }
                  renderSide();
                  renderMain();
                }).catch(function (err) {
                  ui.savingNew = false;
                  ui.createErr = (err && err.message) || String(err);
                  renderSide();
                  renderMain();
                });
                return;
              }
            }
            handleResult(res);
          }
        };

        var inputs = [idIn];
        if (nameIn) inputs.push(nameIn);
        inputs.forEach(function (i) {
          i.addEventListener('keydown', function (e) { if (e.key === 'Enter') create(); });
        });

        var createFields = inputs.slice();
        if (ui.createErr) {
          createFields.push(h('div', { class: 'tb-error', id: idPrefix + 'CreateError', text: ui.createErr }));
        }
        createFields.push(h('div', { class: 'tb-row' }, [
          btn(ui.savingNew ? 'Creating...' : 'Create', 'btn-primary' + (ui.savingNew ? ' disabled' : ''), create, { id: idPrefix + 'CreateBtn' }),
          btn('Cancel', 'btn-outline-secondary', function () { ui.creating = false; ui.savingNew = false; ui.createErr = null; renderSide(); })
        ]));

        sideEl.appendChild(h('div', { class: 'tb-create' }, createFields));
      }

      sideEl.appendChild(renderSearchDropdown());

      if (ui.selectMode) {
        var allChecked = st.list.items.length > 0 && ui.selectedIds.length === st.list.items.length;
        var hasSelected = ui.selectedIds.length > 0;
        var selBar = h('div', { class: 'tb-selection-bar', id: idPrefix + 'SelectionBar' }, [
          h('div', { class: 'tb-selection-row tb-selection-header-row' }, [
            h('label', { class: 'tb-selection-left' }, [
              h('input', {
                type: 'checkbox', class: 'form-check-input tb-check-all',
                checked: allChecked,
                title: allChecked ? 'Deselect all' : 'Select all',
                onchange: function () { toggleSelectAll(); }
              }),
              h('span', { class: 'tb-selection-label', text: 'Select all' })
            ]),
            h('span', { class: 'tb-selection-count', text: ui.selectedIds.length + ' selected' })
          ]),
          h('div', { class: 'tb-selection-row tb-selection-actions-row' }, [
            h('button', {
              type: 'button',
              class: 'tb-batch-btn tb-batch-group-btn' + (!hasSelected ? ' disabled' : ''),
              id: idPrefix + 'BatchGroupBtn',
              disabled: !hasSelected,
              title: hasSelected ? ('Assign ' + ui.selectedIds.length + ' selected ' + itemLabel + (ui.selectedIds.length > 1 ? 's' : '') + ' to a group') : 'Select items to group',
              onclick: function () { if (hasSelected) promptGroup(ui.selectedIds); }
            }, [
              icon('folder2'),
              h('span', { text: 'Group' })
            ]),
            h('button', {
              type: 'button',
              class: 'tb-batch-btn tb-batch-del-btn' + (!hasSelected ? ' disabled' : ''),
              id: idPrefix + 'BatchDeleteBtn',
              disabled: !hasSelected,
              title: hasSelected ? ('Delete ' + ui.selectedIds.length + ' selected ' + itemLabel + (ui.selectedIds.length > 1 ? 's' : '')) : 'Select items to delete',
              onclick: function () { if (hasSelected) deleteSelected(); }
            }, [
              icon('trash3'),
              h('span', { text: 'Delete' })
            ]),
            h('button', {
              type: 'button',
              class: 'tb-batch-btn tb-batch-cancel-btn',
              id: idPrefix + 'BatchCancelBtn',
              title: 'Close selection',
              onclick: function () { ui.selectMode = false; ui.selectedIds = []; renderSide(); }
            }, [
              icon('x-lg'),
              h('span', { text: 'Cancel' })
            ])
          ])
        ]);
        sideEl.appendChild(selBar);
      }

      var body = h('div', {
        class: 'tb-list' + (ui.selectMode ? ' in-select-mode' : ''),
        id: idPrefix + 'List'
      });
      var allKnownGroups = groupMgr.getGroupNames();
      if (st.list.status === 'loading' && !st.list.items.length) {
        body.appendChild(h('div', { class: 'tb-empty', text: 'Loading…' }));
      } else if (st.list.status === 'error') {
        body.appendChild(h('div', {
          class: 'tb-empty tb-empty-error', id: idPrefix + 'ListError',
          text: st.list.error || ('Could not load ' + itemLabel + 's')
        }));
      } else if (!st.list.items.length && (!allKnownGroups || allKnownGroups.length === 0)) {
        body.appendChild(h('div', { class: 'tb-empty', id: idPrefix + 'EmptyState' }, [
          icon(spec.emptyIcon || 'inbox'),
          h('div', { text: emptyTitle }),
          h('div', { class: 'tb-muted', text: emptySubtext })
        ]));
      } else {
        function createItemEl(it) {
          var active = st.current && st.current.id === it.id;
          var isSelected = ui.selectedIds.indexOf(it.id) >= 0;

          var curVer = (active && st.current && !st.current.readOnly && st.current.version !== undefined && st.current.version !== null)
            ? st.current.version
            : (it.activeVersion !== undefined && it.activeVersion !== null
                ? it.activeVersion
                : (typeof store.getActiveVersion === 'function' ? store.getActiveVersion(it.id) : undefined));
          if (curVer === undefined || curVer === null) {
            curVer = it.latestVersion;
          }

          var isNew = it.isNew || curVer === 'new';
          var isDefault = it.isDefault || curVer === 0 || curVer === '0 (default)';
          var verText = isNew ? 'new'
                      : (isDefault ? 'v0 (default)'
                      : (typeof curVer === 'number' ? 'v' + curVer : (String(curVer).indexOf('v') === 0 ? curVer : 'v' + curVer)));
          var verClass = (isNew || isDefault) ? 'tb-badge-default' : 'tb-ver';

          var itemKids = [];

          if (ui.selectMode) {
            var check = h('input', {
              type: 'checkbox',
              class: 'form-check-input tb-item-check',
              checked: isSelected,
              title: 'Select ' + (it.name || it.id),
              'aria-label': 'Select ' + (it.name || it.id),
              onclick: function (e) {
                e.stopPropagation();
                toggleSelect(it.id);
              }
            });
            itemKids.push(check);
          }

          itemKids.push(h('div', { class: 'tb-item-info' }, [
            h('span', { class: 'tb-item-name', text: it.name || it.id, title: 'Name: ' + (it.name || it.id) }),
            h('span', { class: 'tb-item-id', text: it.id, title: 'ID: ' + it.id })
          ]));

          itemKids.push(h('span', { class: 'badge ' + verClass, text: verText }));

          var optBtn = h('button', {
            type: 'button',
            class: 'btn tb-item-opt-btn' + (ui.activeMenuId === it.id ? ' active' : ''),
            id: idPrefix + 'OptBtn_' + it.id,
            title: 'More options for ' + (it.name || it.id),
            'aria-label': 'More options for ' + (it.name || it.id),
            onclick: function (e) {
              e.stopPropagation();
              e.preventDefault();
              toggleItemMenu(it, optBtn);
            }
          }, [
            icon('three-dots-vertical')
          ]);
          itemKids.push(optBtn);

          var item = h('div', {
            class: 'tb-item' + (active ? ' active' : '') + (isSelected ? ' selected' : '') + (ui.selectMode ? ' in-select-mode' : ''),
            'data-id': it.id, role: 'button', tabindex: '0',
            onclick: function (e) {
              if (ui.selectMode) {
                toggleSelect(it.id);
                return;
              }
              if (e.ctrlKey || e.metaKey) {
                ui.selectMode = true;
                toggleSelect(it.id);
                return;
              }
              openItem(it.id);
            },
            onkeydown: function (e) {
              if (e.key === 'Enter') {
                if (ui.selectMode) toggleSelect(it.id);
                else openItem(it.id);
              }
            }
          }, itemKids);
          return item;
        }

        var allItems = st.list.items || [];
        var groups = groupMgr.getAll();
        allKnownGroups = groupMgr.getGroupNames();

        var displayItems = allItems;
        if (ui.searchQuery && ui.searchQuery.trim()) {
          var q = ui.searchQuery.trim().toLowerCase();
          displayItems = allItems.filter(function (x) {
            var n = (x.name || '').toLowerCase();
            var i = (x.id || '').toLowerCase();
            var g = (groups[x.id] || '').toLowerCase();
            return n.indexOf(q) >= 0 || i.indexOf(q) >= 0 || g.indexOf(q) >= 0;
          });
        }

        var groupMap = {};
        allKnownGroups.forEach(function (g) {
          if (!ui.searchQuery || !ui.searchQuery.trim() || g.toLowerCase().indexOf(ui.searchQuery.trim().toLowerCase()) >= 0) {
            groupMap[g] = [];
          }
        });
        var ungroupedList = [];
        displayItems.forEach(function (it) {
          var grp = groups[it.id];
          if (grp) {
            if (!groupMap[grp]) groupMap[grp] = [];
            groupMap[grp].push(it);
          } else {
            ungroupedList.push(it);
          }
        });

        var groupNames = Object.keys(groupMap).sort(function (a, b) {
          var comp = a.localeCompare(b, undefined, { numeric: true, sensitivity: 'base' });
          return (ui.groupsOrder === 'desc') ? -comp : comp;
        });
        groupNames.forEach(function (groupName) {
          var itemsInGroup = groupMap[groupName];
          var isCollapsed = !!ui.collapsedGroups[groupName];
          var safeGrpId = groupName.replace(/\s+/g, '_');

          var groupSec = h('div', {
            class: 'tb-group-section' + (itemsInGroup.length === 0 ? ' is-empty' : ''),
            'data-group': groupName
          });

          var groupOptBtn = h('span', {
            class: 'tb-group-action-btn tb-group-opt-btn' + (ui.activeGroupMenu === groupName ? ' active' : ''),
            id: idPrefix + 'GroupOptBtn_' + safeGrpId,
            role: 'button',
            tabindex: '0',
            title: 'Group options for ' + groupName,
            'aria-label': 'Group options for ' + groupName,
            onclick: function (e) {
              e.stopPropagation();
              e.preventDefault();
              toggleGroupMenu(groupName, itemsInGroup, groupOptBtn);
            },
            onkeydown: function (e) {
              if (e.key === 'Enter' || e.key === ' ') {
                e.stopPropagation();
                e.preventDefault();
                toggleGroupMenu(groupName, itemsInGroup, groupOptBtn);
              }
            }
          }, [icon('three-dots-vertical')]);

          var groupHead = h('button', {
            type: 'button',
            class: 'tb-group-header' + (isCollapsed ? ' collapsed' : ''),
            id: idPrefix + 'GroupHeader_' + safeGrpId,
            title: (isCollapsed ? 'Expand ' : 'Collapse ') + groupName,
            onclick: function (e) {
              e.stopPropagation();
              ui.collapsedGroups[groupName] = !ui.collapsedGroups[groupName];
              saveCollapsedGroups(ui.collapsedGroups);
              renderSide();
            }
          }, [
            icon(isCollapsed ? 'chevron-right' : 'chevron-down'),
            icon(isCollapsed ? 'folder2' : 'folder2-open'),
            h('span', { class: 'tb-group-title', text: groupName }),
            h('span', { class: 'badge tb-group-badge', text: String(itemsInGroup.length) }),
            groupOptBtn
          ]);

          var groupItems = h('div', {
            class: 'tb-group-items' + (isCollapsed ? ' collapsed' : '')
          });
          var sortedGroupItems = sortItemsList(itemsInGroup, ui.groupSort && ui.groupSort[groupName]);
          if (sortedGroupItems.length === 0) {
            groupItems.appendChild(h('div', {
              class: 'tb-group-empty-hint',
              text: 'No items in this group'
            }));
          } else {
            sortedGroupItems.forEach(function (it) {
              groupItems.appendChild(createItemEl(it));
            });
          }

          groupSec.appendChild(groupHead);
          groupSec.appendChild(groupItems);
          body.appendChild(groupSec);
        });

        if (ungroupedList.length > 0) {
          var isUnCollapsed = !!ui.collapsedGroups['__ungrouped__'];
          var unSec = h('div', {
            class: 'tb-group-section tb-ungrouped-section',
            'data-group': '__ungrouped__'
          });

          var unOptBtn = h('span', {
            class: 'tb-group-action-btn tb-group-opt-btn' + (ui.activeGroupMenu === '__ungrouped__' ? ' active' : ''),
            id: idPrefix + 'GroupOptBtn_Ungrouped',
            role: 'button',
            tabindex: '0',
            title: 'Options for ungrouped items',
            'aria-label': 'Options for ungrouped items',
            onclick: function (e) {
              e.stopPropagation();
              e.preventDefault();
              toggleGroupMenu('__ungrouped__', ungroupedList, unOptBtn);
            },
            onkeydown: function (e) {
              if (e.key === 'Enter' || e.key === ' ') {
                e.stopPropagation();
                e.preventDefault();
                toggleGroupMenu('__ungrouped__', ungroupedList, unOptBtn);
              }
            }
          }, [icon('three-dots-vertical')]);

          var unHead = h('button', {
            type: 'button',
            class: 'tb-group-header' + (isUnCollapsed ? ' collapsed' : ''),
            id: idPrefix + 'GroupHeader_Ungrouped',
            title: (isUnCollapsed ? 'Expand ' : 'Collapse ') + 'ungrouped items',
            onclick: function (e) {
              e.stopPropagation();
              ui.collapsedGroups['__ungrouped__'] = !ui.collapsedGroups['__ungrouped__'];
              saveCollapsedGroups(ui.collapsedGroups);
              renderSide();
            }
          }, [
            icon(isUnCollapsed ? 'chevron-right' : 'chevron-down'),
            icon('inbox'),
            h('span', { class: 'tb-group-title', text: 'Ungrouped' }),
            h('span', { class: 'badge tb-group-badge', text: String(ungroupedList.length) }),
            unOptBtn
          ]);

          var unItems = h('div', {
            class: 'tb-group-items' + (isUnCollapsed ? ' collapsed' : '')
          });
          var sortedUngrouped = sortItemsList(ungroupedList, ui.groupSort && ui.groupSort['__ungrouped__']);
          sortedUngrouped.forEach(function (it) {
            unItems.appendChild(createItemEl(it));
          });

          unSec.appendChild(unHead);
          unSec.appendChild(unItems);
          body.appendChild(unSec);
        }

        if (groupNames.length === 0 && ungroupedList.length === 0) {
          if (ui.searchQuery && ui.searchQuery.trim()) {
            body.appendChild(h('div', { class: 'tb-empty', text: 'No matching ' + itemLabel + 's or groups' }));
          } else {
            body.appendChild(h('div', { class: 'tb-empty', id: idPrefix + 'EmptyState' }, [
              icon(spec.emptyIcon || 'inbox'),
              h('div', { text: emptyTitle }),
              h('div', { class: 'tb-muted', text: emptySubtext })
            ]));
          }
        }
      }
      sideEl.appendChild(body);
    }

    var docListenersAttached = false;
    function onOutsideClick(e) {
      if (!ui.searchOpen) return;
      var curBox = (typeof document !== 'undefined' && typeof document.getElementById === 'function')
        ? document.getElementById(idPrefix + 'SearchBox')
        : null;
      if (curBox && curBox.contains && curBox.contains(e.target)) {
        return;
      }
      ui.searchOpen = false;
      if (curBox) {
        renderDropdownMenu(curBox);
      } else if (typeof document !== 'undefined' && typeof document.getElementById === 'function') {
        var menu = document.getElementById(idPrefix + 'DropdownMenu');
        if (menu && menu.remove) menu.remove();
      }
    }

    function ensureDocListeners() {
      if (docListenersAttached || typeof document === 'undefined') return;
      if (typeof document.addEventListener === 'function') {
        document.addEventListener('pointerdown', onOutsideClick, true);
        document.addEventListener('click', onOutsideClick, true);
      }
      if (typeof window !== 'undefined' && typeof window.addEventListener === 'function') {
        window.addEventListener('blur', function () {
          if (ui.searchOpen) {
            ui.searchOpen = false;
            var curBox = (typeof document !== 'undefined' && typeof document.getElementById === 'function')
              ? document.getElementById(idPrefix + 'SearchBox')
              : null;
            if (curBox) renderDropdownMenu(curBox);
          }
        });
      }
      docListenersAttached = true;
    }

    function renderSearchDropdown() {
      ensureDocListeners();
      var box = h('div', { class: 'tb-search-box', id: idPrefix + 'SearchBox' });
      var input = h('input', {
        type: 'text', class: 'form-control form-control-sm tb-search-input', id: idPrefix + 'SearchInput',
        placeholder: searchPlaceholder,
        value: ui.searchQuery,
        autocomplete: 'off',
        onfocus: function () { ui.searchOpen = true; renderDropdownMenu(box); },
        oninput: function (e) {
          ui.searchQuery = e.target.value;
          ui.searchOpen = true;
          renderDropdownMenu(box);
        },
        onkeydown: function (e) {
          if (e.key === 'Enter') {
            var q = ui.searchQuery.trim();
            if (q) {
              ui.searchOpen = false;
              var exists = store.state.list.items.some(function (it) { return it.id.toLowerCase() === q.toLowerCase(); });
              if (exists) {
                openItem(q);
              } else {
                var done = function () {
                  ui.searchQuery = '';
                  renderSide();
                  renderMain();
                };
                if (typeof spec.onCreate === 'function') {
                  var p = spec.onCreate(store, q, q, ui);
                  if (p && typeof p.then === 'function') {
                    p.then(done).catch(done);
                    return;
                  }
                } else if (store.createNew) {
                  var cr = store.createNew(q, q);
                  if (cr && cr.ok && store.save) {
                    store.save().then(done).catch(done);
                    return;
                  }
                } else {
                  store.open(q);
                }
                done();
              }
            }
          } else if (e.key === 'Escape') {
            ui.searchOpen = false;
            renderDropdownMenu(box);
          }
        }
      });

      box.appendChild(input);

      renderDropdownMenu(box);
      return box;
    }

    function renderDropdownMenu(box) {
      var existing = box.querySelector('.tb-dropdown-menu');
      if (existing) existing.remove();
      if (!ui.searchOpen) return;

      var menu = h('div', { class: 'tb-dropdown-menu', id: idPrefix + 'DropdownMenu' });
      var q = ui.searchQuery.trim().toLowerCase();
      var st = store.state;

      var matchedSaved = st.list.items.filter(function (it) {
        if (typeof spec.filterItem === 'function') return spec.filterItem(it, q);
        return !q || it.id.toLowerCase().indexOf(q) !== -1 || (it.name && it.name.toLowerCase().indexOf(q) !== -1);
      });

      var savedIds = {};
      st.list.items.forEach(function (it) { savedIds[it.id.toLowerCase()] = true; });

      var hasItems = false;
      if (matchedSaved.length) {
        hasItems = true;
        menu.appendChild(h('div', { class: 'tb-dropdown-header', text: 'Configured ' + title }));
        matchedSaved.forEach(function (it) {
          var active = st.current && st.current.id === it.id;
          var curVer = (active && st.current && !st.current.readOnly && st.current.version !== undefined && st.current.version !== null)
            ? st.current.version
            : (it.activeVersion !== undefined && it.activeVersion !== null
                ? it.activeVersion
                : (typeof store.getActiveVersion === 'function' ? store.getActiveVersion(it.id) : undefined));
          if (curVer === undefined || curVer === null) {
            curVer = it.latestVersion;
          }

          var isNew = it.isNew || curVer === 'new';
          var isDefault = it.isDefault || curVer === 0 || curVer === '0 (default)';
          var verText = isNew ? 'new'
                      : (isDefault ? 'v0 (default)'
                      : (typeof curVer === 'number' ? 'v' + curVer : (String(curVer).indexOf('v') === 0 ? curVer : 'v' + curVer)));
          var verClass = (isNew || isDefault) ? 'badge tb-badge-default' : 'badge tb-ver';

          menu.appendChild(h('button', {
            type: 'button', class: 'tb-dropdown-item', 'data-id': it.id,
            onclick: function () {
              ui.searchOpen = false;
              ui.searchQuery = '';
              openItem(it.id);
            }
          }, [
            h('span', { text: it.name && it.name !== it.id ? it.name + ' (' + it.id + ')' : it.id }),
            h('span', { class: verClass, text: verText })
          ]));
        });
      }

      if (q && !savedIds[q]) {
        hasItems = true;
        menu.appendChild(h('button', {
          type: 'button', class: 'tb-dropdown-item tb-item-new',
          onclick: function () {
            var targetId = ui.searchQuery.trim();
            ui.searchOpen = false;
            var done = function () {
              ui.searchQuery = '';
              renderSide();
              renderMain();
            };
            if (typeof spec.onCreate === 'function') {
              var p2 = spec.onCreate(store, targetId, targetId, ui);
              if (p2 && typeof p2.then === 'function') {
                p2.then(done).catch(done);
                return;
              }
            } else if (store.createNew) {
              var cr2 = store.createNew(targetId, targetId);
              if (cr2 && cr2.ok && store.save) {
                store.save().then(done).catch(done);
                return;
              }
            } else {
              store.open(targetId);
            }
            done();
          }
        }, [
          h('span', { text: '+ Create "' + ui.searchQuery.trim() + '"' }),
          h('span', { class: 'badge tb-badge-default', text: 'new' })
        ]));
      }

      if (!hasItems) {
        menu.appendChild(h('div', { class: 'tb-dropdown-empty', text: 'No matching ' + itemLabel + 's.' }));
      }

      box.appendChild(menu);
    }

    // -------------------------------------------------------- Main Editor Rendering
    function renderMain() {
      if (!mainEl) return;
      var st = store.state;
      mainEl.textContent = '';
      var wrap = h('div', { class: 'tb-main' });
      mainEl.appendChild(wrap);

      if (st.failure) {
        wrap.appendChild(h('div', { class: 'alert alert-danger tb-banner', id: idPrefix + 'Failure', role: 'alert' }, [
          icon('exclamation-octagon'),
          h('span', { text: ' ' + serviceLabel(st.failure.service) + ' failed: ' + st.failure.message + ' ' }),
          st.failure.canRetry ? btn('Retry', 'btn-outline-danger', function () { store.retry(); }, { id: idPrefix + 'Retry' }) : null
        ]));
      }

      // Render toast notification in floating stack at bottom-right (VS Code IDE style)
      if (typeof document !== 'undefined') {
        var noticeId = idPrefix + 'Notice';
        var existingToast = document.getElementById(noticeId);
        if (st.notice) {
          var isSame = existingToast &&
                       existingToast.dataset &&
                       existingToast.dataset.text === st.notice.text &&
                       existingToast.dataset.kind === st.notice.kind &&
                       !existingToast.classList.contains('tb-toast-exit');
          if (!isSame) {
            if (existingToast && existingToast.parentNode) {
              existingToast.parentNode.removeChild(existingToast);
            }
            var stack = document.getElementById('tbNoticeStack');
            if (!stack) {
              stack = h('div', {
                id: 'tbNoticeStack',
                class: 'tb-notice-stack',
                role: 'region',
                'aria-label': 'Notifications'
              });
              document.body.appendChild(stack);
            }
            var toast = (Common.renderToastNotice || Common.renderBannerNotice)(st.notice, function () {
              store.dismissNotice();
            }, noticeId);
            if (toast && stack) {
              stack.appendChild(toast);
            }
          }
        } else if (existingToast && !existingToast.classList.contains('tb-toast-exit')) {
          if (typeof Common.dismissToast === 'function') {
            Common.dismissToast(existingToast);
          } else if (existingToast.parentNode) {
            existingToast.parentNode.removeChild(existingToast);
          }
        }
      }

      var cur = st.current;
      if (!cur) {
        wrap.appendChild(h('div', { class: 'tb-placeholder' }, [
          icon(iconName),
          h('div', { text: spec.placeholderText || ('Select a ' + itemLabel + ', or create one with +') })
        ]));
        return;
      }

      wrap.appendChild(h('div', { class: 'tb-errsum', id: idPrefix + 'ErrorSummary' }));
      wrap.appendChild(Common.renderVersionBar({
        cur: cur,
        store: store,
        confirmLeave: confirmLeave,
        isChanged: isChanged,
        itemLabel: itemLabel,
        idPrefix: idPrefix,
        live: live
      }));

      var ctx = {
        h: h,
        icon: icon,
        btn: btn,
        section: section,
        live: live,
        store: store,
        ui: ui,
        renderMain: renderMain,
        renderSide: renderSide,
        openItem: openItem
      };

      if (typeof spec.renderCard === 'function') {
        wrap.appendChild(spec.renderCard(cur, ctx));
      }

      updateLive();
    }

    // -------------------------------------------------------- Live Updates
    function updateLive() {
      if (!mainEl || !store.state.current) return;
      var cur = store.state.current;
      var v = store.validate();

      var idIn = mainEl.querySelector('#' + idPrefix + 'IdInput');
      if (idIn && idIn.readOnly && idIn.value !== cur.id) {
        idIn.value = cur.id || '';
      }
      var nameIn = mainEl.querySelector('#' + idPrefix + 'NameInput');
      var expectedName = cur.name !== undefined ? cur.name : (cur.id || '');
      if (nameIn && nameIn.readOnly && nameIn.value !== expectedName) {
        nameIn.value = expectedName;
      }

      var ctx = {
        h: h,
        icon: icon,
        btn: btn,
        store: store,
        ui: ui,
        mainEl: mainEl
      };

      if (typeof spec.onUpdateLive === 'function') {
        spec.onUpdateLive(cur, v, ctx);
      }

      var sum = mainEl.querySelector('#' + idPrefix + 'ErrorSummary');
      if (sum && !spec.customErrorSummary) {
        sum.textContent = '';
        if (!v.ok && !cur.readOnly) {
          var errList = Array.isArray(v.list)
            ? v.list.map(function (e) { return e.message; })
            : (v.errors ? Object.keys(v.errors).map(function (k) { return v.errors[k]; }) : []);
          sum.appendChild(h('div', { class: 'alert alert-warning tb-banner' }, [
            h('strong', { text: 'Cannot save yet: ' }),
            h('ul', {}, errList.map(function (msg) { return h('li', { text: msg }); }))
          ]));
        }
        if (cur.saveError && !cur.readOnly) {
          sum.appendChild(h('div', { class: 'alert alert-danger tb-banner', id: idPrefix + 'SaveError', role: 'alert' }, [
            h('strong', { text: cur.saveError.code === 'UNAVAILABLE' ? 'Configuration Hub unavailable. ' : 'Save failed. ' }),
            h('span', { text: cur.saveError.code === 'UNAVAILABLE'
              ? 'Your input is kept; retry when the hub is back.' : cur.saveError.message })
          ]));
        }
        if (cur.catalogChanged) {
          sum.appendChild(h('div', { class: 'alert alert-info tb-banner', id: idPrefix + 'CatalogChanged' },
            ['The catalog changed since this testbench was saved. Devices are shown as saved.']));
        }
      }

      var status = mainEl.querySelector('#' + idPrefix + 'Status');
      if (status && !spec.customStatus) {
        var dirty = isChanged();
        status.className = 'tb-status ' + (cur.readOnly ? 'ro' : (cur.isNew ? 'new' : (cur.isDefault ? 'new' : (dirty ? 'dirty' : 'clean'))));
        status.textContent = cur.readOnly ? ('Viewing v' + (cur.viewingVersion || cur.version))
                           : (cur.isNew ? 'Not saved yet'
                           : (cur.isDefault ? 'Provider default'
                           : (dirty ? 'Unsaved changes' : 'All changes saved')));
      }

      var save = mainEl.querySelector('#' + idPrefix + 'Save');
      if (save && !spec.customSaveButton) {
        save.disabled = !store.canSave();
        save.textContent = cur.saving ? 'Saving…'
                         : (cur.isNew ? ('Create ' + itemLabel)
                         : (cur.isDefault ? ('Save infrastructure (creates v1)')
                         : 'Save new version'));
      }
    }

    function onChange() {
      if (typing) { updateLive(); return; }
      renderSide();
      renderMain();
      if (MM.testbenchConfig) MM.testbenchConfig.updateCounts();
    }

    function init() {
      if (store) return;
      ensureDocListeners();
      if (typeof document !== 'undefined') {
        sideEl = document.getElementById(sidePaneId) || (fallbackSideId ? document.getElementById(fallbackSideId) : null);
        mainEl = document.getElementById(contentId);
      }
      if (typeof spec.createStore === 'function') {
        store = spec.createStore();
      }
      if (typeof spec.onStoreCreated === 'function') {
        spec.onStoreCreated(store);
      }
      if (store && typeof store.subscribe === 'function') {
        store.subscribe(onChange);
      }
      if (typeof window !== 'undefined') {
        window.addEventListener('beforeunload', function (e) {
          if (isChanged()) { e.preventDefault(); e.returnValue = ''; }
        });
      }
    }

    function activate() {
      init();
      renderSide();
      renderMain();
      if (store && typeof store.loadList === 'function') {
        store.loadList();
      }
      if (typeof spec.onActivate === 'function') {
        spec.onActivate(store, { ui: ui, renderMain: renderMain, renderSide: renderSide });
      }
    }

    return {
      init: init,
      activate: activate,
      isDirty: isChanged,
      getStore: function () { return store; },
      getUI: function () { return ui; },
      getGroupManager: function () { return groupMgr; },
      getSpec: function () { return spec; },
      promptDuplicate: promptDuplicate,
      promptGroup: promptGroup,
      renderSide: renderSide,
      renderMain: renderMain,
      updateLive: updateLive,
      live: live,
      section: section,
      confirmLeave: confirmLeave,
      open: openItem,
      toggleGroupMenu: toggleGroupMenu,
      toggleItemMenu: toggleItemMenu,
      closeActiveMenu: closeActiveMenu,
      sortItemsList: sortItemsList
    };
  }

  var api = {
    createBaseView: createBaseView,
    section: section
  };

  MM.configBaseView = api;
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;
  }
})();
