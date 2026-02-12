/**
 * @fileoverview Service Creator Wizard — generates boilerplate microservice projects.
 * Renders a 4-step wizard into #creatorContent with a step sidebar in #creatorStepList.
 *
 * @author Nguyen Huynh Tri Cuong
 * @version 1.0.0
 */

(function () {
  'use strict';

  var MM = window.MicroserviceManager;

  var STEPS = [
    { label: 'Basic Info' },
    { label: 'API Methods' },
    { label: 'GUI Support' },
    { label: 'Review & Generate' }
  ];

  var _currentStep = 0;
  var _formData = _defaultFormData();
  var _methodIdCounter = 0;
  var _uploadedJsFileName = '';

  function _defaultFormData() {
    return {
      serviceName: '',
      version: '1.0.0',
      description: '',
      shortDescription: '',
      group: '',
      tag: '',
      routingKey: '',
      transport: 'rabbitmq',
      guiSupport: false,
      methods: [],
      outputPath: '',
      customGuiHtml: null,
      customGuiJs: null
    };
  }

  // ---- Helpers ----

  function _escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function _toSnakeCase(name) {
    return name
      .replace(/([A-Z])/g, function (m, c, i) { return (i > 0 ? '_' : '') + c; })
      .toLowerCase()
      .replace(/[^a-z0-9_]/g, '_')
      .replace(/_+/g, '_')
      .replace(/^_|_$/g, '');
  }

  function _toPascalCase(str) {
    return str
      .replace(/[^a-zA-Z0-9]/g, ' ')
      .split(/\s+/)
      .map(function (w) { return w.charAt(0).toUpperCase() + w.slice(1); })
      .join('');
  }

  // ---- Step Sidebar ----

  function _renderStepList() {
    var container = document.getElementById('creatorStepList');
    if (!container) return;

    var html = '<div class="creator-sidebar-title">Service Creator</div>';
    STEPS.forEach(function (step, i) {
      var cls = 'creator-step';
      if (i === _currentStep) cls += ' active';
      else if (i < _currentStep) cls += ' completed';

      var icon = (i < _currentStep) ? '<i class="bi bi-check-lg"></i>' : (i + 1);

      html +=
        '<div class="' + cls + '" data-step="' + i + '">' +
          '<span class="creator-step-number">' + icon + '</span>' +
          '<span class="creator-step-label">' + _escapeHtml(step.label) + '</span>' +
        '</div>';
    });

    container.innerHTML = html;

    // Wire click navigation
    container.querySelectorAll('.creator-step').forEach(function (el) {
      el.addEventListener('click', function () {
        var target = parseInt(el.getAttribute('data-step'), 10);
        _navigateToStep(target);
      });
    });
  }

  function _navigateToStep(target) {
    // Allow going back freely; going forward requires validation
    if (target > _currentStep) {
      for (var i = _currentStep; i < target; i++) {
        if (!_validateStep(i)) return;
      }
    }
    _collectFormData();
    _currentStep = target;
    _renderStepList();
    _renderStep(_currentStep);
  }

  // ---- Step Rendering ----

  function _renderStep(n) {
    var content = document.getElementById('creatorContent');
    if (!content) return;

    switch (n) {
      case 0: _renderStep1(content); break;
      case 1: _renderStep2(content); break;
      case 2: _renderStep3(content); break;
      case 3: _renderStep4(content); break;
    }
  }

  // Step 1: Basic Info
  function _renderStep1(container) {
    var d = _formData;
    var rk = d.routingKey || (d.serviceName ? 'service.' + _toSnakeCase(d.serviceName) : '');

    container.innerHTML =
      '<div class="creator-content">' +
        '<div class="creator-header">' +
          '<h4><i class="bi bi-1-circle me-2"></i>Basic Information</h4>' +
          '<p>Define the core metadata for your new microservice.</p>' +
        '</div>' +
        '<form id="creatorForm1">' +
          '<div class="row mb-3">' +
            '<div class="col-md-8">' +
              '<label class="form-label fw-semibold">Service Name <span class="text-danger">*</span></label>' +
              '<input type="text" class="form-control" id="cfServiceName" ' +
                'placeholder="MyService (PascalCase)" value="' + _escapeHtml(d.serviceName) + '">' +
              '<div class="form-text">PascalCase name for your service class.</div>' +
            '</div>' +
            '<div class="col-md-4">' +
              '<label class="form-label fw-semibold">Version</label>' +
              '<input type="text" class="form-control" id="cfVersion" ' +
                'placeholder="1.0.0" value="' + _escapeHtml(d.version) + '">' +
            '</div>' +
          '</div>' +
          '<div class="mb-3">' +
            '<label class="form-label fw-semibold">Description</label>' +
            '<textarea class="form-control" id="cfDescription" rows="2" ' +
              'placeholder="A detailed description of what the service does.">' + _escapeHtml(d.description) + '</textarea>' +
          '</div>' +
          '<div class="mb-3">' +
            '<label class="form-label fw-semibold">Short Description</label>' +
            '<input type="text" class="form-control" id="cfShortDesc" ' +
              'placeholder="Brief one-line summary" value="' + _escapeHtml(d.shortDescription) + '">' +
          '</div>' +
          '<div class="row mb-3">' +
            '<div class="col-md-6">' +
              '<label class="form-label fw-semibold">Group</label>' +
              '<input type="text" class="form-control" id="cfGroup" ' +
                'placeholder="e.g. tools, examples" value="' + _escapeHtml(d.group) + '">' +
            '</div>' +
            '<div class="col-md-6">' +
              '<label class="form-label fw-semibold">Tag</label>' +
              '<input type="text" class="form-control" id="cfTag" ' +
                'placeholder="e.g. v1" value="' + _escapeHtml(d.tag) + '">' +
            '</div>' +
          '</div>' +
          '<div class="mb-3">' +
            '<label class="form-label fw-semibold">Routing Key</label>' +
            '<input type="text" class="form-control" id="cfRoutingKey" ' +
              'placeholder="service.my_service" value="' + _escapeHtml(rk) + '">' +
            '<div class="form-text">Auto-generated from service name. You can customize it.</div>' +
          '</div>' +
          '<div class="mb-3">' +
            '<label class="form-label fw-semibold">Transport Type</label>' +
            '<select class="form-select" id="cfTransport">' +
              '<option value="rabbitmq"' + (d.transport === 'rabbitmq' ? ' selected' : '') + '>RabbitMQ</option>' +
              '<option value="eventbus"' + (d.transport === 'eventbus' ? ' selected' : '') + '>EventBus</option>' +
            '</select>' +
          '</div>' +
        '</form>' +
        _navButtons(0) +
      '</div>';

    // Auto-generate routing key on service name change
    var nameInput = document.getElementById('cfServiceName');
    var rkInput = document.getElementById('cfRoutingKey');
    if (nameInput && rkInput) {
      nameInput.addEventListener('input', function () {
        var name = nameInput.value.trim();
        if (name) {
          rkInput.value = 'service.' + _toSnakeCase(name);
        }
      });
    }

    _wireNavButtons();
  }

  // Step 2: API Methods
  function _renderStep2(container) {
    container.innerHTML =
      '<div class="creator-content">' +
        '<div class="creator-header">' +
          '<h4><i class="bi bi-2-circle me-2"></i>API Methods</h4>' +
          '<p>Define the methods your service will expose. Each method name will be prefixed with <code>svc_api_</code>.</p>' +
        '</div>' +
        '<div id="creatorMethodList"></div>' +
        '<button class="btn btn-outline-primary btn-sm" id="btnAddMethod">' +
          '<i class="bi bi-plus-lg me-1"></i>Add Method' +
        '</button>' +
        _navButtons(1) +
      '</div>';

    var methodList = document.getElementById('creatorMethodList');

    // Render existing methods
    _formData.methods.forEach(function (method) {
      _appendMethodCard(methodList, method);
    });

    document.getElementById('btnAddMethod').addEventListener('click', function () {
      var method = { id: ++_methodIdCounter, name: '', params: [], returnType: '', description: '' };
      _formData.methods.push(method);
      _appendMethodCard(methodList, method);
    });

    _wireNavButtons();
  }

  function _appendMethodCard(container, method) {
    var card = document.createElement('div');
    card.className = 'creator-method-card';
    card.setAttribute('data-method-id', method.id);

    card.innerHTML =
      '<div class="method-header">' +
        '<h6><code>svc_api_</code><input type="text" class="form-control form-control-sm d-inline-block" ' +
          'style="width:200px" placeholder="method_name" value="' + _escapeHtml(method.name) + '" data-field="name"></h6>' +
        '<button class="btn-remove-method" title="Remove method"><i class="bi bi-trash"></i></button>' +
      '</div>' +
      '<div class="row mb-2">' +
        '<div class="col-md-4">' +
          '<label class="form-label form-label-sm">Return Type</label>' +
          '<input type="text" class="form-control form-control-sm" placeholder="e.g. str, int, dict" ' +
            'value="' + _escapeHtml(method.returnType) + '" data-field="returnType">' +
        '</div>' +
        '<div class="col-md-8">' +
          '<label class="form-label form-label-sm">Description</label>' +
          '<input type="text" class="form-control form-control-sm" placeholder="What does this method do?" ' +
            'value="' + _escapeHtml(method.description) + '" data-field="description">' +
        '</div>' +
      '</div>' +
      '<label class="form-label form-label-sm fw-semibold">Parameters</label>' +
      '<div class="method-params"></div>' +
      '<button class="btn btn-outline-secondary btn-sm mt-1 btn-add-param">' +
        '<i class="bi bi-plus me-1"></i>Add Parameter' +
      '</button>';

    // Wire remove method
    card.querySelector('.btn-remove-method').addEventListener('click', function () {
      _formData.methods = _formData.methods.filter(function (m) { return m.id !== method.id; });
      card.remove();
    });

    // Render existing params
    var paramsContainer = card.querySelector('.method-params');
    (method.params || []).forEach(function (param) {
      _appendParamRow(paramsContainer, param);
    });

    // Wire add param
    card.querySelector('.btn-add-param').addEventListener('click', function () {
      var param = { name: '', type: 'str', required: true };
      _appendParamRow(paramsContainer, param);
    });

    container.appendChild(card);
  }

  function _appendParamRow(container, param) {
    var row = document.createElement('div');
    row.className = 'creator-param-row';

    row.innerHTML =
      '<div style="flex:2">' +
        '<input type="text" class="form-control form-control-sm" placeholder="param_name" ' +
          'value="' + _escapeHtml(param.name) + '" data-pfield="name">' +
      '</div>' +
      '<div style="flex:1">' +
        '<select class="form-select form-select-sm" data-pfield="type">' +
          '<option value="str"' + (param.type === 'str' ? ' selected' : '') + '>str</option>' +
          '<option value="int"' + (param.type === 'int' ? ' selected' : '') + '>int</option>' +
          '<option value="float"' + (param.type === 'float' ? ' selected' : '') + '>float</option>' +
          '<option value="bool"' + (param.type === 'bool' ? ' selected' : '') + '>bool</option>' +
          '<option value="list"' + (param.type === 'list' ? ' selected' : '') + '>list</option>' +
          '<option value="dict"' + (param.type === 'dict' ? ' selected' : '') + '>dict</option>' +
        '</select>' +
      '</div>' +
      '<div style="flex:1">' +
        '<select class="form-select form-select-sm" data-pfield="required">' +
          '<option value="true"' + (param.required !== false ? ' selected' : '') + '>required</option>' +
          '<option value="false"' + (param.required === false ? ' selected' : '') + '>optional</option>' +
        '</select>' +
      '</div>' +
      '<button class="btn-remove-param" title="Remove parameter"><i class="bi bi-x-lg"></i></button>';

    row.querySelector('.btn-remove-param').addEventListener('click', function () {
      row.remove();
    });

    container.appendChild(row);
  }

  // Step 3: GUI Support
  function _renderStep3(container) {
    var hasGui = _formData.guiSupport;
    var htmlContent = _formData.customGuiHtml || _generateGuiHtml(_formData);

    container.innerHTML =
      '<div class="creator-content' + (hasGui ? ' has-gui-preview' : '') + '">' +
        '<div class="creator-header">' +
          '<h4><i class="bi bi-3-circle me-2"></i>GUI Support</h4>' +
          '<p>Choose whether to include a GUI template for your service.</p>' +
        '</div>' +
        '<div class="card">' +
          '<div class="card-body">' +
            '<div class="form-check form-switch mb-3">' +
              '<input class="form-check-input" type="checkbox" id="cfGuiSupport"' +
                (hasGui ? ' checked' : '') + '>' +
              '<label class="form-check-label fw-semibold" for="cfGuiSupport">' +
                'Generate GUI template' +
              '</label>' +
            '</div>' +
            '<div id="guiPreviewArea" style="display:' + (hasGui ? '' : 'none') + '">' +

              // Toolbar
              '<div class="gui-preview-toolbar">' +
                '<button class="btn btn-outline-secondary btn-sm" id="btnResetGuiTemplate">' +
                  '<i class="bi bi-arrow-counterclockwise me-1"></i>Reset to Template' +
                '</button>' +
                '<label class="btn btn-outline-primary btn-sm mb-0" id="lblUploadHtml">' +
                  '<i class="bi bi-upload me-1"></i>Upload HTML' +
                  '<input type="file" accept=".html,.htm" id="cfUploadHtml" class="d-none">' +
                '</label>' +
              '</div>' +

              // Side-by-side editor + preview
              '<div class="gui-preview-layout">' +
                '<div>' +
                  '<label class="form-label fw-semibold form-label-sm">HTML Editor</label>' +
                  '<textarea class="gui-html-editor" id="cfGuiHtmlEditor" spellcheck="false">' +
                    _escapeHtml(htmlContent) +
                  '</textarea>' +
                '</div>' +
                '<div>' +
                  '<label class="form-label fw-semibold form-label-sm">Live Preview</label>' +
                  '<div class="gui-preview-render" id="guiPreviewRender">' +
                    htmlContent +
                  '</div>' +
                '</div>' +
              '</div>' +

              // JS upload dropzone
              '<div class="mt-3">' +
                '<label class="form-label fw-semibold form-label-sm">JavaScript File (optional)</label>' +
                '<div class="gui-js-dropzone" id="guiJsDropzone">' +
                  '<i class="bi bi-filetype-js me-2"></i>' +
                  '<span id="guiJsDropzoneLabel">' +
                    (_uploadedJsFileName
                      ? '<span class="badge bg-info me-1">' + _escapeHtml(_uploadedJsFileName) + '</span> Drop or click to replace'
                      : 'Drag &amp; drop a .js file here, or click to browse') +
                  '</span>' +
                  '<input type="file" accept=".js" id="cfUploadJs" class="d-none">' +
                '</div>' +
              '</div>' +

            '</div>' +
          '</div>' +
        '</div>' +
        _navButtons(2) +
      '</div>';

    // ---- Wire events ----
    var checkbox = document.getElementById('cfGuiSupport');
    var previewArea = document.getElementById('guiPreviewArea');
    var creatorContent = container.querySelector('.creator-content');
    var editor = document.getElementById('cfGuiHtmlEditor');
    var preview = document.getElementById('guiPreviewRender');

    // Toggle GUI support
    checkbox.addEventListener('change', function () {
      _formData.guiSupport = checkbox.checked;
      previewArea.style.display = checkbox.checked ? '' : 'none';
      if (checkbox.checked) {
        creatorContent.classList.add('has-gui-preview');
        if (!editor.value.trim()) {
          var tpl = _generateGuiHtml(_formData);
          editor.value = tpl;
          preview.innerHTML = tpl;
        }
      } else {
        creatorContent.classList.remove('has-gui-preview');
      }
    });

    // Debounced live preview
    var _debounceTimer = null;
    editor.addEventListener('input', function () {
      clearTimeout(_debounceTimer);
      _debounceTimer = setTimeout(function () {
        preview.innerHTML = editor.value;
      }, 200);
    });

    // HTML file upload
    var htmlFileInput = document.getElementById('cfUploadHtml');
    htmlFileInput.addEventListener('change', function () {
      if (htmlFileInput.files && htmlFileInput.files[0]) {
        _readFileAsText(htmlFileInput.files[0], function (text) {
          editor.value = text;
          preview.innerHTML = text;
          _formData.customGuiHtml = text;
        });
      }
    });

    // HTML drag-and-drop on editor
    editor.addEventListener('dragover', function (e) { e.preventDefault(); });
    editor.addEventListener('drop', function (e) {
      e.preventDefault();
      var file = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
      if (file && /\.(html?|htm)$/i.test(file.name)) {
        _readFileAsText(file, function (text) {
          editor.value = text;
          preview.innerHTML = text;
          _formData.customGuiHtml = text;
        });
      }
    });

    // JS file upload
    var jsFileInput = document.getElementById('cfUploadJs');
    var jsDropzone = document.getElementById('guiJsDropzone');
    var jsLabel = document.getElementById('guiJsDropzoneLabel');

    jsDropzone.addEventListener('click', function () { jsFileInput.click(); });
    jsFileInput.addEventListener('change', function () {
      if (jsFileInput.files && jsFileInput.files[0]) {
        _handleJsUpload(jsFileInput.files[0], jsLabel);
      }
    });

    // JS drag-and-drop
    jsDropzone.addEventListener('dragover', function (e) {
      e.preventDefault();
      jsDropzone.classList.add('dragover');
    });
    jsDropzone.addEventListener('dragleave', function () {
      jsDropzone.classList.remove('dragover');
    });
    jsDropzone.addEventListener('drop', function (e) {
      e.preventDefault();
      jsDropzone.classList.remove('dragover');
      var file = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
      if (file && /\.js$/i.test(file.name)) {
        _handleJsUpload(file, jsLabel);
      }
    });

    // Reset to Template
    document.getElementById('btnResetGuiTemplate').addEventListener('click', function () {
      var tpl = _generateGuiHtml(_formData);
      editor.value = tpl;
      preview.innerHTML = tpl;
      _formData.customGuiHtml = null;
      _formData.customGuiJs = null;
      _uploadedJsFileName = '';
      jsLabel.innerHTML = 'Drag &amp; drop a .js file here, or click to browse';
    });

    _wireNavButtons();
  }

  function _readFileAsText(file, callback) {
    var reader = new FileReader();
    reader.onload = function (e) { callback(e.target.result); };
    reader.readAsText(file);
  }

  function _handleJsUpload(file, labelEl) {
    _readFileAsText(file, function (text) {
      _formData.customGuiJs = text;
      _uploadedJsFileName = file.name;
      labelEl.innerHTML =
        '<span class="badge bg-info me-1">' + _escapeHtml(file.name) + '</span> Drop or click to replace';
    });
  }

  // Step 4: Review & Generate
  function _renderStep4(container) {
    _collectFormData();
    var d = _formData;
    var snakeName = _toSnakeCase(d.serviceName);

    // Build file tree
    var tree = d.serviceName + '/\n';
    tree += '\u251c\u2500\u2500 ' + snakeName + '.py\n';
    tree += '\u251c\u2500\u2500 main.py\n';
    if (d.transport === 'eventbus') {
      tree += '\u251c\u2500\u2500 config.jsonp\n';
    }
    if (d.guiSupport) {
      tree += '\u2514\u2500\u2500 GUIs/\n';
      tree += '    \u251c\u2500\u2500 service.html' + (d.customGuiHtml ? ' (custom)' : '') + '\n';
      tree += '    \u2514\u2500\u2500 service.js' + (d.customGuiJs ? ' (custom)' : '') + '\n';
    }

    // Build methods summary
    var methodsHtml = '';
    if (d.methods.length === 0) {
      methodsHtml = '<div class="text-muted fst-italic">No methods defined</div>';
    } else {
      d.methods.forEach(function (m) {
        var paramStr = (m.params || []).map(function (p) { return p.name; }).join(', ');
        methodsHtml +=
          '<div class="creator-summary-method">' +
            '<code>svc_api_' + _escapeHtml(m.name) + '(' + _escapeHtml(paramStr) + ')</code>' +
            (m.returnType ? ' &rarr; <code>' + _escapeHtml(m.returnType) + '</code>' : '') +
            (m.description ? '<div class="text-muted">' + _escapeHtml(m.description) + '</div>' : '') +
          '</div>';
      });
    }

    container.innerHTML =
      '<div class="creator-content">' +
        '<div class="creator-header">' +
          '<h4><i class="bi bi-4-circle me-2"></i>Review & Generate</h4>' +
          '<p>Verify your service configuration and generate the project files.</p>' +
        '</div>' +

        // Summary card
        '<div class="creator-summary">' +
          '<div class="creator-summary-header">' +
            '<i class="bi bi-box-seam me-2"></i>' + _escapeHtml(d.serviceName) + ' v' + _escapeHtml(d.version) +
          '</div>' +
          '<div class="creator-summary-body">' +
            _summaryRow('Description', d.description ? _escapeHtml(d.description) : '<em class="text-muted">none</em>') +
            _summaryRow('Short Desc', d.shortDescription ? _escapeHtml(d.shortDescription) : '<em class="text-muted">none</em>') +
            _summaryRow('Group', d.group ? _escapeHtml(d.group) : '<em class="text-muted">none</em>') +
            _summaryRow('Tag', d.tag ? _escapeHtml(d.tag) : '<em class="text-muted">none</em>') +
            _summaryRow('Routing Key', '<code>' + _escapeHtml(d.routingKey) + '</code>') +
            _summaryRow('Transport', d.transport) +
            _summaryRow('GUI Support', d.guiSupport
              ? '<span class="badge bg-success">Yes</span>' +
                (d.customGuiHtml ? ' <span class="badge bg-info">custom HTML</span>' : '') +
                (d.customGuiJs ? ' <span class="badge bg-info">custom JS</span>' : '')
              : '<span class="badge bg-secondary">No</span>') +
            '<div class="creator-summary-methods">' +
              '<div class="fw-semibold mb-2" style="font-size:0.85rem">API Methods (' + d.methods.length + ')</div>' +
              methodsHtml +
            '</div>' +
          '</div>' +
        '</div>' +

        // File tree preview
        '<label class="form-label fw-semibold">Generated File Structure</label>' +
        '<div class="creator-preview">' + _escapeHtml(tree) + '</div>' +

        // Output actions
        '<div class="creator-output-actions">' +
          '<div class="output-path-group">' +
            '<label class="form-label fw-semibold">Output Path (optional)</label>' +
            '<input type="text" class="form-control" id="cfOutputPath" ' +
              'placeholder="C:\\Projects\\MyService or leave empty for ZIP download" ' +
              'value="' + _escapeHtml(d.outputPath) + '">' +
          '</div>' +
          '<button class="btn btn-primary" id="btnDownloadZip">' +
            '<i class="bi bi-file-earmark-zip me-1"></i>Download ZIP' +
          '</button>' +
          '<button class="btn btn-outline-primary" id="btnSavePath" disabled>' +
            '<i class="bi bi-folder2-open me-1"></i>Save to Path' +
          '</button>' +
        '</div>' +

        _navButtons(3) +
      '</div>';

    // Wire output path → enable Save to Path
    var pathInput = document.getElementById('cfOutputPath');
    var saveBtn = document.getElementById('btnSavePath');
    pathInput.addEventListener('input', function () {
      saveBtn.disabled = !pathInput.value.trim();
    });
    if (pathInput.value.trim()) saveBtn.disabled = false;

    // Wire generate buttons
    document.getElementById('btnDownloadZip').addEventListener('click', function () {
      _submitGenerate('zip');
    });
    saveBtn.addEventListener('click', function () {
      _formData.outputPath = pathInput.value.trim();
      _submitGenerate('path');
    });

    _wireNavButtons();
  }

  function _summaryRow(label, valueHtml) {
    return '<div class="creator-summary-row">' +
      '<div class="creator-summary-label">' + _escapeHtml(label) + '</div>' +
      '<div class="creator-summary-value">' + valueHtml + '</div>' +
    '</div>';
  }

  // ---- Navigation Buttons ----

  function _navButtons(step) {
    var html = '<div class="creator-nav-buttons">';
    if (step > 0) {
      html += '<button class="btn btn-outline-secondary" id="btnCreatorPrev">' +
        '<i class="bi bi-arrow-left me-1"></i>Previous</button>';
    } else {
      html += '<div></div>';
    }
    if (step < STEPS.length - 1) {
      html += '<button class="btn btn-primary" id="btnCreatorNext">' +
        'Next<i class="bi bi-arrow-right ms-1"></i></button>';
    } else {
      html += '<div></div>';
    }
    html += '</div>';
    return html;
  }

  function _wireNavButtons() {
    var prevBtn = document.getElementById('btnCreatorPrev');
    var nextBtn = document.getElementById('btnCreatorNext');

    if (prevBtn) {
      prevBtn.addEventListener('click', function () {
        _collectFormData();
        _currentStep--;
        _renderStepList();
        _renderStep(_currentStep);
      });
    }
    if (nextBtn) {
      nextBtn.addEventListener('click', function () {
        if (_validateStep(_currentStep)) {
          _collectFormData();
          _currentStep++;
          _renderStepList();
          _renderStep(_currentStep);
        }
      });
    }
  }

  // ---- Collect Form Data ----

  function _collectFormData() {
    // Step 1
    var el;
    el = document.getElementById('cfServiceName');
    if (el) _formData.serviceName = el.value.trim();
    el = document.getElementById('cfVersion');
    if (el) _formData.version = el.value.trim() || '1.0.0';
    el = document.getElementById('cfDescription');
    if (el) _formData.description = el.value.trim();
    el = document.getElementById('cfShortDesc');
    if (el) _formData.shortDescription = el.value.trim();
    el = document.getElementById('cfGroup');
    if (el) _formData.group = el.value.trim();
    el = document.getElementById('cfTag');
    if (el) _formData.tag = el.value.trim();
    el = document.getElementById('cfRoutingKey');
    if (el) _formData.routingKey = el.value.trim();
    el = document.getElementById('cfTransport');
    if (el) _formData.transport = el.value;

    // Step 2: collect methods from DOM
    var methodCards = document.querySelectorAll('.creator-method-card');
    if (methodCards.length > 0) {
      _formData.methods = [];
      methodCards.forEach(function (card) {
        var methodId = parseInt(card.getAttribute('data-method-id'), 10);
        var method = {
          id: methodId,
          name: (card.querySelector('[data-field="name"]') || {}).value || '',
          returnType: (card.querySelector('[data-field="returnType"]') || {}).value || '',
          description: (card.querySelector('[data-field="description"]') || {}).value || '',
          params: []
        };

        card.querySelectorAll('.creator-param-row').forEach(function (row) {
          method.params.push({
            name: (row.querySelector('[data-pfield="name"]') || {}).value || '',
            type: (row.querySelector('[data-pfield="type"]') || {}).value || 'str',
            required: (row.querySelector('[data-pfield="required"]') || {}).value !== 'false'
          });
        });

        _formData.methods.push(method);
      });
    }

    // Step 3
    el = document.getElementById('cfGuiSupport');
    if (el) _formData.guiSupport = el.checked;
    el = document.getElementById('cfGuiHtmlEditor');
    if (el) _formData.customGuiHtml = el.value || null;

    // Step 4
    el = document.getElementById('cfOutputPath');
    if (el) _formData.outputPath = el.value.trim();
  }

  // ---- Validation ----

  function _validateStep(n) {
    if (n === 0) {
      _collectFormData();
      if (!_formData.serviceName) {
        MM.showToast('Validation', 'Service Name is required.', 'warning');
        return false;
      }
      // Enforce PascalCase: first char uppercase
      if (!/^[A-Z]/.test(_formData.serviceName)) {
        MM.showToast('Validation', 'Service Name should start with an uppercase letter (PascalCase).', 'warning');
        return false;
      }
    }
    if (n === 1) {
      _collectFormData();
      for (var i = 0; i < _formData.methods.length; i++) {
        var m = _formData.methods[i];
        if (!m.name) {
          MM.showToast('Validation', 'Method #' + (i + 1) + ' needs a name.', 'warning');
          return false;
        }
      }
    }
    return true;
  }

  // ---- Code Generators (pure JS, no server needed) ----

  function _escPy(str) {
    return (str || '').replace(/\\/g, '\\\\').replace(/'/g, "\\'");
  }

  function _generateServiceClass(d) {
    var snakeName = _toSnakeCase(d.serviceName);
    var routingKey = d.routingKey || ('service.' + snakeName);
    var L = [];

    L.push('import logging');
    L.push('import sys');
    L.push('');
    L.push('from MicroserviceBase.domain.service_base import ServiceBase');
    L.push('from MicroserviceBase.factory import create_transport, create_registry');
    L.push('');
    L.push('');
    L.push('logger = logging.getLogger("' + d.serviceName + '")');
    L.push('');
    L.push('');
    L.push('class ' + d.serviceName + 'Service(ServiceBase):');
    L.push('   """');
    L.push('   ' + (d.description || d.serviceName + ' service.'));
    L.push('   """');
    L.push('');
    L.push('   _SERVICE_INFO = {');
    L.push("      'name': '" + _escPy(d.serviceName) + "',");
    L.push("      'description': '" + _escPy(d.description) + "',");
    L.push("      'shortdesc': '" + _escPy(d.shortDescription) + "',");
    L.push("      'group': '" + _escPy(d.group) + "',");
    L.push("      'tag': '" + _escPy(d.tag) + "',");
    L.push("      'version': '" + _escPy(d.version) + "',");
    L.push("      'routing_key': '" + _escPy(routingKey) + "',");
    L.push("      'gui_support': " + (d.guiSupport ? 'True' : 'False') + ",");
    L.push("      'methods': [],");
    L.push("      'methods_info': {},");
    L.push('   }');

    d.methods.forEach(function (method) {
      var name = method.name.trim();
      if (!name) return;
      var params = ['self'];
      (method.params || []).forEach(function (p) {
        if (p.name.trim()) params.push(p.name.trim());
      });

      L.push('');
      L.push('   def svc_api_' + name + '(' + params.join(', ') + '):');
      L.push('      """');
      L.push('      ' + (method.description || name.replace(/_/g, ' ').charAt(0).toUpperCase() + name.replace(/_/g, ' ').slice(1) + '.'));

      if (method.params && method.params.length > 0) {
        L.push('');
        L.push('      **Arguments:**');
        method.params.forEach(function (p) {
          if (!p.name.trim()) return;
          var cond = p.required !== false ? 'required' : 'optional';
          L.push('');
          L.push('      * ``' + p.name.trim() + '``');
          L.push('');
          L.push('        / *Condition*: ' + cond + ' / *Type*: ' + (p.type || 'str') + ' /');
          L.push('');
          L.push('        ' + p.name.trim().replace(/_/g, ' ').charAt(0).toUpperCase() + p.name.trim().replace(/_/g, ' ').slice(1) + '.');
        });
      }
      if (method.returnType) {
        L.push('');
        L.push('      **Returns:**');
        L.push('');
        L.push('        / *Type*: ' + method.returnType + ' /');
        L.push('');
        L.push('        Result.');
      }
      L.push('      """');
      L.push('      # TODO: Implement ' + name);
      L.push('      pass');
    });

    return L.join('\n') + '\n';
  }

  function _generateMainPy(d) {
    var snakeName = _toSnakeCase(d.serviceName);
    var L = [];

    L.push('import logging');
    L.push('import os');
    L.push('import sys');
    L.push('');
    L.push('from ' + snakeName + ' import ' + d.serviceName + 'Service');
    L.push('from MicroserviceBase.factory import create_transport, create_registry');
    L.push('');
    L.push('logging.basicConfig(');
    L.push("   format='%(asctime)s.%(msecs)03d %(levelname)s [%(name)s] %(message)s',");
    L.push("   datefmt='%H:%M:%S',");
    L.push('   level=logging.INFO,');
    L.push(')');
    L.push("logging.getLogger('pika').setLevel(logging.WARNING)");
    L.push('');
    L.push("logger = logging.getLogger('" + d.serviceName + "')");
    L.push('');
    L.push('');
    L.push('def main():');
    L.push('   """');
    L.push('   Run the ' + d.serviceName + ' service.');
    L.push('   """');

    if (d.transport === 'eventbus') {
      L.push("   config_path = os.path.join(os.path.dirname(__file__), 'config.jsonp')");
      L.push("   transport = create_transport('eventbus', config_path=config_path,");
      L.push("                                service_name='" + d.serviceName + "')");
      L.push("   registry = create_registry('eventbus', config_path=config_path,");
      L.push("                              service_name='" + d.serviceName + "')");
    } else {
      L.push("   transport = create_transport('rabbitmq', cmd_args=sys.argv[1:],");
      L.push("                                service_name='" + d.serviceName + "')");
      L.push("   registry = create_registry('rabbitmq', cmd_args=sys.argv[1:],");
      L.push("                              service_name='" + d.serviceName + "')");
    }

    L.push('');
    L.push('   service = ' + d.serviceName + 'Service(transport=transport, registry=registry)');
    L.push('');
    L.push('   try:');
    L.push('      service.register_service()');
    L.push("      logger.info('Service registered, starting serve()...')");
    L.push('      service.serve()');
    L.push('   except KeyboardInterrupt:');
    L.push("      logger.info('KeyboardInterrupt caught')");
    L.push('   except Exception as ex:');
    L.push("      logger.error('Exception: %s: %s', type(ex).__name__, ex)");
    L.push('   finally:');
    L.push('      try:');
    L.push('         service.unregister_service()');
    L.push('      except Exception:');
    L.push('         pass');
    L.push('      try:');
    L.push('         service.close()');
    L.push('      except Exception:');
    L.push('         pass');
    L.push("      logger.info('Service stopped')");
    L.push('');
    L.push('');
    L.push("if __name__ == '__main__':");
    L.push('   main()');

    return L.join('\n') + '\n';
  }

  function _generateConfigJsonp(d) {
    var routingKey = d.routingKey || ('service.' + _toSnakeCase(d.serviceName));
    var config = {
      transport: 'eventbus',
      routing_key: routingKey,
      xpub_endpoint: 'tcp://localhost:5555',
      xsub_endpoint: 'tcp://localhost:5556'
    };
    return JSON.stringify(config, null, 2) + '\n';
  }

  function _generateGuiHtml(d) {
    var name = _escapeHtml(d.serviceName);
    var subtitle = _escapeHtml(d.shortDescription || d.description || '');
    return '<div class="card">\n' +
      '  <div class="card-header">\n' +
      '    <h5>' + name + '</h5>\n' +
      '    <small class="text-muted">' + subtitle + '</small>\n' +
      '  </div>\n' +
      '  <div class="card-body">\n' +
      '    <p>Custom GUI for ' + name + '.</p>\n' +
      '    <!-- Add your service GUI here -->\n' +
      '  </div>\n' +
      '</div>\n';
  }

  function _generateGuiJs(d) {
    return '/**\n' +
      ' * GUI for ' + d.serviceName + ' service.\n' +
      ' */\n' +
      '(function () {\n' +
      "  'use strict';\n" +
      '\n' +
      '  var MM = window.MicroserviceManager;\n' +
      '\n' +
      '  function load' + d.serviceName + '() {\n' +
      "    console.log('" + d.serviceName + " GUI loaded');\n" +
      '  }\n' +
      '\n' +
      '  function unload' + d.serviceName + '() {\n' +
      "    console.log('" + d.serviceName + " GUI unloaded');\n" +
      '  }\n' +
      '\n' +
      '  // Expose load/unload to global scope for the service loader\n' +
      '  window.load' + d.serviceName + ' = load' + d.serviceName + ';\n' +
      '  window.unload' + d.serviceName + ' = unload' + d.serviceName + ';\n' +
      '\n' +
      '  // Initial load\n' +
      '  load' + d.serviceName + '();\n' +
      '})();\n';
  }

  /**
   * Collect all generated files as an array of {path, content}.
   */
  function _buildFileList(d) {
    var snakeName = _toSnakeCase(d.serviceName);
    var files = [];
    files.push({ path: snakeName + '.py', content: _generateServiceClass(d) });
    files.push({ path: 'main.py', content: _generateMainPy(d) });
    if (d.transport === 'eventbus') {
      files.push({ path: 'config.jsonp', content: _generateConfigJsonp(d) });
    }
    if (d.guiSupport) {
      files.push({ path: 'GUIs/service.html', content: d.customGuiHtml || _generateGuiHtml(d) });
      files.push({ path: 'GUIs/service.js', content: d.customGuiJs || _generateGuiJs(d) });
    }
    return files;
  }

  // ---- Minimal ZIP builder (STORE method, no compression) ----

  function _buildZipBlob(folderName, files) {
    var encoder = new TextEncoder();
    var localHeaders = [];
    var centralEntries = [];
    var offset = 0;

    files.forEach(function (file) {
      var fullPath = folderName + '/' + file.path;
      var nameBytes = encoder.encode(fullPath);
      var dataBytes = encoder.encode(file.content);
      var crc = _crc32(dataBytes);

      // Local file header (30 + name + data)
      var localHeader = new Uint8Array(30 + nameBytes.length + dataBytes.length);
      var view = new DataView(localHeader.buffer);
      view.setUint32(0, 0x04034b50, true);  // signature
      view.setUint16(4, 20, true);           // version needed
      view.setUint16(6, 0, true);            // flags
      view.setUint16(8, 0, true);            // compression (STORE)
      view.setUint16(10, 0, true);           // mod time
      view.setUint16(12, 0, true);           // mod date
      view.setUint32(14, crc, true);         // crc32
      view.setUint32(18, dataBytes.length, true);  // compressed size
      view.setUint32(22, dataBytes.length, true);  // uncompressed size
      view.setUint16(26, nameBytes.length, true);  // name length
      view.setUint16(28, 0, true);           // extra length
      localHeader.set(nameBytes, 30);
      localHeader.set(dataBytes, 30 + nameBytes.length);

      localHeaders.push(localHeader);

      // Central directory entry (46 + name)
      var central = new Uint8Array(46 + nameBytes.length);
      var cv = new DataView(central.buffer);
      cv.setUint32(0, 0x02014b50, true);    // signature
      cv.setUint16(4, 20, true);             // version made by
      cv.setUint16(6, 20, true);             // version needed
      cv.setUint16(8, 0, true);              // flags
      cv.setUint16(10, 0, true);             // compression
      cv.setUint16(12, 0, true);             // mod time
      cv.setUint16(14, 0, true);             // mod date
      cv.setUint32(16, crc, true);           // crc32
      cv.setUint32(20, dataBytes.length, true);  // compressed
      cv.setUint32(24, dataBytes.length, true);  // uncompressed
      cv.setUint16(28, nameBytes.length, true);  // name length
      cv.setUint16(30, 0, true);             // extra length
      cv.setUint16(32, 0, true);             // comment length
      cv.setUint16(34, 0, true);             // disk number
      cv.setUint16(36, 0, true);             // internal attrs
      cv.setUint32(38, 0, true);             // external attrs
      cv.setUint32(42, offset, true);        // local header offset
      central.set(nameBytes, 46);

      centralEntries.push(central);
      offset += localHeader.length;
    });

    // End of central directory
    var centralOffset = offset;
    var centralSize = 0;
    centralEntries.forEach(function (c) { centralSize += c.length; });

    var eocd = new Uint8Array(22);
    var ev = new DataView(eocd.buffer);
    ev.setUint32(0, 0x06054b50, true);       // signature
    ev.setUint16(4, 0, true);                 // disk number
    ev.setUint16(6, 0, true);                 // central dir disk
    ev.setUint16(8, files.length, true);       // entries on disk
    ev.setUint16(10, files.length, true);      // total entries
    ev.setUint32(12, centralSize, true);       // central dir size
    ev.setUint32(16, centralOffset, true);     // central dir offset
    ev.setUint16(20, 0, true);                 // comment length

    var parts = localHeaders.concat(centralEntries, [eocd]);
    return new Blob(parts, { type: 'application/zip' });
  }

  // CRC-32 lookup table
  var _crc32Table = null;
  function _crc32(bytes) {
    if (!_crc32Table) {
      _crc32Table = new Uint32Array(256);
      for (var n = 0; n < 256; n++) {
        var c = n;
        for (var k = 0; k < 8; k++) {
          c = (c & 1) ? (0xEDB88320 ^ (c >>> 1)) : (c >>> 1);
        }
        _crc32Table[n] = c;
      }
    }
    var crc = 0xFFFFFFFF;
    for (var i = 0; i < bytes.length; i++) {
      crc = _crc32Table[(crc ^ bytes[i]) & 0xFF] ^ (crc >>> 8);
    }
    return (crc ^ 0xFFFFFFFF) >>> 0;
  }

  // ---- Submit / Generate ----

  function _submitGenerate(mode) {
    _collectFormData();
    var d = _formData;

    if (mode === 'zip') {
      // Pure client-side: generate files + ZIP, download directly
      try {
        var files = _buildFileList(d);
        var blob = _buildZipBlob(d.serviceName, files);
        var url = URL.createObjectURL(blob);
        var a = document.createElement('a');
        a.href = url;
        a.download = d.serviceName + '.zip';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        MM.showToast('Success', 'ZIP file downloaded.', 'success');
      } catch (err) {
        MM.showToast('Error', 'Failed to generate ZIP: ' + err.message, 'danger');
      }
      return;
    }

    // "Save to Path" mode — requires FastAPI backend
    var payload = {
      service_name: d.serviceName,
      version: d.version,
      description: d.description,
      short_description: d.shortDescription,
      group: d.group,
      tag: d.tag,
      routing_key: d.routingKey || 'service.' + _toSnakeCase(d.serviceName),
      transport: d.transport,
      gui_support: d.guiSupport,
      methods: d.methods.map(function (m) {
        return {
          name: m.name,
          params: (m.params || []).map(function (p) {
            return { name: p.name, type: p.type, required: p.required };
          }),
          return_type: m.returnType,
          description: m.description
        };
      }),
      output_path: d.outputPath,
      custom_gui_html: d.customGuiHtml || '',
      custom_gui_js: d.customGuiJs || ''
    };

    var apiUrl = MM.serviceClient ? MM.serviceClient.apiUrl : '';
    if (!apiUrl || apiUrl === 'null' || apiUrl.indexOf('file:') === 0) {
      // Electron mode: derive bridge URL from settings
      var settings = MM.getSettings ? MM.getSettings() : {};
      var bridgePort = settings.bridgePort || 1112;
      apiUrl = 'http://localhost:' + bridgePort;
    }

    fetch(apiUrl + '/api/scaffold/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    })
      .then(function (resp) {
        if (!resp.ok) throw new Error('Server error: ' + resp.status);
        return resp.json();
      })
      .then(function (data) {
        if (data.status === 'ok') {
          MM.showToast('Success', 'Files saved to ' + data.path, 'success');
        } else {
          MM.showToast('Error', data.error || 'Generation failed.', 'danger');
        }
      })
      .catch(function (err) {
        MM.showToast('Error', 'Failed to save: ' + err.message, 'danger');
      });
  }

  // ---- Public API ----

  function activate() {
    _renderStepList();
    _renderStep(_currentStep);
  }

  function deactivate() {
    _collectFormData();
  }

  // Expose on MM namespace
  MM.serviceCreator = {
    activate: activate,
    deactivate: deactivate
  };

})();
