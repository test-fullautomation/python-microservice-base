/**
 * @fileoverview SchemaRenderer — renders a service GUI from a JSON schema descriptor.
 *
 * Supports component types: method-form, result-table, text, live-status, custom.
 * Supports layout modes: single, tabs, accordion.
 *
 * Usage:
 *   SchemaRenderer.render(schema, containerEl, serviceName);
 *
 * Exposed as window.SchemaRenderer (follows MM namespace pattern).
 */

(function () {
  'use strict';

  var MM = window.MicroserviceManager;
  var _liveTimers = [];

  /* ================================================================
   *  Public API
   * ================================================================ */

  var SchemaRenderer = {
    /**
     * Render a full GUI from a schema descriptor into a container element.
     *
     * @param {Object} schema   - Parsed gui_schema.json object.
     * @param {HTMLElement} container - DOM element to render into.
     * @param {string} serviceName   - Service name key in MM.servicesInfor.
     */
    render: function (schema, container, serviceName) {
      _clearLiveTimers();
      container.innerHTML = '';

      // Card wrapper
      var card = document.createElement('div');
      card.className = 'card schema-gui-card';
      card.style.cssText = 'height:100%;width:100%;top:0;';

      // Header
      if (schema.title || schema.subtitle) {
        var header = document.createElement('div');
        header.className = 'card-header';
        header.innerHTML =
          '<h5 class="card-title mb-0">' + _esc(schema.title || serviceName) + '</h5>' +
          (schema.subtitle ? '<small class="text-muted">' + _esc(schema.subtitle) + '</small>' : '');
        card.appendChild(header);
      }

      // Body
      var body = document.createElement('div');
      body.className = 'card-body';
      _renderLayout(schema, body, serviceName);
      card.appendChild(body);

      container.appendChild(card);
    },

    /** Stop all live-status polling timers. */
    cleanup: function () {
      _clearLiveTimers();
    }
  };

  /* ================================================================
   *  Layout renderers
   * ================================================================ */

  function _renderLayout(schema, container, serviceName) {
    var sections = schema.sections || [];
    var layout = schema.layout || 'single';

    if (layout === 'tabs' && sections.length > 1) {
      _renderTabsLayout(sections, container, serviceName);
    } else if (layout === 'accordion' && sections.length > 1) {
      _renderAccordionLayout(sections, container, serviceName);
    } else {
      // single or fallback
      sections.forEach(function (section) {
        _renderSection(section, container, serviceName);
      });
    }
  }

  function _renderTabsLayout(sections, container, serviceName) {
    var tabId = 'schemaTabs_' + _uid();

    // Nav tabs
    var nav = document.createElement('ul');
    nav.className = 'nav nav-tabs mb-3';
    nav.setAttribute('role', 'tablist');

    var content = document.createElement('div');
    content.className = 'tab-content';

    sections.forEach(function (section, idx) {
      var paneId = tabId + '_pane_' + (section.id || idx);
      var isActive = idx === 0;

      // Tab button
      var li = document.createElement('li');
      li.className = 'nav-item';
      li.setAttribute('role', 'presentation');
      var btn = document.createElement('button');
      btn.className = 'nav-link' + (isActive ? ' active' : '');
      btn.setAttribute('data-bs-toggle', 'tab');
      btn.setAttribute('data-bs-target', '#' + paneId);
      btn.setAttribute('type', 'button');
      btn.setAttribute('role', 'tab');
      btn.textContent = section.label || 'Section ' + (idx + 1);
      li.appendChild(btn);
      nav.appendChild(li);

      // Tab pane
      var pane = document.createElement('div');
      pane.className = 'tab-pane fade' + (isActive ? ' show active' : '');
      pane.id = paneId;
      pane.setAttribute('role', 'tabpanel');
      _renderSection(section, pane, serviceName);
      content.appendChild(pane);
    });

    container.appendChild(nav);
    container.appendChild(content);
  }

  function _renderAccordionLayout(sections, container, serviceName) {
    var accId = 'schemaAcc_' + _uid();

    var acc = document.createElement('div');
    acc.className = 'accordion';
    acc.id = accId;

    sections.forEach(function (section, idx) {
      var itemId = accId + '_item_' + (section.id || idx);
      var isFirst = idx === 0;

      var item = document.createElement('div');
      item.className = 'accordion-item';

      var headerEl = document.createElement('h2');
      headerEl.className = 'accordion-header';

      var btn = document.createElement('button');
      btn.className = 'accordion-button' + (isFirst ? '' : ' collapsed');
      btn.setAttribute('type', 'button');
      btn.setAttribute('data-bs-toggle', 'collapse');
      btn.setAttribute('data-bs-target', '#' + itemId);
      btn.textContent = section.label || 'Section ' + (idx + 1);
      headerEl.appendChild(btn);

      var collapseDiv = document.createElement('div');
      collapseDiv.id = itemId;
      collapseDiv.className = 'accordion-collapse collapse' + (isFirst ? ' show' : '');
      collapseDiv.setAttribute('data-bs-parent', '#' + accId);

      var bodyDiv = document.createElement('div');
      bodyDiv.className = 'accordion-body';
      _renderSection(section, bodyDiv, serviceName);
      collapseDiv.appendChild(bodyDiv);

      item.appendChild(headerEl);
      item.appendChild(collapseDiv);
      acc.appendChild(item);
    });

    container.appendChild(acc);
  }

  /* ================================================================
   *  Section renderer
   * ================================================================ */

  function _renderSection(section, container, serviceName) {
    var components = section.components || [];
    components.forEach(function (comp) {
      _renderComponent(comp, container, serviceName);
    });
  }

  /* ================================================================
   *  Component dispatch
   * ================================================================ */

  function _renderComponent(comp, container, serviceName) {
    switch (comp.type) {
      case 'method-form':
        _renderMethodForm(comp, container, serviceName);
        break;
      case 'result-table':
        _renderResultTable(comp, container, serviceName);
        break;
      case 'text':
        _renderText(comp, container);
        break;
      case 'live-status':
        _renderLiveStatus(comp, container, serviceName);
        break;
      case 'custom':
        _renderCustom(comp, container);
        break;
      default:
        console.warn('SchemaRenderer: unknown component type "' + comp.type + '"');
    }
  }

  /* ================================================================
   *  method-form component
   * ================================================================ */

  function _renderMethodForm(comp, container, serviceName) {
    var formId = 'schemaForm_' + _uid();
    var resultId = 'schemaResult_' + _uid();

    var wrapper = document.createElement('div');
    wrapper.className = 'mb-4';

    // Method title
    if (comp.method) {
      var title = document.createElement('h6');
      title.className = 'fw-semibold mb-3';
      title.innerHTML = '<code>' + _esc(comp.method) + '</code>';
      wrapper.appendChild(title);
    }

    // Form
    var form = document.createElement('form');
    form.id = formId;
    form.addEventListener('submit', function (e) { e.preventDefault(); });

    var fields = comp.fields || [];
    fields.forEach(function (field) {
      var fieldEl = _buildField(field);
      form.appendChild(fieldEl);
    });

    // Submit button
    var btnRow = document.createElement('div');
    btnRow.className = 'mt-3';
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'btn btn-primary';
    btn.innerHTML = '<i class="bi bi-play-fill me-1"></i>' + _esc(comp.submit_label || 'Execute');
    btnRow.appendChild(btn);
    form.appendChild(btnRow);

    wrapper.appendChild(form);

    // Result area
    var resultDiv = document.createElement('div');
    resultDiv.id = resultId;
    resultDiv.className = 'mt-3';
    resultDiv.style.display = 'none';
    wrapper.appendChild(resultDiv);

    // Wire submit
    btn.addEventListener('click', function () {
      var args = _collectArgs(form, fields);
      btn.disabled = true;
      btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Running...';

      _callMethod(serviceName, comp.method, args)
        .then(function (data) {
          resultDiv.style.display = '';
          _displayResult(resultDiv, data, comp.result_display || 'text');
        })
        .catch(function (err) {
          resultDiv.style.display = '';
          resultDiv.innerHTML = '<div class="alert alert-danger">' + _esc(String(err)) + '</div>';
        })
        .finally(function () {
          btn.disabled = false;
          btn.innerHTML = '<i class="bi bi-play-fill me-1"></i>' + _esc(comp.submit_label || 'Execute');
        });
    });

    container.appendChild(wrapper);
  }

  /* ================================================================
   *  result-table component
   * ================================================================ */

  function _renderResultTable(comp, container, serviceName) {
    var tableId = 'schemaTable_' + _uid();

    var wrapper = document.createElement('div');
    wrapper.className = 'mb-4';

    if (comp.method) {
      var title = document.createElement('h6');
      title.className = 'fw-semibold mb-2';
      title.innerHTML = '<code>' + _esc(comp.method) + '</code>';
      wrapper.appendChild(title);
    }

    var tableContainer = document.createElement('div');
    tableContainer.id = tableId;
    tableContainer.innerHTML = '<div class="text-muted">Loading...</div>';
    wrapper.appendChild(tableContainer);

    container.appendChild(wrapper);

    // Fetch data function
    var fetchData = function () {
      _callMethod(serviceName, comp.method, [])
        .then(function (data) {
          _renderTableFromData(tableContainer, data, comp.columns);
        })
        .catch(function (err) {
          tableContainer.innerHTML = '<div class="alert alert-warning">' + _esc(String(err)) + '</div>';
        });
    };

    fetchData();

    // Auto-refresh
    if (comp.auto_refresh && comp.auto_refresh > 0) {
      var timer = setInterval(fetchData, comp.auto_refresh);
      _liveTimers.push(timer);
    }
  }

  function _renderTableFromData(container, data, columns) {
    var resultData = (data && data.result_data !== undefined) ? data.result_data : data;
    var rows = Array.isArray(resultData) ? resultData : [resultData];

    if (!rows.length || (rows.length === 1 && rows[0] == null)) {
      container.innerHTML = '<div class="text-muted">No data</div>';
      return;
    }

    // Determine columns
    var cols = columns;
    if (!cols || !cols.length) {
      if (typeof rows[0] === 'object' && rows[0] !== null) {
        cols = Object.keys(rows[0]).map(function (k) {
          return { key: k, label: k };
        });
      } else {
        cols = [{ key: '_value', label: 'Value' }];
      }
    }

    var html = '<div class="table-responsive"><table class="table table-sm table-striped">';
    html += '<thead><tr>';
    cols.forEach(function (c) {
      html += '<th>' + _esc(c.label || c.key) + '</th>';
    });
    html += '</tr></thead><tbody>';

    rows.forEach(function (row) {
      html += '<tr>';
      cols.forEach(function (c) {
        var val = '';
        if (typeof row === 'object' && row !== null) {
          val = row[c.key] !== undefined ? row[c.key] : '';
        } else if (c.key === '_value') {
          val = row;
        }
        html += '<td>' + _esc(String(val)) + '</td>';
      });
      html += '</tr>';
    });

    html += '</tbody></table></div>';
    container.innerHTML = html;
  }

  /* ================================================================
   *  text component
   * ================================================================ */

  function _renderText(comp, container) {
    var div = document.createElement('div');
    div.className = 'mb-3 text-muted';
    div.textContent = comp.content || '';
    container.appendChild(div);
  }

  /* ================================================================
   *  live-status component
   * ================================================================ */

  function _renderLiveStatus(comp, container, serviceName) {
    var badgeId = 'schemaLive_' + _uid();
    var interval = comp.interval_ms || 5000;

    var wrapper = document.createElement('div');
    wrapper.className = 'mb-3 d-flex align-items-center';

    if (comp.label) {
      var label = document.createElement('span');
      label.className = 'me-2 fw-semibold';
      label.textContent = comp.label;
      wrapper.appendChild(label);
    }

    var badge = document.createElement('span');
    badge.className = 'badge bg-secondary';
    badge.id = badgeId;
    badge.textContent = 'Loading...';
    wrapper.appendChild(badge);

    container.appendChild(wrapper);

    var poll = function () {
      _callMethod(serviceName, comp.method, [])
        .then(function (data) {
          var resultData = (data && data.result_data !== undefined) ? data.result_data : data;
          var text = '';
          if (comp.format) {
            text = comp.format.replace(/\{(\w+)\}/g, function (_, key) {
              return (typeof resultData === 'object' && resultData !== null)
                ? String(resultData[key] || '')
                : String(resultData || '');
            });
          } else {
            text = typeof resultData === 'object' ? JSON.stringify(resultData) : String(resultData);
          }
          badge.textContent = text;
          badge.className = 'badge bg-success';
        })
        .catch(function () {
          badge.textContent = 'Error';
          badge.className = 'badge bg-danger';
        });
    };

    poll();
    var timer = setInterval(poll, interval);
    _liveTimers.push(timer);
  }

  /* ================================================================
   *  custom component (inline HTML escape hatch)
   * ================================================================ */

  function _renderCustom(comp, container) {
    var div = document.createElement('div');
    div.className = 'mb-3';
    if (comp.html) {
      div.innerHTML = comp.html;
    }
    container.appendChild(div);

    if (comp.script) {
      try {
        var fn = new Function(comp.script);
        fn();
      } catch (e) {
        console.error('SchemaRenderer: custom script error', e);
      }
    }
  }

  /* ================================================================
   *  Field builders
   * ================================================================ */

  function _buildField(field) {
    var groupDiv = document.createElement('div');
    groupDiv.className = 'mb-3';

    var label = document.createElement('label');
    label.className = 'form-label';
    label.textContent = field.label || field.arg || '';
    groupDiv.appendChild(label);

    var widget = field.widget || 'text';
    var input;

    switch (widget) {
      case 'textarea':
        input = document.createElement('textarea');
        input.className = 'form-control';
        input.rows = field.rows || 3;
        input.placeholder = field.placeholder || '';
        if (field.default != null) input.value = String(field.default);
        break;

      case 'select':
        input = document.createElement('select');
        input.className = 'form-select';
        (field.options || []).forEach(function (opt) {
          var option = document.createElement('option');
          if (typeof opt === 'object') {
            option.value = opt.value;
            option.textContent = opt.label || opt.value;
          } else {
            option.value = opt;
            option.textContent = opt;
          }
          input.appendChild(option);
        });
        if (field.default != null) input.value = String(field.default);
        break;

      case 'checkbox':
        var checkDiv = document.createElement('div');
        checkDiv.className = 'form-check';
        input = document.createElement('input');
        input.type = 'checkbox';
        input.className = 'form-check-input';
        if (field.default === true) input.checked = true;
        var checkLabel = document.createElement('label');
        checkLabel.className = 'form-check-label';
        checkLabel.textContent = field.label || field.arg || '';
        checkDiv.appendChild(input);
        checkDiv.appendChild(checkLabel);
        // Replace the label we already added
        groupDiv.innerHTML = '';
        groupDiv.appendChild(checkDiv);
        break;

      case 'number':
        input = document.createElement('input');
        input.type = 'number';
        input.className = 'form-control';
        input.placeholder = field.placeholder || '';
        if (field.min != null) input.min = field.min;
        if (field.max != null) input.max = field.max;
        if (field.step != null) input.step = field.step;
        if (field.default != null) input.value = String(field.default);
        break;

      case 'file':
        input = document.createElement('input');
        input.type = 'file';
        input.className = 'form-control';
        if (field.accept) input.accept = field.accept;
        break;

      default: // 'text'
        input = document.createElement('input');
        input.type = 'text';
        input.className = 'form-control';
        input.placeholder = field.placeholder || '';
        if (field.default != null) input.value = String(field.default);
        break;
    }

    input.setAttribute('data-arg', field.arg || '');
    input.setAttribute('data-widget', widget);
    if (widget !== 'checkbox') {
      groupDiv.appendChild(input);
    }

    // Description hint
    if (field.description) {
      var hint = document.createElement('div');
      hint.className = 'form-text';
      hint.textContent = field.description;
      groupDiv.appendChild(hint);
    }

    return groupDiv;
  }

  /* ================================================================
   *  Value collection
   * ================================================================ */

  function _collectArgs(formEl, fields) {
    var args = [];
    fields.forEach(function (field) {
      var input = formEl.querySelector('[data-arg="' + field.arg + '"]');
      if (!input) {
        args.push(null);
        return;
      }

      var widget = input.getAttribute('data-widget') || 'text';
      var val;

      switch (widget) {
        case 'checkbox':
          val = input.checked;
          break;
        case 'number':
          val = input.value === '' ? null : Number(input.value);
          break;
        case 'file':
          // File inputs are handled asynchronously — for now push null
          // (file support is base64 encode on submit, handled separately)
          val = input.files && input.files[0] ? input.files[0].name : null;
          break;
        default:
          val = input.value;
          break;
      }

      args.push(val);
    });
    return args;
  }

  /* ================================================================
   *  Result display
   * ================================================================ */

  function _displayResult(resultEl, data, mode) {
    var resultData = (data && data.result_data !== undefined) ? data.result_data : data;
    var resultStatus = (data && data.result) || 'pass';
    var isError = resultStatus === 'exception' || resultStatus === 'error';

    resultEl.innerHTML = '';

    switch (mode) {
      case 'json':
        var pre = document.createElement('pre');
        pre.className = 'api-response-pre';
        try {
          pre.textContent = JSON.stringify(resultData, null, 2);
        } catch (e) {
          pre.textContent = String(resultData);
        }
        resultEl.appendChild(pre);
        break;

      case 'table':
        _renderTableFromData(resultEl, data);
        break;

      case 'image':
        if (resultData) {
          var img = document.createElement('img');
          img.className = 'img-fluid rounded';
          img.style.maxWidth = '100%';
          // Support raw base64 or data URI
          if (typeof resultData === 'string' && !resultData.startsWith('data:')) {
            img.src = 'data:image/png;base64,' + resultData;
          } else {
            img.src = resultData;
          }
          resultEl.appendChild(img);
        } else {
          resultEl.innerHTML = '<div class="text-muted">No image data</div>';
        }
        break;

      case 'none':
        if (isError) {
          resultEl.innerHTML = '<div class="alert alert-danger">' + _esc(String(resultData)) + '</div>';
          resultEl.style.display = '';
        }
        break;

      default: // 'text'
        var alertClass = isError ? 'alert-danger' : 'alert-info';
        var div = document.createElement('div');
        div.className = 'alert ' + alertClass;
        div.textContent = typeof resultData === 'object'
          ? JSON.stringify(resultData)
          : String(resultData != null ? resultData : '');
        resultEl.appendChild(div);
        break;
    }
  }

  /* ================================================================
   *  Service call helper
   * ================================================================ */

  function _callMethod(serviceName, method, args) {
    var serviceInfo = MM.servicesInfor[serviceName];
    if (!serviceInfo) {
      return Promise.reject(new Error('Service "' + serviceName + '" not found'));
    }

    var routingKey = serviceInfo.routing_key;
    var requestData = { method: method, args: args };

    return MM.requestService(requestData, 'services_request', routingKey)
      .then(function (data) {
        if (data && (data.result === 'exception' || data.result === 'error')) {
          var err = new Error(data.result_data || 'Service returned an error');
          err.responseData = data;
          throw err;
        }
        return data;
      });
  }

  /* ================================================================
   *  Utilities
   * ================================================================ */

  var _uidCounter = 0;
  function _uid() {
    return 'sr' + (++_uidCounter) + '_' + Date.now().toString(36);
  }

  function _esc(str) {
    var div = document.createElement('div');
    div.appendChild(document.createTextNode(str));
    return div.innerHTML;
  }

  function _clearLiveTimers() {
    _liveTimers.forEach(function (t) { clearInterval(t); });
    _liveTimers = [];
  }

  /* ================================================================
   *  Expose
   * ================================================================ */

  window.SchemaRenderer = SchemaRenderer;

})();
