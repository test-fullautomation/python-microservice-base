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
    { label: 'Technology' },
    { label: 'API Methods' },
    { label: 'GUI Support' },      // skipped for C++ or guiType=='none'
    { label: 'Review & Generate' }
  ];

  // Step 3 (GUI Support) is only relevant for Python + HTML/JS GUI.
  // For C++ (QML/WASM/Widget), the GUI is defined by Technology choice.
  function _isStepSkipped(n) {
    if (n === 3) {
      // Skip GUI Support for C++ or no-GUI
      return _formData.language === 'cpp' || _formData.guiType === 'none';
    }
    return false;
  }

  function _nextVisibleStep(from) {
    for (var i = from + 1; i < STEPS.length; i++) {
      if (!_isStepSkipped(i)) return i;
    }
    return from;
  }

  function _prevVisibleStep(from) {
    for (var i = from - 1; i >= 0; i--) {
      if (!_isStepSkipped(i)) return i;
    }
    return from;
  }

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
      // Technology (step 2 — new)
      language: 'python',        // 'python' | 'cpp'
      guiType: 'none',           // 'none' | 'html' | 'qml' | 'wasm' | 'widget'
      clientGrpcKind: 'google',  // 'google' | 'qt' | 'google_vcpkg' — only relevant when guiType != 'none' on C++
      serverGrpcKind: 'msys2',   // 'msys2' | 'vcpkg' — toolchain the server is built with (independent of client)
      genNomad: true,
      genBuildScripts: true,
      genReadme: true,
      genStubs: true,
      vcpkgRoot: '',
      protocPath: '',
      grpcPluginPath: '',
      nomadConsulAddr: 'http://127.0.0.1:8500',
      // Legacy (kept for old v1 flow)
      guiSupport: false,
      guiMode: 'schema',        // 'schema' | 'custom'
      guiSchema: null,
      methods: [],
      importedProtoContent: '',     // non-empty when user imported a .proto file
      importedProtoFileName: '',
      importedServices: [],         // [{name, methods}] when user imported 2+ services
      monorepoLayout: false,        // false = separate folders, true = single project
      layout: '',                   // '' | 'monorepo' | 'multi_proto' — set by import handlers
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
      if (_isStepSkipped(i)) return;  // hide skipped steps from sidebar

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
      case 1: _renderStepTechnology(content); break;
      case 2: _renderStep2(content); break;
      case 3: _renderStep3(content); break;
      case 4: _renderStep4(content); break;
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

  // Step 2: Technology
  function _renderStepTechnology(container) {
    var f = _formData;

    // Determine which GUI options are valid for the selected language
    var pythonGuis = [
      { value: 'none', label: 'None', desc: 'Service only, no GUI' },
      { value: 'html', label: 'HTML / JS', desc: 'Browser-based UI loaded by MicroserviceManagerGUI' },
    ];
    var cppGuis = [
      { value: 'none', label: 'None', desc: 'Service only, no GUI' },
      { value: 'qml', label: 'QML (Qt Quick)', desc: 'Qt Quick UI with preview app + WASM-ready' },
      { value: 'wasm', label: 'WASM (Qt Widgets)', desc: 'Qt Widgets compiled to WebAssembly for in-browser rendering' },
      { value: 'widget', label: 'Widget (Qt Widgets)', desc: 'Native Qt Widgets desktop window' },
    ];

    var guiOptions = (f.language === 'cpp') ? cppGuis : pythonGuis;
    var validTypes = guiOptions.map(function (o) { return o.value; });
    if (validTypes.indexOf(f.guiType) < 0) f.guiType = 'none';

    var guiRadios = guiOptions.map(function (o) {
      var checked = (f.guiType === o.value) ? ' checked' : '';
      return (
        '<div class="form-check mb-2">' +
        '  <input class="form-check-input" type="radio" name="scGuiType" ' +
        '         id="scGui_' + o.value + '" value="' + o.value + '"' + checked + '>' +
        '  <label class="form-check-label" for="scGui_' + o.value + '">' +
        '    <strong>' + _escapeHtml(o.label) + '</strong>' +
        '    <span class="text-muted ms-1">&mdash; ' + _escapeHtml(o.desc) + '</span>' +
        '  </label>' +
        '</div>'
      );
    }).join('');

    container.innerHTML =
      '<h4><i class="bi bi-cpu me-2"></i>Technology</h4>' +
      '<p class="text-muted small">Choose the implementation language, GUI type, and infrastructure files.</p>' +

      '<div class="row">' +
      '<div class="col-md-6">' +

      // Language
      '<div class="mb-4">' +
      '  <label class="form-label fw-bold">Language</label>' +
      '  <div class="btn-group w-100" role="group">' +
      '    <input type="radio" class="btn-check" name="scLanguage" id="scLangPython" value="python"' +
             (f.language === 'python' ? ' checked' : '') + '>' +
      '    <label class="btn btn-outline-primary" for="scLangPython">' +
      '      <i class="bi bi-filetype-py me-1"></i>Python</label>' +
      '    <input type="radio" class="btn-check" name="scLanguage" id="scLangCpp" value="cpp"' +
             (f.language === 'cpp' ? ' checked' : '') + '>' +
      '    <label class="btn btn-outline-primary" for="scLangCpp">' +
      '      <i class="bi bi-filetype-cpp me-1"></i>C++</label>' +
      '  </div>' +
      '</div>' +

      // GUI type
      '<div class="mb-4">' +
      '  <label class="form-label fw-bold">GUI Type</label>' +
      '  <div id="scGuiTypeRadios">' + guiRadios + '</div>' +
      '</div>' +

      // Client gRPC stack — only relevant for C++ projects with a Qt GUI.
      // Server is always Google grpc++ (Qt has no server module); this
      // controls which stack the *client* uses.
      ((f.language === 'cpp' && ['widget', 'wasm', 'qml'].indexOf(f.guiType) >= 0) ?
        '<div class="mb-4" id="scClientGrpcBlock">' +
        '  <label class="form-label fw-bold">Client gRPC Stack</label>' +
        '  <div class="form-check mb-2">' +
        '    <input class="form-check-input" type="radio" name="scClientGrpc" ' +
        '           id="scClientGrpcGoogle" value="google"' +
                 (f.clientGrpcKind === 'google' ? ' checked' : '') + '>' +
        '    <label class="form-check-label" for="scClientGrpcGoogle">' +
        '      <strong>Google grpc++</strong>' +
        '      <span class="text-muted ms-1">&mdash; client lives in <code>client/</code> alongside the server, MSYS2 toolchain</span>' +
        '    </label>' +
        '  </div>' +
        '  <div class="form-check mb-2">' +
        '    <input class="form-check-input" type="radio" name="scClientGrpc" ' +
        '           id="scClientGrpcQt" value="qt"' +
                 (f.clientGrpcKind === 'qt' ? ' checked' : '') + '>' +
        '    <label class="form-check-label" for="scClientGrpcQt">' +
        '      <strong>Qt6::Grpc + Qt6::Protobuf</strong>' +
        '      <span class="text-muted ms-1">&mdash; emits a separate <code>qt_client/</code> project that builds with the Qt-installer MinGW kit (no MSYS2 / Google grpc dependency)</span>' +
        '    </label>' +
        '  </div>' +
        '  <div class="form-check mb-2">' +
        '    <input class="form-check-input" type="radio" name="scClientGrpc" ' +
        '           id="scClientGrpcVcpkg" value="google_vcpkg"' +
                 (f.clientGrpcKind === 'google_vcpkg' ? ' checked' : '') + '>' +
        '    <label class="form-check-label" for="scClientGrpcVcpkg">' +
        '      <strong>Google grpc++ via vcpkg + Qt MinGW</strong>' +
        '      <span class="text-muted ms-1">&mdash; emits <code>qt_client_grpcpp/</code> + <code>triplets/</code> + <code>ports/</code>; vcpkg builds grpc/protobuf/abseil with the Qt-installer MinGW so client AND server share one toolchain. First build ~30&ndash;60&nbsp;min (vcpkg cache); subsequent builds instant.</span>' +
        '    </label>' +
        '  </div>' +
        '  <div class="form-text">Server side: with <em>google</em> or <em>qt</em> the server uses MSYS2-prebuilt grpc; with <em>google_vcpkg</em> the server CMakeLists is also re-targeted to vcpkg.</div>' +

        // Version-support alert — shown only when "qt" is currently selected.
        (f.clientGrpcKind === 'qt' ?
          '<div class="alert alert-warning small mt-2 mb-0 py-2 px-3">' +
          '  <div><i class="bi bi-info-circle me-1"></i>' +
          '    <strong>Qt version requirement for the generated <code>qt_client/</code></strong>' +
          '  </div>' +
          '  <ul class="mb-2 mt-2" style="padding-left: 1.2rem;">' +
          '    <li><strong>Qt 6.8 or later</strong> &mdash; recommended. ' +
                 '<code>Qt6::Grpc</code> and <code>Qt6::Protobuf</code> are stable ' +
                 'and installed by default with the MinGW kit.</li>' +
          '    <li><strong>Qt 6.7</strong> &mdash; works, but Qt GRPC/Protobuf are ' +
                 '<em>Technology Preview</em> and not installed by default. ' +
                 'Open the Qt Maintenance Tool, select 6.7.x &rarr; MinGW 64-bit, ' +
                 'and tick <em>Qt GRPC</em> and <em>Qt Protobuf</em>.</li>' +
          '    <li><strong>Qt 6.6 or earlier</strong> &mdash; not supported (no Qt GRPC module).</li>' +
          '  </ul>' +
          '  <div class="text-muted">' +
          '    Verify with: <code>dir C:\\Qt\\&lt;version&gt;\\mingw_64\\lib\\cmake\\Qt6Grpc</code> ' +
          '    &mdash; the folder must exist or CMake fails with ' +
          '    <em>Failed to find required Qt component "Grpc"</em>.' +
          '  </div>' +
          '</div>'
          : '') +

        // Vcpkg/Qt-MinGW prerequisites alert — shown only when "google_vcpkg" is selected.
        (f.clientGrpcKind === 'google_vcpkg' ?
          '<div class="alert alert-info small mt-2 mb-0 py-2 px-3">' +
          '  <div><i class="bi bi-info-circle me-1"></i>' +
          '    <strong>Prerequisites for <code>google_vcpkg</code></strong>' +
          '  </div>' +
          '  <ul class="mb-2 mt-2" style="padding-left: 1.2rem;">' +
          '    <li><strong>Qt 6.x MinGW 64-bit kit</strong> at <code>C:\\Qt\\Tools\\mingw1310_64\\</code> ' +
                 '(or override via <code>QT_MINGW_BIN</code> env var).</li>' +
          '    <li><strong>vcpkg</strong> cloned + bootstrapped, with <code>VCPKG_ROOT</code> env var set ' +
                 '(<code>git clone https://github.com/microsoft/vcpkg.git C:\\vcpkg</code> &rarr; ' +
                 '<code>C:\\vcpkg\\bootstrap-vcpkg.bat</code> &rarr; <code>setx VCPKG_ROOT C:\\vcpkg</code>).</li>' +
          '    <li><strong>Windows 10 1803+</strong> (for built-in <code>tar.exe</code> used by deploy/export scripts).</li>' +
          '  </ul>' +
          '  <div class="text-muted">' +
          '    First <code>build_qt.bat</code> run takes 30&ndash;60&nbsp;min while vcpkg compiles ' +
          '    boringssl + abseil + protobuf + grpc with Qt&rsquo;s MinGW. Subsequent runs hit the ' +
          '    binary cache (~5&nbsp;sec). Use <code>export_prebuilt.bat</code> to share built ' +
          '    artifacts with other developers so they skip this cost.' +
          '  </div>' +
          '</div>'
          : '') +
        '</div>'
        : '') +

      // Server toolchain — applies to ALL C++ services (regardless of GUI).
      // Independent of client gRPC stack; user can pick any combination.
      ((f.language === 'cpp') ?
        '<div class="mb-4" id="scServerGrpcBlock">' +
        '  <label class="form-label fw-bold">Server Toolchain</label>' +
        '  <div class="form-check mb-2">' +
        '    <input class="form-check-input" type="radio" name="scServerGrpc" ' +
        '           id="scServerGrpcMsys2" value="msys2"' +
                 (f.serverGrpcKind === 'msys2' ? ' checked' : '') + '>' +
        '    <label class="form-check-label" for="scServerGrpcMsys2">' +
        '      <strong>MSYS2 prebuilt</strong>' +
        '      <span class="text-muted ms-1">&mdash; Google grpc++ from MSYS2 (default). Build via <code>build_deploy_msys2.bat</code>. No vcpkg required.</span>' +
        '    </label>' +
        '  </div>' +
        '  <div class="form-check mb-2">' +
        '    <input class="form-check-input" type="radio" name="scServerGrpc" ' +
        '           id="scServerGrpcVcpkg" value="vcpkg"' +
                 (f.serverGrpcKind === 'vcpkg' ? ' checked' : '') + '>' +
        '    <label class="form-check-label" for="scServerGrpcVcpkg">' +
        '      <strong>vcpkg + Qt MinGW</strong>' +
        '      <span class="text-muted ms-1">&mdash; Google grpc++ via vcpkg, built with the Qt-installer MinGW 13.1.0. Emits <code>build_qt_vcpkg.bat</code> + shared <code>triplets/</code> + <code>ports/</code>. Pick this for both client AND server to share one toolchain end-to-end.</span>' +
        '    </label>' +
        '  </div>' +
        ((f.clientGrpcKind === 'google_vcpkg' && f.serverGrpcKind === 'msys2') ?
          '<div class="alert alert-warning small mt-2 mb-0 py-2 px-3">' +
          '  <i class="bi bi-exclamation-triangle me-1"></i>' +
          '  <strong>Mixed toolchains:</strong> client is <code>google_vcpkg</code> but server is <code>msys2</code>. ' +
          '  Wire-protocol still works, but client + server use different libstdc++ ABIs. ' +
          '  Pick <em>vcpkg + Qt MinGW</em> for the server too if you want a unified toolchain.' +
          '</div>'
          : '') +
        ((f.clientGrpcKind !== 'google_vcpkg' && f.serverGrpcKind === 'vcpkg') ?
          '<div class="alert alert-info small mt-2 mb-0 py-2 px-3">' +
          '  <i class="bi bi-info-circle me-1"></i>' +
          '  Server uses vcpkg, client does not. The vcpkg cache populated by ' +
          '  <code>build_qt_vcpkg.bat</code> is reusable later if you switch the client to ' +
          '  <code>google_vcpkg</code> &mdash; same triplet, same overlay-port.' +
          '</div>'
          : '') +
        '</div>'
        : '') +

      '</div>' +  // end col-md-6

      '<div class="col-md-6">' +

      // Infrastructure checkboxes
      '<div class="mb-4">' +
      '  <label class="form-label fw-bold">Infrastructure Files</label>' +
      '  <div class="form-check mb-2">' +
      '    <input class="form-check-input" type="checkbox" id="scGenNomad"' +
             (f.genNomad ? ' checked' : '') + '>' +
      '    <label class="form-check-label" for="scGenNomad">' +
      '      <strong>Nomad job file</strong> <span class="text-muted">(.nomad.hcl)</span>' +
      '      <div class="form-text">Job spec for deploying with HashiCorp Nomad. ' +
      '      Includes dynamic port allocation and Consul registration env vars.</div>' +
      '    </label>' +
      '  </div>' +
      '  <div class="form-check mb-2">' +
      '    <input class="form-check-input" type="checkbox" id="scGenBuild"' +
             (f.genBuildScripts ? ' checked' : '') + '>' +
      '    <label class="form-check-label" for="scGenBuild">' +
      '      <strong>Build scripts</strong> <span class="text-muted">(build.bat / build.sh)</span>' +
      '      <div class="form-text">Cross-platform build scripts that configure CMake with vcpkg ' +
      '      and compile the service.</div>' +
      '    </label>' +
      '  </div>' +
      '  <div class="form-check mb-2">' +
      '    <input class="form-check-input" type="checkbox" id="scGenReadme"' +
             (f.genReadme ? ' checked' : '') + '>' +
      '    <label class="form-check-label" for="scGenReadme">' +
      '      <strong>README.md</strong>' +
      '      <div class="form-text">Auto-generated documentation with build instructions, ' +
      '      method list, and verify commands.</div>' +
      '    </label>' +
      '  </div>' +
      '</div>' +

      '</div>' +  // end col-md-6
      '</div>' +  // end row

      _navButtons(1);

    // Wire language toggle → re-render GUI options
    container.querySelectorAll('input[name="scLanguage"]').forEach(function (radio) {
      radio.addEventListener('change', function () {
        f.language = this.value;
        _renderStepTechnology(container);
      });
    });

    // Wire GUI type — re-render so the Client-grpc block appears/disappears
    // based on whether a GUI is selected.
    container.querySelectorAll('input[name="scGuiType"]').forEach(function (radio) {
      radio.addEventListener('change', function () {
        f.guiType = this.value;
        f.guiSupport = (this.value !== 'none');
        if (this.value === 'none') f.clientGrpcKind = 'google';
        _renderStepTechnology(container);
      });
    });

    // Wire Client gRPC stack (only present when a C++ GUI is selected).
    // Re-render so the version-support alert shows/hides immediately.
    container.querySelectorAll('input[name="scClientGrpc"]').forEach(function (radio) {
      radio.addEventListener('change', function () {
        f.clientGrpcKind = this.value;
        // Convenience: when user picks google_vcpkg for client, suggest
        // vcpkg for server too (one toolchain).  User can still flip
        // back manually.
        if (this.value === 'google_vcpkg' && f.serverGrpcKind === 'msys2') {
          f.serverGrpcKind = 'vcpkg';
        }
        _renderStepTechnology(container);
      });
    });

    // Wire Server toolchain (present whenever language === 'cpp').
    // Re-render so the mixed-toolchain alerts show/hide immediately.
    container.querySelectorAll('input[name="scServerGrpc"]').forEach(function (radio) {
      radio.addEventListener('change', function () {
        f.serverGrpcKind = this.value;
        _renderStepTechnology(container);
      });
    });

    // Wire infrastructure
    var nomadCb = document.getElementById('scGenNomad');
    var buildCb = document.getElementById('scGenBuild');
    var readmeCb = document.getElementById('scGenReadme');
    if (nomadCb) nomadCb.addEventListener('change', function () { f.genNomad = this.checked; });
    if (buildCb) buildCb.addEventListener('change', function () { f.genBuildScripts = this.checked; });
    if (readmeCb) readmeCb.addEventListener('change', function () { f.genReadme = this.checked; });

    _wireNavButtons();
  }

  // Step 3: API Methods (gRPC-style — defines the .proto service)
  function _renderStep2(container) {
    container.innerHTML =
      '<div class="creator-content">' +
        '<div class="creator-header">' +
          '<h4><i class="bi bi-diagram-3 me-2"></i>gRPC Methods</h4>' +
          '<p class="text-muted">Define the RPC methods your service exposes. ' +
          'These become the <code>service</code> block in the generated <code>.proto</code> file. ' +
          'Use <strong>PascalCase</strong> for method names (e.g. <code>GetStatus</code>, not <code>get_status</code>).</p>' +
        '</div>' +
        // Multi-service imported: show summary card in place of editable methods.
        (_formData.importedServices && _formData.importedServices.length > 1 ?
          '<div class="card mb-3 border-success">' +
            '<div class="card-body">' +
              '<h6 class="card-title text-success mb-3">' +
                '<i class="bi bi-collection me-2"></i>' +
                _formData.importedServices.length + ' services will be generated' +
              '</h6>' +
              // Layout selector — three options:
              //   multi_proto: one process hosting all services
              //   monorepo:    one project, N processes (shared codebase)
              //   separate:    N independent projects, one per service
              // Wording is language-aware: C++ uses ".exe", Python uses
              // "Python entry point" so we don't suggest Python services
              // produce native binaries.  Reflects whatever was set
              // during import (picker modal / multi-file auto-default).
              (function () {
                var isCpp = (_formData.language === 'cpp');
                var procWord    = isCpp ? '<code>.exe</code>'  : 'Python entry point';
                var procWordPl  = isCpp ? '<code>.exe</code>s' : 'Python entry points';
                var monorepoBuild = isCpp ? 'CMakeLists' : 'pyproject.toml';
                return (
                '<div class="mb-3 p-2 rounded" style="background:rgba(255,255,255,0.04);">' +
                  '<div class="small text-muted mb-1">Output layout:</div>' +
                  '<div class="form-check">' +
                    '<input class="form-check-input" type="radio" name="creatorStep3Layout" ' +
                      'id="creatorLayoutMultiProto" value="multi_proto"' +
                      (_formData.layout === 'multi_proto' ? ' checked' : '') + '>' +
                    '<label class="form-check-label small" for="creatorLayoutMultiProto">' +
                      '<strong>multi-proto</strong> &mdash; one ' + procWord + ' hosting ' +
                      'all services on one port (one Consul registration). ' +
                      '<span class="text-muted">Best for one logical device.</span>' +
                    '</label>' +
                  '</div>' +
                  '<div class="form-check">' +
                    '<input class="form-check-input" type="radio" name="creatorStep3Layout" ' +
                      'id="creatorLayoutMonorepo" value="monorepo"' +
                      (_formData.layout === 'monorepo' ||
                       (_formData.monorepoLayout && _formData.layout !== 'multi_proto'
                                                && _formData.layout !== 'separate')
                         ? ' checked' : '') + '>' +
                    '<label class="form-check-label small" for="creatorLayoutMonorepo">' +
                      '<strong>monorepo</strong> &mdash; one project, ' +
                      '<em>N</em> ' + procWordPl + ', each with its own port and ' +
                      'Consul registration. ' +
                      '<span class="text-muted">Scale services independently.</span>' +
                    '</label>' +
                  '</div>' +
                  '<div class="form-check">' +
                    '<input class="form-check-input" type="radio" name="creatorStep3Layout" ' +
                      'id="creatorLayoutSeparate" value="separate"' +
                      (_formData.layout === 'separate' ? ' checked' : '') + '>' +
                    '<label class="form-check-label small" for="creatorLayoutSeparate">' +
                      '<strong>separate projects</strong> &mdash; ' +
                      '<em>N</em> independent project folders, one per service. ' +
                      '<span class="text-muted">Each ships separately ' +
                      '(own ' + monorepoBuild + ', build script, Nomad job).</span>' +
                    '</label>' +
                  '</div>' +
                '</div>'
                );
              })() +
              // Per-service grouped method list -- shows which RPC belongs
              // to which service so it's clear how the .proto is structured.
              '<div class="mb-2">' +
                _formData.importedServices.map(function (s) {
                  var methodsHtml = (s.methods && s.methods.length > 0)
                    ? '<ul class="ms-4 mb-2 mt-1" style="font-family: Consolas, monospace; font-size: 0.85em;">' +
                        s.methods.map(function (m) {
                          var paramStr = (m.params || []).map(function (p) {
                            return p.name + ':' + (p.type || 'string');
                          }).join(', ');
                          var stream = m.serverStreaming
                            ? ' <span class="badge bg-warning text-dark" style="font-size: 0.75em;">stream</span>'
                            : '';
                          return '<li>' +
                            'rpc <strong>' + _escapeHtml(m.name) + '</strong>' +
                            '(' + _escapeHtml(paramStr) + ')' +
                            (m.returnType ? ' &rarr; ' + _escapeHtml(m.returnType) : '') +
                            stream +
                          '</li>';
                        }).join('') +
                      '</ul>'
                    : '<div class="ms-4 text-muted small fst-italic">no methods</div>';
                  return '<div class="mb-2">' +
                    '<div class="fw-semibold">' +
                      '<i class="bi bi-box me-1"></i>' + _escapeHtml(s.name) +
                      ' <span class="text-muted small">(' + s.methods.length + ' method' +
                      (s.methods.length === 1 ? '' : 's') + ')</span>' +
                    '</div>' +
                    methodsHtml +
                  '</div>';
                }).join('') +
              '</div>' +
              '<p class="text-muted small mb-2">' +
                'To edit methods, modify the <code>.proto</code>(s) and re-import.' +
              '</p>' +
              '<button class="btn btn-sm btn-outline-secondary" id="btnClearImport">' +
                '<i class="bi bi-x-circle me-1"></i>Clear import &amp; enter manually' +
              '</button>' +
            '</div>' +
          '</div>'
        :
          '<div id="creatorMethodList"></div>' +
          '<div class="d-flex gap-2 mb-3 flex-wrap">' +
            '<button class="btn btn-outline-primary btn-sm" id="btnAddMethod">' +
              '<i class="bi bi-plus-lg me-1"></i>Add Method' +
            '</button>' +
            '<button class="btn btn-outline-secondary btn-sm" id="btnImportProto" ' +
              'title="Load methods from an existing .proto file">' +
              '<i class="bi bi-upload me-1"></i>Import .proto…' +
            '</button>' +
            '<input type="file" id="importProtoFile" accept=".proto,text/plain" ' +
              'multiple style="display:none">' +
            (_formData.importedProtoContent ?
              '<span class="badge bg-success align-self-center">' +
                '<i class="bi bi-check-circle me-1"></i>Imported .proto loaded' +
              '</span>' : '') +
          '</div>'
        ) +

        '<div class="card mb-3">' +
          '<div class="card-body py-2">' +
            '<div class="form-check mb-2">' +
              '<input class="form-check-input" type="checkbox" id="scGenStubs"' +
                (_formData.genStubs ? ' checked' : '') + '>' +
              '<label class="form-check-label" for="scGenStubs">' +
                '<strong>Pre-generate proto stubs</strong>' +
              '</label>' +
            '</div>' +
            '<div id="scStubsPanel"></div>' +
          '</div>' +
        '</div>' +

        _navButtons(2) +
      '</div>';

    // Render the stubs configuration panel based on language
    var stubsPanel = document.getElementById('scStubsPanel');
    var stubsCb = document.getElementById('scGenStubs');

    function _updateStubsPanel() {
      if (!stubsPanel) return;
      var checked = stubsCb && stubsCb.checked;

      if (!checked) {
        stubsPanel.innerHTML =
          '<div class="form-text text-muted">' +
          '  Stubs will not be pre-generated. You\'ll need to run the generation ' +
          '  script manually before building.' +
          '</div>';
        return;
      }

      if (_formData.language === 'python') {
        stubsPanel.innerHTML =
          '<div class="alert alert-success py-2 small mb-0">' +
          '  <i class="bi bi-check-circle me-1"></i>' +
          '  <strong>Python stubs will be generated automatically</strong> by the bridge server ' +
          '  using <code>grpc_tools.protoc</code>. No additional tools required.' +
          '  <div class="mt-1 text-muted">Output: <code>proto/*_pb2.py</code> + <code>proto/*_pb2_grpc.py</code></div>' +
          '</div>';
      } else {
        stubsPanel.innerHTML =
          '<div class="alert alert-warning py-2 small mb-2">' +
          '  <i class="bi bi-exclamation-triangle me-1"></i>' +
          '  <strong>C++ stubs require <code>protoc</code> and <code>grpc_cpp_plugin</code>.</strong>' +
          '  <div class="mt-1">CMake generates stubs at build time, but for pre-generation or ' +
          '  client projects you need the tools installed.</div>' +
          '</div>' +
          '<div class="mb-2">' +
          '  <label class="form-label form-label-sm">' +
          '    <code>VCPKG_ROOT</code>' +
          '    <span class="text-muted ms-1">— vcpkg installation path (tools are auto-detected from here)</span>' +
          '  </label>' +
          '  <input class="form-control form-control-sm" id="scVcpkgRoot" ' +
          '    placeholder="e.g. ~/vcpkg or C:\\vcpkg" ' +
          '    value="' + _escapeHtml(_formData.vcpkgRoot || '') + '">' +
          '</div>' +
          '<div class="mb-2">' +
          '  <label class="form-label form-label-sm">' +
          '    <code>protoc</code> path' +
          '    <span class="text-muted ms-1">— leave empty to auto-detect from VCPKG_ROOT or PATH</span>' +
          '  </label>' +
          '  <input class="form-control form-control-sm" id="scProtocPath" ' +
          '    placeholder="(auto-detect)" ' +
          '    value="' + _escapeHtml(_formData.protocPath || '') + '">' +
          '</div>' +
          '<div class="mb-2">' +
          '  <label class="form-label form-label-sm">' +
          '    <code>grpc_cpp_plugin</code> path' +
          '    <span class="text-muted ms-1">— leave empty to auto-detect</span>' +
          '  </label>' +
          '  <input class="form-control form-control-sm" id="scGrpcPlugin" ' +
          '    placeholder="(auto-detect)" ' +
          '    value="' + _escapeHtml(_formData.grpcPluginPath || '') + '">' +
          '</div>' +
          '<div class="form-text small">' +
          '  <strong>Install tools:</strong> <code>vcpkg install grpc:x64-windows protobuf:x64-windows</code> (Windows) ' +
          '  or <code>vcpkg install grpc:x64-linux protobuf:x64-linux</code> (Linux)' +
          '</div>';

        // Wire C++ tool path inputs
        var vcpkgInput = document.getElementById('scVcpkgRoot');
        var protocInput = document.getElementById('scProtocPath');
        var pluginInput = document.getElementById('scGrpcPlugin');
        if (vcpkgInput) vcpkgInput.addEventListener('change', function () {
          _formData.vcpkgRoot = this.value.trim();
        });
        if (protocInput) protocInput.addEventListener('change', function () {
          _formData.protocPath = this.value.trim();
        });
        if (pluginInput) pluginInput.addEventListener('change', function () {
          _formData.grpcPluginPath = this.value.trim();
        });
      }
    }

    if (stubsCb) {
      stubsCb.addEventListener('change', function () {
        _formData.genStubs = this.checked;
        _updateStubsPanel();
      });
    }
    _updateStubsPanel();

    var methodList = document.getElementById('creatorMethodList');

    // Multi-service mode: only the summary card is rendered, skip method list wiring.
    if (_formData.importedServices && _formData.importedServices.length > 1) {
      var clearBtn = document.getElementById('btnClearImport');
      if (clearBtn) clearBtn.addEventListener('click', function () {
        _formData.importedServices = [];
        _formData.importedProtoContent = '';
        _formData.importedProtoFileName = '';
        _formData.monorepoLayout = false;
        _formData.layout = '';
        _formData.methods = [];
        _renderStep(_currentStep);
      });

      // Inline layout toggle — flips _formData.layout / monorepoLayout
      // so the user can switch between multi_proto (1 .exe), monorepo
      // (N .exe in 1 project), or separate (N independent projects)
      // without re-importing.
      var layoutRadios = document.querySelectorAll(
        'input[name="creatorStep3Layout"]'
      );
      layoutRadios.forEach(function (radio) {
        radio.addEventListener('change', function () {
          _formData.layout = this.value;
          // monorepoLayout is the legacy boolean; keep it consistent.
          _formData.monorepoLayout = (this.value === 'monorepo');
        });
      });
      _wireNavButtons();
      return;
    }

    _formData.methods.forEach(function (method) {
      _appendMethodCard(methodList, method);
    });

    document.getElementById('btnAddMethod').addEventListener('click', function () {
      var method = {
        id: ++_methodIdCounter,
        name: '',
        params: [],
        returnType: 'string',
        description: '',
        serverStreaming: false
      };
      _formData.methods.push(method);
      _appendMethodCard(methodList, method);
    });

    // ---- Import .proto... ----
    var importBtn = document.getElementById('btnImportProto');
    var importFileInput = document.getElementById('importProtoFile');
    importBtn.addEventListener('click', function () { importFileInput.click(); });
    importFileInput.addEventListener('change', function (ev) {
      var files = ev.target.files ? Array.from(ev.target.files) : [];
      if (files.length === 0) return;
      if (files.length === 1) {
        // Single .proto: original flow (may itself contain multiple
        // service blocks → triggers picker modal).
        var f = files[0];
        var reader = new FileReader();
        reader.onload = function (e) { _handleImportedProto(e.target.result, f.name); };
        reader.readAsText(f);
      } else {
        // Multiple .proto files: each file becomes one ServiceBlock with
        // its own proto_file + proto_content.  Forces multi_proto layout
        // (one binary, N gRPC services on one ServerBuilder).
        _handleMultipleProtoImports(files);
      }
      // Clear so the same file(s) can be re-picked.
      importFileInput.value = '';
    });

    _wireNavButtons();
  }

  // ---- Import .proto handling -----------------------------------------

  function _handleImportedProto(protoText, fileName) {
    var apiUrl = MM.serviceClient ? MM.serviceClient.apiUrl : '';
    if (!apiUrl || apiUrl === 'null' || apiUrl.indexOf('file:') === 0) {
      var settings = MM.getSettings ? MM.getSettings() : {};
      var bridgePort = settings.bridgePort || 1112;
      apiUrl = 'http://localhost:' + bridgePort;
    }

    fetch(apiUrl + '/api/scaffold/parse-proto', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ proto_content: protoText })
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.status !== 'ok') {
          MM.showToast('Import failed', data.error || 'Unknown error', 'danger');
          return;
        }
        if (!data.services || data.services.length === 0) {
          MM.showToast('Import failed', 'No services found in the .proto', 'warning');
          return;
        }
        // Warnings are non-fatal hints.
        (data.warnings || []).slice(0, 3).forEach(function (w) {
          MM.showToast('Heads up', w, 'warning');
        });

        if (data.services.length === 1) {
          _formData.monorepoLayout = false;
          _applyImportedServices([data.services[0]], data.proto_package, protoText, fileName);
        } else {
          _showServicePickerModal(data.services, function (pick) {
            if (!pick || !pick.indices || pick.indices.length === 0) return;
            var picked = pick.indices.map(function (i) { return data.services[i]; });
            _formData.monorepoLayout = !!pick.monorepo;
            _formData.layout = pick.layout || (pick.monorepo ? 'monorepo' : '');
            // For multi_proto from a single .proto, all services share the
            // same proto file + content.  _applyImportedServices stamps the
            // shared values onto each ServiceBlock so the generator's
            // multi_proto path can dedup by proto_file.
            _applyImportedServices(picked, data.proto_package, protoText, fileName);
          });
        }
      })
      .catch(function (err) {
        MM.showToast('Import failed', 'Bridge unreachable: ' + err.message, 'danger');
      });
  }

  // Multi-file import: parses N .proto files in parallel, collects every
  // service from every file into _formData.importedServices (each entry
  // carrying its own proto_file + proto_content), and forces
  // layout=multi_proto so the bridge's multi-proto generator emits one
  // binary hosting all services on one ServerBuilder.
  function _handleMultipleProtoImports(files) {
    var apiUrl = MM.serviceClient ? MM.serviceClient.apiUrl : '';
    if (!apiUrl || apiUrl === 'null' || apiUrl.indexOf('file:') === 0) {
      var settings = MM.getSettings ? MM.getSettings() : {};
      var bridgePort = settings.bridgePort || 1112;
      apiUrl = 'http://localhost:' + bridgePort;
    }

    // Read each File into text first (FileReader is async per-file).
    var readPromises = files.map(function (f) {
      return new Promise(function (resolve, reject) {
        var reader = new FileReader();
        reader.onload = function (e) {
          resolve({ name: f.name, content: e.target.result });
        };
        reader.onerror = function () { reject(new Error('Read failed: ' + f.name)); };
        reader.readAsText(f);
      });
    });

    Promise.all(readPromises)
      .then(function (filePayloads) {
        // Parse each file via the bridge.  The bridge endpoint accepts one
        // .proto at a time; we fan out and wait for all results.
        var parsePromises = filePayloads.map(function (fp) {
          return fetch(apiUrl + '/api/scaffold/parse-proto', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ proto_content: fp.content })
          })
            .then(function (r) { return r.json(); })
            .then(function (data) {
              return { file: fp, parsed: data };
            });
        });
        return Promise.all(parsePromises);
      })
      .then(function (results) {
        var allServices = [];
        var failed = [];
        results.forEach(function (r) {
          if (r.parsed.status !== 'ok') {
            failed.push(r.file.name + ': ' + (r.parsed.error || 'parse failed'));
            return;
          }
          if (!r.parsed.services || r.parsed.services.length === 0) {
            failed.push(r.file.name + ': no services found');
            return;
          }
          // Take ALL services from this file (most files have 1; if a file
          // has multiple, each becomes its own ServiceBlock anyway).
          r.parsed.services.forEach(function (svc) {
            allServices.push({
              name: svc.name,
              methods: (svc.methods || []).map(function (m) {
                return {
                  name: m.name,
                  params: (m.params || []).map(function (p) {
                    return { name: p.name, type: p.type || 'string', required: true };
                  }),
                  returnType: m.return_type || 'string',
                  description: m.description || '',
                  serverStreaming: !!m.server_streaming,
                  inputType: m.input_type || '',
                  outputType: m.output_type || ''
                };
              }),
              // multi_proto-only fields: which file this service came from
              // (also drives the proto/<file> path on the backend).
              protoFile: r.file.name,
              protoContent: r.file.content
            });
          });
        });

        if (failed.length > 0) {
          MM.showToast('Some files failed to import',
                       failed.join('  |  '), 'warning');
        }
        if (allServices.length === 0) {
          MM.showToast('Import failed', 'No services parsed from selected files.', 'danger');
          return;
        }

        // Populate _formData for multi_proto layout.
        _formData.importedServices = allServices;
        _formData.layout = 'multi_proto';
        _formData.monorepoLayout = false; // mutually exclusive with multi_proto
        // Drive the wizard's single-service fields from the first service
        // (same convention as single-file multi-service path).
        _formData.methods = allServices[0].methods.slice();
        if (!_formData.serviceName) {
          _formData.serviceName = allServices[0].name;
        }
        // Track aggregated source for the "imported badge" text.
        _formData.importedProtoFileName = files.length + ' files';
        _formData.importedProtoContent = ''; // not used in multi_proto mode

        MM.showToast('Imported',
          allServices.length + ' service(s) from ' + files.length + ' file(s) ' +
          '(layout: multi_proto — one binary on one port).',
          'success');
        _renderStep(_currentStep);
      })
      .catch(function (err) {
        MM.showToast('Import failed', 'Bridge unreachable: ' + err.message, 'danger');
      });
  }

  function _applyImportedServices(services, protoPackage, protoText, fileName) {
    // services is an array of {name, methods[...]}; length >= 1.
    _formData.importedProtoContent = protoText;
    _formData.importedProtoFileName = fileName || '';
    if (protoPackage) _formData.protoPackage = protoPackage;

    // The first service drives the wizard's single-service fields.
    // If > 1, the wizard shows a summary card and disables method editing.
    var primary = services[0];
    // Service name rule:
    //  - Single service  → always use the proto's service name.
    //  - Multi-service   → keep whatever the user already typed in Basic Info
    //                      (that becomes the project/folder name for monorepo
    //                      OR the parent folder for separate-folders mode).
    //                      Fall back to the first service's name only if the
    //                      Basic Info field is empty.
    if (services.length === 1 || !_formData.serviceName) {
      _formData.serviceName = primary.name;
    }
    _formData.methods = (primary.methods || []).map(function (m) {
      return {
        id: ++_methodIdCounter,
        name: m.name,
        params: (m.params || []).map(function (p) {
          return { name: p.name, type: p.type || 'string', required: true };
        }),
        returnType: m.return_type || 'string',
        description: m.description || '',
        serverStreaming: !!m.server_streaming,
        inputType: m.input_type || '',
        outputType: m.output_type || ''
      };
    });

    // Keep the full list so submit can loop generate-v2 per service.
    // For single-file multi-service in multi_proto layout, every service
    // shares the same proto file + content (the generator dedups codegen
    // blocks by proto_file).  protoFile defaults to the imported file's
    // name so the generator writes proto/<fileName> verbatim.
    _formData.importedServices = (services.length > 1) ? services.map(function (s) {
      return {
        name: s.name,
        methods: (s.methods || []).map(function (m) {
          return {
            name: m.name,
            params: (m.params || []).map(function (p) {
              return { name: p.name, type: p.type || 'string', required: true };
            }),
            returnType: m.return_type || 'string',
            description: m.description || '',
            serverStreaming: !!m.server_streaming,
            inputType: m.input_type || '',
            outputType: m.output_type || ''
          };
        }),
        protoFile: fileName || '',
        protoContent: protoText || ''
      };
    }) : [];

    if (services.length === 1) {
      MM.showToast('Import complete',
        primary.name + ' — ' + _formData.methods.length + ' method(s) loaded',
        'success');
    } else {
      var total = services.reduce(function (n, s) { return n + (s.methods ? s.methods.length : 0); }, 0);
      MM.showToast('Import complete',
        services.length + ' services / ' + total + ' methods — each will get its own folder',
        'success');
    }
    // Re-render so the summary badge + any UI changes appear.
    _renderStep(_currentStep);
  }

  function _showServicePickerModal(services, onPick) {
    // Multi-select modal + layout choice.  onPick receives:
    //   { indices: [int], monorepo: bool }
    var rows = services.map(function (s, i) {
      return '<div class="form-check">' +
        '<input class="form-check-input svc-pick" type="checkbox" id="svcPick' + i +
          '" data-idx="' + i + '" checked>' +
        '<label class="form-check-label" for="svcPick' + i + '">' +
          '<strong>' + _escapeHtml(s.name) + '</strong>' +
          '<span class="text-muted ms-2">' +
            (s.methods ? s.methods.length : 0) + ' method(s)</span>' +
        '</label>' +
      '</div>';
    }).join('');

    var html =
      '<div class="modal fade" id="svcPickerModal" tabindex="-1">' +
        '<div class="modal-dialog modal-lg">' +
          '<div class="modal-content">' +
            '<div class="modal-header">' +
              '<h5 class="modal-title">Services found in .proto</h5>' +
              '<button type="button" class="btn-close" data-bs-dismiss="modal"></button>' +
            '</div>' +
            '<div class="modal-body">' +
              '<p class="text-muted">Select the services you want to scaffold:</p>' +
              '<div class="mb-2">' +
                '<button type="button" class="btn btn-link btn-sm p-0 me-3" id="svcPickAll">' +
                  'Select all</button>' +
                '<button type="button" class="btn btn-link btn-sm p-0" id="svcPickNone">' +
                  'Select none</button>' +
              '</div>' +
              '<div id="svcPickerList" class="mb-3">' + rows + '</div>' +

              '<hr>' +
              '<h6 class="mb-2">Output layout</h6>' +
              // Wording is language-aware so we don't tell Python users
              // their service produces a ".exe" or has a "ServerBuilder".
              (function () {
                var isCpp = (_formData.language === 'cpp');
                var procWord     = isCpp ? '.exe'                  : 'Python process';
                var procWordPl   = isCpp ? 'executables'           : 'Python entry points';
                var serverWord   = isCpp ? 'grpc::ServerBuilder'   : 'gRPC server';
                var buildArtifact = isCpp ? 'CMakeLists' : 'pyproject.toml';
                return (
                '<div class="form-check">' +
                  '<input class="form-check-input" type="radio" name="svcLayout" ' +
                    'id="svcLayoutMultiProto" value="multi_proto" checked>' +
                  '<label class="form-check-label" for="svcLayoutMultiProto">' +
                    '<strong>Single ' + (isCpp ? 'binary' : 'process') + ', multiple services</strong> ' +
                    '(<code>multi_proto</code>)<br>' +
                    '<span class="text-muted small">' +
                      'One <code>' + procWord + '</code> hosts every selected service on the ' +
                      '<strong>same</strong> <code>' + serverWord + '</code> &mdash; ' +
                      'one Consul registration, one port, atomic lifecycle.  ' +
                      'Best for one logical device with multiple capability ' +
                      'surfaces (e.g. Power Supply: config + control).' +
                    '</span>' +
                  '</label>' +
                '</div>' +
                '<div class="form-check mt-2">' +
                  '<input class="form-check-input" type="radio" name="svcLayout" ' +
                    'id="svcLayoutMonorepo" value="monorepo">' +
                  '<label class="form-check-label" for="svcLayoutMonorepo">' +
                    '<strong>Single project (monorepo)</strong> &mdash; N ' + procWordPl + '<br>' +
                    '<span class="text-muted small">' +
                      'One project (one <code>' + buildArtifact + '</code>) ' +
                      'that produces N entry points sharing the same <code>.proto</code>.  ' +
                      'Each service has its own port and Consul registration.  ' +
                      'Good for services that may scale independently.' +
                    '</span>' +
                  '</label>' +
                '</div>' +
                '<div class="form-check mt-2">' +
                  '<input class="form-check-input" type="radio" name="svcLayout" ' +
                    'id="svcLayoutSeparate" value="separate">' +
                  '<label class="form-check-label" for="svcLayoutSeparate">' +
                    '<strong>One folder per service</strong> (independent projects)<br>' +
                    '<span class="text-muted small">' +
                      'Each service becomes a self-contained scaffold &mdash; its own ' +
                      '<code>.proto</code>, <code>' + buildArtifact + '</code>, build script, ' +
                      'and Nomad job.  Good for services that ship separately or are owned ' +
                      'by different teams.' +
                    '</span>' +
                  '</label>' +
                '</div>'
                );
              })() +
            '</div>' +
            '<div class="modal-footer">' +
              '<button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>' +
              '<button type="button" class="btn btn-primary" id="svcPickerConfirm">' +
                'Import selected</button>' +
            '</div>' +
          '</div>' +
        '</div>' +
      '</div>';

    var existing = document.getElementById('svcPickerModal');
    if (existing) existing.remove();
    document.body.insertAdjacentHTML('beforeend', html);
    var modalEl = document.getElementById('svcPickerModal');
    var modal = new bootstrap.Modal(modalEl);

    function _gatherPicked() {
      return Array.prototype.slice.call(
        modalEl.querySelectorAll('.svc-pick:checked')
      ).map(function (cb) { return parseInt(cb.getAttribute('data-idx'), 10); });
    }

    modalEl.querySelector('#svcPickAll').addEventListener('click', function () {
      modalEl.querySelectorAll('.svc-pick').forEach(function (cb) { cb.checked = true; });
    });
    modalEl.querySelector('#svcPickNone').addEventListener('click', function () {
      modalEl.querySelectorAll('.svc-pick').forEach(function (cb) { cb.checked = false; });
    });
    modalEl.querySelector('#svcPickerConfirm').addEventListener('click', function () {
      var picked = _gatherPicked();
      if (picked.length === 0) {
        MM.showToast('Pick at least one service', '', 'warning');
        return;
      }
      var layoutRadio = modalEl.querySelector('input[name="svcLayout"]:checked');
      var layoutValue = layoutRadio ? layoutRadio.value : 'multi_proto';
      modal.hide();
      // Keep `monorepo: bool` for back-compat with older callbacks.
      // `layout` is the new authoritative value.
      onPick({
        indices: picked,
        layout: layoutValue,
        monorepo: layoutValue === 'monorepo',
      });
    });
    modalEl.addEventListener('hidden.bs.modal', function () { modalEl.remove(); });
    modal.show();
  }

  function _appendMethodCard(container, method) {
    var card = document.createElement('div');
    card.className = 'creator-method-card';
    card.setAttribute('data-method-id', method.id);

    card.innerHTML =
      '<div class="method-header">' +
        '<h6>' +
          '<code>rpc </code>' +
          '<input type="text" class="form-control form-control-sm d-inline-block" ' +
            'style="width:200px" placeholder="MethodName (PascalCase)" ' +
            'value="' + _escapeHtml(method.name) + '" data-field="name">' +
        '</h6>' +
        '<button class="btn-remove-method" title="Remove method"><i class="bi bi-trash"></i></button>' +
      '</div>' +
      '<div class="row mb-2">' +
        '<div class="col-md-3">' +
          '<label class="form-label form-label-sm">Response type</label>' +
          '<select class="form-select form-select-sm" data-field="returnType">' +
            _protoTypeOptions(method.returnType) +
          '</select>' +
        '</div>' +
        '<div class="col-md-5">' +
          '<label class="form-label form-label-sm">Description</label>' +
          '<input type="text" class="form-control form-control-sm" placeholder="What does this method do?" ' +
            'value="' + _escapeHtml(method.description) + '" data-field="description">' +
        '</div>' +
        '<div class="col-md-4">' +
          '<label class="form-label form-label-sm">Streaming</label>' +
          '<div class="form-check form-switch mt-1">' +
            '<input class="form-check-input" type="checkbox" data-field="serverStreaming"' +
              (method.serverStreaming ? ' checked' : '') + '>' +
            '<label class="form-check-label small">Server streaming</label>' +
          '</div>' +
        '</div>' +
      '</div>' +
      '<label class="form-label form-label-sm fw-semibold">Request fields</label>' +
      '<div class="form-text mb-1">Each field becomes a field in the <code>' +
        _escapeHtml(method.name || 'Method') + 'Request</code> proto message.</div>' +
      '<div class="method-params"></div>' +
      '<button class="btn btn-outline-secondary btn-sm mt-1 btn-add-param">' +
        '<i class="bi bi-plus me-1"></i>Add Field' +
      '</button>';

    // Live-bind method fields to the backing object so state stays
    // in sync even if the user navigates away via the stepper (which
    // would otherwise skip _collectFormData on this card's DOM).
    var nameInput = card.querySelector('[data-field="name"]');
    if (nameInput) nameInput.addEventListener('input', function () {
      method.name = this.value;
    });
    var retSel = card.querySelector('[data-field="returnType"]');
    if (retSel) retSel.addEventListener('change', function () {
      method.returnType = this.value;
    });
    var descIn = card.querySelector('[data-field="description"]');
    if (descIn) descIn.addEventListener('input', function () {
      method.description = this.value;
    });
    var streamIn = card.querySelector('[data-field="serverStreaming"]');
    if (streamIn) streamIn.addEventListener('change', function () {
      method.serverStreaming = this.checked;
    });

    // Wire remove method
    card.querySelector('.btn-remove-method').addEventListener('click', function () {
      _formData.methods = _formData.methods.filter(function (m) { return m.id !== method.id; });
      card.remove();
    });

    // Ensure params array exists, then render existing rows.
    if (!method.params) method.params = [];
    var paramsContainer = card.querySelector('.method-params');
    method.params.forEach(function (param) {
      _appendParamRow(paramsContainer, param, method.params);
    });

    // Wire add param — IMPORTANT: push into method.params so state
    // reflects reality even before _collectFormData runs.
    card.querySelector('.btn-add-param').addEventListener('click', function () {
      var param = { name: '', type: 'string', required: true };
      method.params.push(param);
      _appendParamRow(paramsContainer, param, method.params);
    });

    container.appendChild(card);
  }

  var _PROTO_TYPES = [
    { value: 'string',  label: 'string' },
    { value: 'int32',   label: 'int32' },
    { value: 'int64',   label: 'int64' },
    { value: 'float',   label: 'float' },
    { value: 'double',  label: 'double' },
    { value: 'bool',    label: 'bool' },
    { value: 'bytes',   label: 'bytes' },
  ];

  function _protoTypeOptions(selected) {
    return _PROTO_TYPES.map(function (t) {
      var sel = (t.value === selected || (!selected && t.value === 'string')) ? ' selected' : '';
      return '<option value="' + t.value + '"' + sel + '>' + t.label + '</option>';
    }).join('');
  }

  function _appendParamRow(container, param, paramsArray) {
    var row = document.createElement('div');
    row.className = 'creator-param-row';

    row.innerHTML =
      '<div style="flex:2">' +
        '<input type="text" class="form-control form-control-sm" placeholder="field_name (snake_case)" ' +
          'value="' + _escapeHtml(param.name) + '" data-pfield="name">' +
      '</div>' +
      '<div style="flex:1">' +
        '<select class="form-select form-select-sm" data-pfield="type">' +
          _protoTypeOptions(param.type) +
        '</select>' +
      '</div>' +
      '<div style="flex:1">' +
        '<select class="form-select form-select-sm" data-pfield="required">' +
          '<option value="true"' + (param.required !== false ? ' selected' : '') + '>required</option>' +
          '<option value="false"' + (param.required === false ? ' selected' : '') + '>optional</option>' +
        '</select>' +
      '</div>' +
      '<button class="btn-remove-param" title="Remove field"><i class="bi bi-x-lg"></i></button>';

    // Live-bind row fields to the backing param object.
    var pName = row.querySelector('[data-pfield="name"]');
    if (pName) pName.addEventListener('input', function () {
      param.name = this.value;
    });
    var pType = row.querySelector('[data-pfield="type"]');
    if (pType) pType.addEventListener('change', function () {
      param.type = this.value;
    });
    var pReq = row.querySelector('[data-pfield="required"]');
    if (pReq) pReq.addEventListener('change', function () {
      param.required = this.value !== 'false';
    });

    row.querySelector('.btn-remove-param').addEventListener('click', function () {
      if (paramsArray) {
        var idx = paramsArray.indexOf(param);
        if (idx >= 0) paramsArray.splice(idx, 1);
      }
      row.remove();
    });

    container.appendChild(row);
  }

  // Step 3: GUI Support — Schema Builder + Custom HTML/JS tabs
  function _renderStep3(container) {
    var hasGui = _formData.guiSupport;
    var guiMode = _formData.guiMode || 'schema';
    var htmlContent = _formData.customGuiHtml || _generateGuiHtml(_formData);

    container.innerHTML =
      '<div class="creator-content' + (hasGui ? ' has-gui-preview' : '') + '">' +
        '<div class="creator-header">' +
          '<h4><i class="bi bi-3-circle me-2"></i>GUI Support</h4>' +
          '<p>Choose whether to include a GUI for your service.</p>' +
        '</div>' +
        '<div class="card">' +
          '<div class="card-body">' +
            '<div class="form-check form-switch mb-3">' +
              '<input class="form-check-input" type="checkbox" id="cfGuiSupport"' +
                (hasGui ? ' checked' : '') + '>' +
              '<label class="form-check-label fw-semibold" for="cfGuiSupport">' +
                'Generate GUI' +
              '</label>' +
            '</div>' +
            '<div id="guiPreviewArea" style="display:' + (hasGui ? '' : 'none') + '">' +

              // Mode tabs
              '<ul class="nav nav-tabs mb-3" id="guiModeTabs">' +
                '<li class="nav-item">' +
                  '<button class="nav-link' + (guiMode === 'schema' ? ' active' : '') + '" ' +
                    'data-gui-mode="schema" type="button">' +
                    '<i class="bi bi-diagram-3 me-1"></i>Schema Builder (Recommended)' +
                  '</button>' +
                '</li>' +
                '<li class="nav-item">' +
                  '<button class="nav-link' + (guiMode === 'custom' ? ' active' : '') + '" ' +
                    'data-gui-mode="custom" type="button">' +
                    '<i class="bi bi-code-slash me-1"></i>Custom HTML/JS' +
                  '</button>' +
                '</li>' +
              '</ul>' +

              // Schema Builder tab content
              '<div id="guiSchemaPane" style="display:' + (guiMode === 'schema' ? '' : 'none') + '">' +
                _renderSchemaBuilder() +
              '</div>' +

              // Custom HTML/JS tab content
              '<div id="guiCustomPane" style="display:' + (guiMode === 'custom' ? '' : 'none') + '">' +

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

              // Schema Live Preview (below schema builder)
              '<div id="guiSchemaPreview" class="mt-3" style="display:' + (guiMode === 'schema' ? '' : 'none') + '">' +
                '<label class="form-label fw-semibold form-label-sm">Live Preview</label>' +
                '<div class="gui-preview-render" id="schemaPreviewRender" style="min-height:200px;"></div>' +
              '</div>' +

            '</div>' +
          '</div>' +
        '</div>' +
        _navButtons(3) +
      '</div>';

    // ---- Wire events ----
    var checkbox = document.getElementById('cfGuiSupport');
    var previewArea = document.getElementById('guiPreviewArea');
    var creatorContent = container.querySelector('.creator-content');

    // Tab switching
    var modeTabs = document.querySelectorAll('#guiModeTabs .nav-link');
    var schemaPane = document.getElementById('guiSchemaPane');
    var customPane = document.getElementById('guiCustomPane');
    var schemaPreview = document.getElementById('guiSchemaPreview');

    modeTabs.forEach(function (tab) {
      tab.addEventListener('click', function () {
        modeTabs.forEach(function (t) { t.classList.remove('active'); });
        tab.classList.add('active');
        var mode = tab.getAttribute('data-gui-mode');
        _formData.guiMode = mode;
        schemaPane.style.display = mode === 'schema' ? '' : 'none';
        customPane.style.display = mode === 'custom' ? '' : 'none';
        schemaPreview.style.display = mode === 'schema' ? '' : 'none';
      });
    });

    // Toggle GUI support
    checkbox.addEventListener('change', function () {
      _formData.guiSupport = checkbox.checked;
      previewArea.style.display = checkbox.checked ? '' : 'none';
      if (checkbox.checked) {
        creatorContent.classList.add('has-gui-preview');
        _refreshSchemaPreview();
      } else {
        creatorContent.classList.remove('has-gui-preview');
      }
    });

    // ---- Schema Builder wiring ----
    _wireSchemaBuilder();
    if (hasGui && guiMode === 'schema') {
      _refreshSchemaPreview();
    }

    // ---- Custom HTML/JS wiring ----
    var editor = document.getElementById('cfGuiHtmlEditor');
    var preview = document.getElementById('guiPreviewRender');

    // Debounced live preview
    var _debounceTimer = null;
    if (editor) {
      editor.addEventListener('input', function () {
        clearTimeout(_debounceTimer);
        _debounceTimer = setTimeout(function () {
          preview.innerHTML = editor.value;
        }, 200);
      });
    }

    // HTML file upload
    var htmlFileInput = document.getElementById('cfUploadHtml');
    if (htmlFileInput) {
      htmlFileInput.addEventListener('change', function () {
        if (htmlFileInput.files && htmlFileInput.files[0]) {
          _readFileAsText(htmlFileInput.files[0], function (text) {
            editor.value = text;
            preview.innerHTML = text;
            _formData.customGuiHtml = text;
          });
        }
      });
    }

    // HTML drag-and-drop on editor
    if (editor) {
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
    }

    // JS file upload
    var jsFileInput = document.getElementById('cfUploadJs');
    var jsDropzone = document.getElementById('guiJsDropzone');
    var jsLabel = document.getElementById('guiJsDropzoneLabel');

    if (jsDropzone) {
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
    }

    // Reset to Template
    var resetBtn = document.getElementById('btnResetGuiTemplate');
    if (resetBtn) {
      resetBtn.addEventListener('click', function () {
        var tpl = _generateGuiHtml(_formData);
        editor.value = tpl;
        preview.innerHTML = tpl;
        _formData.customGuiHtml = null;
        _formData.customGuiJs = null;
        _uploadedJsFileName = '';
        jsLabel.innerHTML = 'Drag &amp; drop a .js file here, or click to browse';
      });
    }

    _wireNavButtons();
  }

  // ---- Schema Builder HTML ----

  function _renderSchemaBuilder() {
    var schema = _formData.guiSchema || _buildSchemaFromMethods();
    var sections = schema.sections || [];

    var html = '';

    // Layout selector
    html += '<div class="mb-3">' +
      '<label class="form-label fw-semibold form-label-sm">Layout</label>' +
      '<select class="form-select form-select-sm" id="cfSchemaLayout" style="width:200px;">' +
        '<option value="tabs"' + (schema.layout === 'tabs' ? ' selected' : '') + '>Tabs</option>' +
        '<option value="single"' + (schema.layout === 'single' ? ' selected' : '') + '>Single</option>' +
        '<option value="accordion"' + (schema.layout === 'accordion' ? ' selected' : '') + '>Accordion</option>' +
      '</select>' +
    '</div>';

    // Title / Subtitle
    html += '<div class="row mb-3">' +
      '<div class="col">' +
        '<label class="form-label form-label-sm">Title</label>' +
        '<input type="text" class="form-control form-control-sm" id="cfSchemaTitle" ' +
          'value="' + _escapeHtml(schema.title || _formData.serviceName) + '" placeholder="Service Title">' +
      '</div>' +
      '<div class="col">' +
        '<label class="form-label form-label-sm">Subtitle</label>' +
        '<input type="text" class="form-control form-control-sm" id="cfSchemaSubtitle" ' +
          'value="' + _escapeHtml(schema.subtitle || '') + '" placeholder="Short description">' +
      '</div>' +
    '</div>';

    // Sections
    html += '<div id="schemaSectionsContainer">';
    sections.forEach(function (section, idx) {
      html += _renderSchemaSection(section, idx);
    });
    html += '</div>';

    // Add section button
    html += '<button class="btn btn-outline-primary btn-sm mt-2" id="btnAddSchemaSection">' +
      '<i class="bi bi-plus-lg me-1"></i>Add Section</button>';

    // Export button
    html += '<button class="btn btn-outline-secondary btn-sm mt-2 ms-2" id="btnExportSchema">' +
      '<i class="bi bi-download me-1"></i>Export as JSON</button>';

    return html;
  }

  function _renderSchemaSection(section, idx) {
    var comps = section.components || [];

    var html = '<div class="card mb-2 schema-section-card" data-section-idx="' + idx + '">' +
      '<div class="card-header py-2 d-flex justify-content-between align-items-center">' +
        '<div class="d-flex align-items-center gap-2">' +
          '<input type="text" class="form-control form-control-sm" style="width:200px;" ' +
            'data-sfield="label" value="' + _escapeHtml(section.label || '') + '" placeholder="Section Label">' +
          '<input type="text" class="form-control form-control-sm" style="width:120px;" ' +
            'data-sfield="id" value="' + _escapeHtml(section.id || '') + '" placeholder="Section ID">' +
        '</div>' +
        '<button class="btn btn-outline-danger btn-sm btn-remove-section" title="Remove section">' +
          '<i class="bi bi-trash"></i></button>' +
      '</div>' +
      '<div class="card-body py-2">';

    // Components within the section
    comps.forEach(function (comp, cIdx) {
      html += _renderSchemaComponent(comp, idx, cIdx);
    });

    html += '<button class="btn btn-outline-primary btn-sm btn-add-component" ' +
      'data-section-idx="' + idx + '">' +
      '<i class="bi bi-plus me-1"></i>Add Component</button>';

    html += '</div></div>';
    return html;
  }

  function _renderSchemaComponent(comp, sectionIdx, compIdx) {
    var type = comp.type || 'method-form';
    var html = '<div class="border rounded p-2 mb-2 schema-component-card" ' +
      'data-section-idx="' + sectionIdx + '" data-comp-idx="' + compIdx + '">' +
      '<div class="d-flex justify-content-between align-items-center mb-2">' +
        '<div class="d-flex align-items-center gap-2">' +
          '<select class="form-select form-select-sm" style="width:150px;" data-cfield="type">' +
            '<option value="method-form"' + (type === 'method-form' ? ' selected' : '') + '>Method Form</option>' +
            '<option value="result-table"' + (type === 'result-table' ? ' selected' : '') + '>Result Table</option>' +
            '<option value="text"' + (type === 'text' ? ' selected' : '') + '>Static Text</option>' +
            '<option value="live-status"' + (type === 'live-status' ? ' selected' : '') + '>Live Status</option>' +
          '</select>' +
          '<span class="badge bg-secondary">' + _escapeHtml(type) + '</span>' +
        '</div>' +
        '<button class="btn btn-outline-danger btn-sm btn-remove-component" title="Remove">' +
          '<i class="bi bi-x-lg"></i></button>' +
      '</div>';

    // Type-specific fields
    if (type === 'method-form') {
      html += _renderMethodFormFields(comp);
    } else if (type === 'result-table') {
      html += _renderResultTableFields(comp);
    } else if (type === 'text') {
      html += '<div class="mb-2">' +
        '<textarea class="form-control form-control-sm" data-cfield="content" rows="2" ' +
          'placeholder="Text content">' + _escapeHtml(comp.content || '') + '</textarea></div>';
    } else if (type === 'live-status') {
      html += _renderLiveStatusFields(comp);
    }

    html += '</div>';
    return html;
  }

  function _renderMethodFormFields(comp) {
    var methods = _formData.methods || [];
    var methodOptions = '<option value="">-- Select method --</option>';
    methods.forEach(function (m) {
      var fullName = 'svc_api_' + m.name;
      methodOptions += '<option value="' + _escapeHtml(fullName) + '"' +
        (comp.method === fullName ? ' selected' : '') + '>' + _escapeHtml(fullName) + '</option>';
    });

    var html = '<div class="row mb-2">' +
      '<div class="col-6">' +
        '<label class="form-label form-label-sm">Method</label>' +
        '<select class="form-select form-select-sm" data-cfield="method">' +
          methodOptions +
        '</select>' +
      '</div>' +
      '<div class="col-3">' +
        '<label class="form-label form-label-sm">Submit Label</label>' +
        '<input type="text" class="form-control form-control-sm" data-cfield="submit_label" ' +
          'value="' + _escapeHtml(comp.submit_label || 'Execute') + '">' +
      '</div>' +
      '<div class="col-3">' +
        '<label class="form-label form-label-sm">Result Display</label>' +
        '<select class="form-select form-select-sm" data-cfield="result_display">' +
          '<option value="text"' + (comp.result_display === 'text' ? ' selected' : '') + '>Text</option>' +
          '<option value="json"' + (comp.result_display === 'json' ? ' selected' : '') + '>JSON</option>' +
          '<option value="table"' + (comp.result_display === 'table' ? ' selected' : '') + '>Table</option>' +
          '<option value="image"' + (comp.result_display === 'image' ? ' selected' : '') + '>Image</option>' +
          '<option value="none"' + (comp.result_display === 'none' ? ' selected' : '') + '>None</option>' +
        '</select>' +
      '</div>' +
    '</div>';

    // Fields (auto-populated from method params when method is selected)
    html += '<div class="schema-fields-container" data-cfield="fields">';
    var fields = comp.fields || [];
    fields.forEach(function (f, fIdx) {
      html += _renderSchemaField(f, fIdx);
    });
    html += '</div>';

    return html;
  }

  function _renderSchemaField(field, idx) {
    return '<div class="d-flex gap-2 mb-1 schema-field-row" data-field-idx="' + idx + '">' +
      '<input type="text" class="form-control form-control-sm" style="flex:2;" ' +
        'data-ffield="arg" value="' + _escapeHtml(field.arg || '') + '" placeholder="arg name" readonly>' +
      '<input type="text" class="form-control form-control-sm" style="flex:2;" ' +
        'data-ffield="label" value="' + _escapeHtml(field.label || '') + '" placeholder="Label">' +
      '<select class="form-select form-select-sm" style="flex:1.5;" data-ffield="widget">' +
        '<option value="text"' + (field.widget === 'text' ? ' selected' : '') + '>Text</option>' +
        '<option value="number"' + (field.widget === 'number' ? ' selected' : '') + '>Number</option>' +
        '<option value="textarea"' + (field.widget === 'textarea' ? ' selected' : '') + '>Textarea</option>' +
        '<option value="checkbox"' + (field.widget === 'checkbox' ? ' selected' : '') + '>Checkbox</option>' +
        '<option value="select"' + (field.widget === 'select' ? ' selected' : '') + '>Select</option>' +
        '<option value="file"' + (field.widget === 'file' ? ' selected' : '') + '>File</option>' +
      '</select>' +
      '<input type="text" class="form-control form-control-sm" style="flex:2;" ' +
        'data-ffield="placeholder" value="' + _escapeHtml(field.placeholder || '') + '" placeholder="Placeholder">' +
    '</div>';
  }

  function _renderResultTableFields(comp) {
    var methods = _formData.methods || [];
    var methodOptions = '<option value="">-- Select method --</option>';
    methods.forEach(function (m) {
      var fullName = 'svc_api_' + m.name;
      methodOptions += '<option value="' + _escapeHtml(fullName) + '"' +
        (comp.method === fullName ? ' selected' : '') + '>' + _escapeHtml(fullName) + '</option>';
    });

    return '<div class="row mb-2">' +
      '<div class="col-6">' +
        '<label class="form-label form-label-sm">Method</label>' +
        '<select class="form-select form-select-sm" data-cfield="method">' +
          methodOptions + '</select>' +
      '</div>' +
      '<div class="col-6">' +
        '<label class="form-label form-label-sm">Auto-refresh (ms, 0=off)</label>' +
        '<input type="number" class="form-control form-control-sm" data-cfield="auto_refresh" ' +
          'value="' + (comp.auto_refresh || 0) + '" min="0" step="1000">' +
      '</div>' +
    '</div>';
  }

  function _renderLiveStatusFields(comp) {
    var methods = _formData.methods || [];
    var methodOptions = '<option value="">-- Select method --</option>';
    methods.forEach(function (m) {
      var fullName = 'svc_api_' + m.name;
      methodOptions += '<option value="' + _escapeHtml(fullName) + '"' +
        (comp.method === fullName ? ' selected' : '') + '>' + _escapeHtml(fullName) + '</option>';
    });

    return '<div class="row mb-2">' +
      '<div class="col-4">' +
        '<label class="form-label form-label-sm">Method</label>' +
        '<select class="form-select form-select-sm" data-cfield="method">' +
          methodOptions + '</select>' +
      '</div>' +
      '<div class="col-4">' +
        '<label class="form-label form-label-sm">Interval (ms)</label>' +
        '<input type="number" class="form-control form-control-sm" data-cfield="interval_ms" ' +
          'value="' + (comp.interval_ms || 5000) + '" min="1000" step="1000">' +
      '</div>' +
      '<div class="col-4">' +
        '<label class="form-label form-label-sm">Format</label>' +
        '<input type="text" class="form-control form-control-sm" data-cfield="format" ' +
          'value="' + _escapeHtml(comp.format || '') + '" placeholder="{key}">' +
      '</div>' +
    '</div>';
  }

  // ---- Schema Builder wiring ----

  function _wireSchemaBuilder() {
    // Layout change
    var layoutSel = document.getElementById('cfSchemaLayout');
    if (layoutSel) {
      layoutSel.addEventListener('change', function () { _refreshSchemaPreview(); });
    }

    // Title/subtitle change
    var titleInput = document.getElementById('cfSchemaTitle');
    var subtitleInput = document.getElementById('cfSchemaSubtitle');
    if (titleInput) titleInput.addEventListener('input', function () { _refreshSchemaPreview(); });
    if (subtitleInput) subtitleInput.addEventListener('input', function () { _refreshSchemaPreview(); });

    // Add section
    var addSectionBtn = document.getElementById('btnAddSchemaSection');
    if (addSectionBtn) {
      addSectionBtn.addEventListener('click', function () {
        var schema = _collectSchemaFromDOM();
        schema.sections.push({
          id: 'section_' + (schema.sections.length + 1),
          label: 'New Section',
          components: []
        });
        _formData.guiSchema = schema;
        _rerenderSchemaBuilder();
      });
    }

    // Export as JSON
    var exportBtn = document.getElementById('btnExportSchema');
    if (exportBtn) {
      exportBtn.addEventListener('click', function () {
        var schema = _collectSchemaFromDOM();
        var json = JSON.stringify(schema, null, 2);
        var blob = new Blob([json], { type: 'application/json' });
        var url = URL.createObjectURL(blob);
        var a = document.createElement('a');
        a.href = url;
        a.download = 'gui_schema.json';
        a.click();
        URL.revokeObjectURL(url);
      });
    }

    // Wire section/component events via delegation
    var sectionsContainer = document.getElementById('schemaSectionsContainer');
    if (sectionsContainer) {
      sectionsContainer.addEventListener('click', function (e) {
        var target = e.target.closest('button');
        if (!target) return;

        if (target.classList.contains('btn-remove-section')) {
          var card = target.closest('.schema-section-card');
          if (card) {
            card.remove();
            _refreshSchemaPreview();
          }
        } else if (target.classList.contains('btn-remove-component')) {
          var comp = target.closest('.schema-component-card');
          if (comp) {
            comp.remove();
            _refreshSchemaPreview();
          }
        } else if (target.classList.contains('btn-add-component')) {
          var sIdx = parseInt(target.getAttribute('data-section-idx'), 10);
          var schema = _collectSchemaFromDOM();
          if (schema.sections[sIdx]) {
            schema.sections[sIdx].components.push({
              type: 'method-form',
              method: '',
              fields: [],
              submit_label: 'Execute',
              result_display: 'text'
            });
            _formData.guiSchema = schema;
            _rerenderSchemaBuilder();
          }
        }
      });

      // Detect method selection changes to auto-populate fields
      sectionsContainer.addEventListener('change', function (e) {
        var sel = e.target;
        if (sel.getAttribute('data-cfield') === 'method' &&
            sel.closest('.schema-component-card')) {
          _autoPopulateFieldsForComponent(sel);
        }
        if (sel.getAttribute('data-cfield') === 'type') {
          // Component type changed — rebuild schema and re-render
          var schema = _collectSchemaFromDOM();
          _formData.guiSchema = schema;
          _rerenderSchemaBuilder();
        }
        _refreshSchemaPreview();
      });

      // Any input change triggers preview refresh
      sectionsContainer.addEventListener('input', function () { _refreshSchemaPreview(); });
    }
  }

  function _autoPopulateFieldsForComponent(methodSelect) {
    var compCard = methodSelect.closest('.schema-component-card');
    if (!compCard) return;

    var methodName = methodSelect.value;
    var fieldsContainer = compCard.querySelector('.schema-fields-container');
    if (!fieldsContainer) return;

    // Look up method params from _formData.methods
    var methodDef = _formData.methods.find(function (m) {
      return 'svc_api_' + m.name === methodName;
    });

    fieldsContainer.innerHTML = '';

    if (methodDef && methodDef.params) {
      methodDef.params.forEach(function (p, idx) {
        var TYPE_MAP = { 'int': 'number', 'float': 'number', 'bool': 'checkbox' };
        var widget = TYPE_MAP[p.type] || 'text';
        var label = (p.name || 'arg').split('_').map(function (w) {
          return w.charAt(0).toUpperCase() + w.slice(1);
        }).join(' ');

        fieldsContainer.innerHTML += _renderSchemaField({
          arg: p.name,
          label: label,
          widget: widget,
          placeholder: ''
        }, idx);
      });
    }
  }

  function _rerenderSchemaBuilder() {
    var sectionsContainer = document.getElementById('schemaSectionsContainer');
    if (!sectionsContainer) return;

    var schema = _formData.guiSchema || _buildSchemaFromMethods();
    var html = '';
    (schema.sections || []).forEach(function (section, idx) {
      html += _renderSchemaSection(section, idx);
    });
    sectionsContainer.innerHTML = html;

    // Re-wire delegated events are already on the parent
    _refreshSchemaPreview();
  }

  function _refreshSchemaPreview() {
    var previewEl = document.getElementById('schemaPreviewRender');
    if (!previewEl || !window.SchemaRenderer) return;

    var schema = _collectSchemaFromDOM();
    _formData.guiSchema = schema;

    previewEl.innerHTML = '';
    window.SchemaRenderer.render(schema, previewEl, _formData.serviceName || 'MyService');
  }

  function _collectSchemaFromDOM() {
    var layout = (document.getElementById('cfSchemaLayout') || {}).value || 'tabs';
    var title = (document.getElementById('cfSchemaTitle') || {}).value || '';
    var subtitle = (document.getElementById('cfSchemaSubtitle') || {}).value || '';

    var sections = [];
    var sectionCards = document.querySelectorAll('.schema-section-card');
    sectionCards.forEach(function (card) {
      var section = {
        id: (card.querySelector('[data-sfield="id"]') || {}).value || '',
        label: (card.querySelector('[data-sfield="label"]') || {}).value || '',
        components: []
      };

      card.querySelectorAll('.schema-component-card').forEach(function (compEl) {
        var comp = {};
        comp.type = (compEl.querySelector('[data-cfield="type"]') || {}).value || 'method-form';
        comp.method = (compEl.querySelector('[data-cfield="method"]') || {}).value || '';
        comp.submit_label = (compEl.querySelector('[data-cfield="submit_label"]') || {}).value || 'Execute';
        comp.result_display = (compEl.querySelector('[data-cfield="result_display"]') || {}).value || 'text';
        comp.content = (compEl.querySelector('[data-cfield="content"]') || {}).value || '';
        comp.auto_refresh = parseInt((compEl.querySelector('[data-cfield="auto_refresh"]') || {}).value || '0', 10);
        comp.interval_ms = parseInt((compEl.querySelector('[data-cfield="interval_ms"]') || {}).value || '5000', 10);
        comp.format = (compEl.querySelector('[data-cfield="format"]') || {}).value || '';

        // Collect fields
        comp.fields = [];
        compEl.querySelectorAll('.schema-field-row').forEach(function (row) {
          comp.fields.push({
            arg: (row.querySelector('[data-ffield="arg"]') || {}).value || '',
            label: (row.querySelector('[data-ffield="label"]') || {}).value || '',
            widget: (row.querySelector('[data-ffield="widget"]') || {}).value || 'text',
            placeholder: (row.querySelector('[data-ffield="placeholder"]') || {}).value || ''
          });
        });

        section.components.push(comp);
      });

      sections.push(section);
    });

    return {
      '$schema': 'microservice-gui/1.0',
      service: _formData.serviceName || 'MyService',
      layout: layout,
      title: title,
      subtitle: subtitle,
      sections: sections
    };
  }

  function _buildSchemaFromMethods() {
    // Build an initial schema from the methods defined in Step 2
    var methods = _formData.methods || [];
    var sections = [];

    methods.forEach(function (m) {
      var fields = [];
      (m.params || []).forEach(function (p) {
        var TYPE_MAP = { 'int': 'number', 'float': 'number', 'bool': 'checkbox' };
        var widget = TYPE_MAP[p.type] || 'text';
        var label = (p.name || 'arg').split('_').map(function (w) {
          return w.charAt(0).toUpperCase() + w.slice(1);
        }).join(' ');

        fields.push({
          arg: p.name,
          label: label,
          widget: widget,
          placeholder: ''
        });
      });

      var sectionLabel = (m.name || 'method').split('_').map(function (w) {
        return w.charAt(0).toUpperCase() + w.slice(1);
      }).join(' ');

      sections.push({
        id: 'svc_api_' + m.name,
        label: sectionLabel,
        components: [{
          type: 'method-form',
          method: 'svc_api_' + m.name,
          fields: fields,
          submit_label: 'Execute',
          result_display: 'text'
        }]
      });
    });

    return {
      '$schema': 'microservice-gui/1.0',
      service: _formData.serviceName || 'MyService',
      layout: sections.length > 1 ? 'tabs' : 'single',
      title: _formData.serviceName || 'MyService',
      subtitle: _formData.shortDescription || _formData.description || '',
      sections: sections
    };
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
    var sn = _toSnakeCase(d.serviceName);
    var langLabel = d.language === 'cpp' ? 'C++' : 'Python';
    var guiLabels = { none: 'None', html: 'HTML/JS', qml: 'QML', wasm: 'WASM', widget: 'Widget' };
    var guiLabel = guiLabels[d.guiType] || d.guiType;

    // Is this a multi-service import? Drives title + methods rendering.
    var isMulti = d.importedServices && d.importedServices.length > 1;

    function _renderMethodList(methods) {
      if (!methods || methods.length === 0) {
        return '<div class="text-muted fst-italic">No methods defined</div>';
      }
      return methods.map(function (m) {
        var paramStr = (m.params || []).map(function (p) {
          return p.name + ':' + (p.type || 'string');
        }).join(', ');
        var streaming = m.serverStreaming ? ' <span class="badge bg-warning text-dark">stream</span>' : '';
        return '<div class="creator-summary-method">' +
            '<code>rpc ' + _escapeHtml(m.name) + '(' + _escapeHtml(paramStr) + ')</code>' +
            (m.returnType ? ' &rarr; <code>' + _escapeHtml(m.returnType) + '</code>' : '') +
            streaming +
            (m.description ? '<div class="text-muted small">' + _escapeHtml(m.description) + '</div>' : '') +
          '</div>';
      }).join('');
    }

    // Methods summary — per-service blocks in multi-import mode, flat list otherwise.
    var methodsHtml = '';
    if (isMulti) {
      var totalMethods = d.importedServices.reduce(
        function (n, s) { return n + (s.methods ? s.methods.length : 0); }, 0);
      methodsHtml =
        '<div class="text-muted small mb-2">' +
          totalMethods + ' total across ' + d.importedServices.length + ' services' +
        '</div>' +
        d.importedServices.map(function (svc) {
          return '<div class="mb-3 p-2" style="background:rgba(56,189,248,0.06); border-left:3px solid var(--bs-info,#0dcaf0); border-radius:4px">' +
            '<div class="fw-semibold mb-1">' +
              '<i class="bi bi-box me-1"></i>' + _escapeHtml(svc.name) +
              '<span class="text-muted small ms-2">' +
                svc.methods.length + ' method(s)</span>' +
            '</div>' +
            _renderMethodList(svc.methods) +
          '</div>';
        }).join('');
    } else {
      methodsHtml = _renderMethodList(d.methods);
    }

    // Infra badges
    var infraHtml =
      (d.genNomad ? '<span class="badge bg-success me-1">Nomad HCL</span>' : '') +
      (d.genBuildScripts ? '<span class="badge bg-success me-1">Build scripts</span>' : '') +
      (d.genReadme ? '<span class="badge bg-success me-1">README</span>' : '') +
      (d.genStubs ? '<span class="badge bg-success me-1">Proto stubs</span>' : '');

    container.innerHTML =
      '<div class="creator-content">' +
        '<div class="creator-header">' +
          '<h4><i class="bi bi-check-circle me-2"></i>Review & Generate</h4>' +
          '<p>Verify your service configuration and generate the project files.</p>' +
        '</div>' +

        '<div class="row">' +
        '<div class="col-md-6">' +

        // Summary card
        '<div class="creator-summary">' +
          '<div class="creator-summary-header">' +
            (isMulti
              ? (function () {
                  // Resolve effective layout label.  d.layout is the
                  // authoritative value (multi_proto / monorepo /
                  // separate); fall back to legacy monorepoLayout for
                  // older imports that didn't set d.layout.
                  var effectiveLayout = d.layout
                    || (d.monorepoLayout ? 'monorepo' : 'separate');
                  // Badge wording is language-aware — Python doesn't
                  // produce ".exe" files even though it's still one
                  // process per service.
                  var _isCpp = (d.language === 'cpp');
                  var _procWord = _isCpp ? '.exe' : 'process';
                  var layoutLabelMap = {
                    'multi_proto': { text: 'multi-proto (1 ' + _procWord + ')', cls: 'bg-success' },
                    'monorepo':    { text: 'monorepo (N ' + _procWord + ')',    cls: 'bg-info' },
                    'separate':    { text: 'separate projects',                  cls: 'bg-secondary' },
                  };
                  var meta = layoutLabelMap[effectiveLayout]
                    || layoutLabelMap['separate'];
                  return '<i class="bi bi-collection me-2"></i>' +
                    _escapeHtml(d.serviceName) +
                    ' <span class="badge bg-primary ms-2">' +
                      d.importedServices.length + ' services' +
                    '</span>' +
                    ' <span class="badge ' + meta.cls + ' ms-1">' +
                      meta.text +
                    '</span>';
                })()
              : '<i class="bi bi-box-seam me-2"></i>' +
                _escapeHtml(d.serviceName) + ' v' + _escapeHtml(d.version)) +
          '</div>' +
          '<div class="creator-summary-body">' +
            _summaryRow('Language', '<span class="badge bg-primary">' + langLabel + '</span>') +
            _summaryRow('GUI', '<span class="badge ' +
              (d.guiType !== 'none' ? 'bg-info' : 'bg-secondary') + '">' + guiLabel + '</span>') +
            (d.language === 'cpp' && d.guiType !== 'none'
              ? _summaryRow('Client gRPC',
                  (function () {
                    var k = d.clientGrpcKind || 'google';
                    var cls, label;
                    if (k === 'qt') {
                      cls = 'bg-warning text-dark';
                      label = 'Qt6::Grpc (qt_client/)';
                    } else if (k === 'google_vcpkg') {
                      cls = 'bg-info text-dark';
                      label = 'Google grpc++ via vcpkg + Qt MinGW (qt_client_grpcpp/)';
                    } else {
                      cls = 'bg-success';
                      label = 'Google grpc++ MSYS2 (client/)';
                    }
                    return '<span class="badge ' + cls + '">' + label + '</span>';
                  })())
              : '') +
            (d.language === 'cpp'
              ? _summaryRow('Server toolchain',
                  (function () {
                    var k = d.serverGrpcKind || 'msys2';
                    if (k === 'vcpkg')
                      return '<span class="badge bg-info text-dark">vcpkg + Qt MinGW (build_qt_vcpkg.bat)</span>';
                    return '<span class="badge bg-success">MSYS2 prebuilt (build_deploy_msys2.bat)</span>';
                  })())
              : '') +
            _summaryRow('Description', d.description ? _escapeHtml(d.description) : '<em class="text-muted">none</em>') +
            _summaryRow('Group', d.group ? _escapeHtml(d.group) : '<em class="text-muted">none</em>') +
            _summaryRow('Infrastructure', infraHtml || '<em class="text-muted">none</em>') +
            (isMulti && d.importedProtoFileName
              ? _summaryRow('Imported proto',
                  '<code>' + _escapeHtml(d.importedProtoFileName) + '</code>')
              : '') +
            '<div class="creator-summary-methods">' +
              '<div class="fw-semibold mb-2" style="font-size:0.85rem">' +
                (isMulti ? 'Services &amp; Methods' : 'gRPC Methods (' + d.methods.length + ')') +
              '</div>' +
              methodsHtml +
            '</div>' +
          '</div>' +
        '</div>' +

        '</div>' +  // end col-md-6
        '<div class="col-md-6">' +

        // Nomad HCL configuration (only if genNomad is checked)
        (d.genNomad
          ? '<div class="card mb-3">' +
              '<div class="card-header py-2"><i class="bi bi-hdd-rack me-1"></i>Nomad Job Configuration</div>' +
              '<div class="card-body">' +
                '<div class="mb-2">' +
                  '<label class="form-label form-label-sm">Datacenter' +
                    '<span class="text-muted ms-1">— Nomad datacenter name</span></label>' +
                  '<input class="form-control form-control-sm" id="scNomadDc" value="dc1">' +
                '</div>' +
                '<div class="mb-2">' +
                  '<label class="form-label form-label-sm">Driver' +
                    '<span class="text-muted ms-1">— Nomad task driver</span></label>' +
                  '<select class="form-select form-select-sm" id="scNomadDriver">' +
                    '<option value="raw_exec" selected>raw_exec (direct process, no isolation)</option>' +
                    '<option value="exec">exec (chroot isolation, Linux only)</option>' +
                    '<option value="docker">docker (container)</option>' +
                  '</select>' +
                '</div>' +
                '<div class="mb-2">' +
                  '<label class="form-label form-label-sm">Command path' +
                    '<span class="text-muted ms-1">— absolute path to the service executable/script</span></label>' +
                  '<input class="form-control form-control-sm" id="scNomadCommand" ' +
                    'placeholder="/path/to/' + _escapeHtml(sn) + (d.language === 'cpp' ? '' : '/main.py') + '">' +
                '</div>' +
                '<div class="mb-2">' +
                  '<label class="form-label form-label-sm">Consul address' +
                    '<span class="text-muted ms-1">— where the service registers itself</span></label>' +
                  '<input class="form-control form-control-sm" id="scNomadConsulAddr" ' +
                    'value="http://127.0.0.1:8500" placeholder="http://127.0.0.1:8500">' +
                '</div>' +
                '<div class="row">' +
                  '<div class="col-6 mb-2">' +
                    '<label class="form-label form-label-sm">CPU (MHz)' +
                      '<span class="text-muted ms-1">— resource limit</span></label>' +
                    '<input class="form-control form-control-sm" type="number" id="scNomadCpu" value="100">' +
                  '</div>' +
                  '<div class="col-6 mb-2">' +
                    '<label class="form-label form-label-sm">Memory (MB)' +
                      '<span class="text-muted ms-1">— resource limit</span></label>' +
                    '<input class="form-control form-control-sm" type="number" id="scNomadMem" value="128">' +
                  '</div>' +
                '</div>' +
                '<div class="form-text small mt-0">' +
                  '<code>' + _escapeHtml(sn.toUpperCase() + '_') +
                  'GRPC_PORT</code> and <code>ADVERTISE_ADDR</code> are populated automatically ' +
                  'from Nomad\'s dynamic port allocation. ' +
                  '<code>CONSUL_ADDR</code> uses the address configured above.' +
                '</div>' +
              '</div>' +
            '</div>'
          : '') +

        '</div>' +  // end col-md-6
        '</div>' +  // end row

        // Output actions
        '<div class="creator-output-actions">' +
          '<div class="output-path-group">' +
            '<label class="form-label fw-semibold">Output Path</label>' +
            '<div class="input-group">' +
              '<input type="text" class="form-control" id="cfOutputPath" ' +
                'placeholder="Leave empty for ZIP download" ' +
                'value="' + _escapeHtml(d.outputPath) + '">' +
              (typeof window.electronAPI === 'object'
                ? '<button class="btn btn-outline-secondary" type="button" id="btnBrowsePath">' +
                    '<i class="bi bi-folder2 me-1"></i>Browse...' +
                  '</button>'
                : '') +
            '</div>' +
          '</div>' +
          '<div class="d-flex gap-2 mt-2">' +
            '<button class="btn btn-primary" id="btnDownloadZip">' +
              '<i class="bi bi-file-earmark-zip me-1"></i>Download ZIP' +
            '</button>' +
            '<button class="btn btn-outline-primary" id="btnSavePath" disabled>' +
              '<i class="bi bi-folder2-open me-1"></i>Save to Path' +
            '</button>' +
          '</div>' +
        '</div>' +

        _navButtons(4) +
      '</div>';

    // Wire output path → enable Save to Path
    var pathInput = document.getElementById('cfOutputPath');
    var saveBtn = document.getElementById('btnSavePath');
    pathInput.addEventListener('input', function () {
      saveBtn.disabled = !pathInput.value.trim();
    });
    if (pathInput.value.trim()) saveBtn.disabled = false;

    // Wire Browse button (Electron only)
    var browseBtn = document.getElementById('btnBrowsePath');
    if (browseBtn && window.electronAPI && window.electronAPI.showOpenDialog) {
      browseBtn.addEventListener('click', function () {
        window.electronAPI.showOpenDialog({
          properties: ['openDirectory', 'createDirectory'],
          title: 'Select output folder for ' + d.serviceName
        }).then(function (result) {
          if (result && result.filePaths && result.filePaths.length > 0) {
            pathInput.value = result.filePaths[0];
            saveBtn.disabled = false;
          }
        });
      });
    }

    // Wire generate buttons
    document.getElementById('btnDownloadZip').addEventListener('click', function () {
      _submitGenerate('zip');
    });
    saveBtn.addEventListener('click', function () {
      _formData.outputPath = pathInput.value.trim();
      // Collect Nomad config overrides if present
      _collectNomadConfig();
      _submitGenerate('path');
    });

    _wireNavButtons();
  }

  function _collectNomadConfig() {
    // Read Nomad HCL fields into formData so the backend can use them.
    // If these fields don't exist in the DOM (genNomad is false), skip.
    var el;
    el = document.getElementById('scNomadDc');
    if (el) _formData.nomadDc = el.value.trim() || 'dc1';
    el = document.getElementById('scNomadDriver');
    if (el) _formData.nomadDriver = el.value || 'raw_exec';
    el = document.getElementById('scNomadCommand');
    if (el) _formData.nomadCommand = el.value.trim();
    el = document.getElementById('scNomadCpu');
    if (el) _formData.nomadCpu = parseInt(el.value, 10) || 100;
    el = document.getElementById('scNomadMem');
    if (el) _formData.nomadMem = parseInt(el.value, 10) || 128;
    el = document.getElementById('scNomadConsulAddr');
    if (el) _formData.nomadConsulAddr = el.value.trim() || 'http://127.0.0.1:8500';
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
        _currentStep = _prevVisibleStep(_currentStep);
        _renderStepList();
        _renderStep(_currentStep);
      });
    }
    if (nextBtn) {
      nextBtn.addEventListener('click', function () {
        if (_validateStep(_currentStep)) {
          _collectFormData();
          _currentStep = _nextVisibleStep(_currentStep);
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

    // Step 3 (was 2): collect methods from DOM
    var methodCards = document.querySelectorAll('.creator-method-card');
    if (methodCards.length > 0) {
      _formData.methods = [];
      methodCards.forEach(function (card) {
        var methodId = parseInt(card.getAttribute('data-method-id'), 10);
        var streamingEl = card.querySelector('[data-field="serverStreaming"]');
        var method = {
          id: methodId,
          name: (card.querySelector('[data-field="name"]') || {}).value || '',
          returnType: (card.querySelector('[data-field="returnType"]') || {}).value || 'string',
          description: (card.querySelector('[data-field="description"]') || {}).value || '',
          serverStreaming: streamingEl ? streamingEl.checked : false,
          params: []
        };

        card.querySelectorAll('.creator-param-row').forEach(function (row) {
          method.params.push({
            name: (row.querySelector('[data-pfield="name"]') || {}).value || '',
            type: (row.querySelector('[data-pfield="type"]') || {}).value || 'string',
            required: (row.querySelector('[data-pfield="required"]') || {}).value !== 'false'
          });
        });

        _formData.methods.push(method);
      });
    }

    // Step 3
    el = document.getElementById('cfGuiSupport');
    if (el) _formData.guiSupport = el.checked;
    // Determine active GUI mode
    var activeTab = document.querySelector('#guiModeTabs .nav-link.active');
    if (activeTab) _formData.guiMode = activeTab.getAttribute('data-gui-mode') || 'schema';
    // Collect schema from DOM if in schema mode
    if (_formData.guiMode === 'schema' && document.getElementById('schemaSectionsContainer')) {
      _formData.guiSchema = _collectSchemaFromDOM();
    }
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
    // Step 1 (Technology) — no required fields, always valid.

    if (n === 2) {
      _collectFormData();
      // Multi-service import: proto-driven, no in-wizard method editing.
      if (_formData.importedServices && _formData.importedServices.length > 1) {
        return true;
      }
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
      if (d.guiMode === 'schema' && d.guiSchema) {
        files.push({ path: 'GUIs/gui_schema.json', content: JSON.stringify(d.guiSchema, null, 2) });
      } else {
        files.push({ path: 'GUIs/service.html', content: d.customGuiHtml || _generateGuiHtml(d) });
        files.push({ path: 'GUIs/service.js', content: d.customGuiJs || _generateGuiJs(d) });
      }
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

    // Resolve bridge URL once.
    var apiUrl = MM.serviceClient ? MM.serviceClient.apiUrl : '';
    if (!apiUrl || apiUrl === 'null' || apiUrl.indexOf('file:') === 0) {
      var settings = MM.getSettings ? MM.getSettings() : {};
      var bridgePort = settings.bridgePort || 1112;
      apiUrl = 'http://localhost:' + bridgePort;
    }

    // ---- Multi-proto import: single POST, backend generates ONE binary
    //                          hosting N gRPC services on one ServerBuilder.
    if (d.importedServices && d.importedServices.length > 1
        && d.layout === 'multi_proto') {
      var mpPayload = _buildGeneratePayload(d, d.serviceName, d.methods);
      mpPayload.monorepo = false;
      mpPayload.layout = 'multi_proto';
      mpPayload.services = d.importedServices.map(function (svc) {
        return {
          name: svc.name,
          // Per-service .proto location + verbatim content (multi_proto only).
          // The generator writes proto/<proto_file> with this exact text so
          // imported messages, comments, and packages are preserved.
          proto_file: svc.protoFile || '',
          proto_content: svc.protoContent || '',
          methods: (svc.methods || []).map(function (m) {
            return {
              name: m.name,
              params: (m.params || []).map(function (p) {
                return { name: p.name, type: p.type || 'string',
                         required: p.required !== false, description: p.description || '' };
              }),
              return_type: m.returnType || 'string',
              description: m.description || '',
              server_streaming: !!m.serverStreaming,
              input_type: m.inputType || '',
              output_type: m.outputType || ''
            };
          })
        };
      });
      fetch(apiUrl + '/api/scaffold/generate-v2', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(mpPayload)
      })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          if (data.status === 'ok') {
            MM.showToast('Success',
              'Multi-proto binary with ' + d.importedServices.length +
              ' services saved to ' + data.path, 'success');
          } else {
            MM.showToast('Error', data.error || 'Generation failed.', 'danger');
          }
        })
        .catch(function (err) {
          MM.showToast('Error', 'Failed to save: ' + err.message, 'danger');
        });
      return;
    }

    // ---- Monorepo import: single POST, backend generates one project folder
    //                       with N executables.
    if (d.importedServices && d.importedServices.length > 1 && d.monorepoLayout) {
      var payload = _buildGeneratePayload(d, d.serviceName, d.methods);
      payload.monorepo = true;
      payload.services = d.importedServices.map(function (svc) {
        return {
          name: svc.name,
          methods: (svc.methods || []).map(function (m) {
            return {
              name: m.name,
              params: (m.params || []).map(function (p) {
                return { name: p.name, type: p.type || 'string',
                         required: p.required !== false, description: p.description || '' };
              }),
              return_type: m.returnType || 'string',
              description: m.description || '',
              server_streaming: !!m.serverStreaming,
              input_type: m.inputType || '',
              output_type: m.outputType || ''
            };
          })
        };
      });
      fetch(apiUrl + '/api/scaffold/generate-v2', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          if (data.status === 'ok') {
            MM.showToast('Success',
              'Monorepo with ' + d.importedServices.length + ' services saved to ' + data.path,
              'success');
          } else {
            MM.showToast('Error', data.error || 'Generation failed.', 'danger');
          }
        })
        .catch(function (err) {
          MM.showToast('Error', 'Failed to save: ' + err.message, 'danger');
        });
      return;
    }

    // ---- Separate-folders multi-service import: loop N POSTs.
    // Each service becomes its own independent project.  In multi-file
    // mode, every service carries its own protoContent (set by the
    // multi-file import handler), so each generated project preserves
    // exactly the .proto file it was imported from.  In single-file
    // mode, all services share the imported proto (handled implicitly
    // by _buildGeneratePayload reading d.importedProtoContent).
    if (d.importedServices && d.importedServices.length > 1) {
      var results = { ok: 0, fail: 0, errors: [] };
      var chain = Promise.resolve();
      d.importedServices.forEach(function (svc) {
        chain = chain.then(function () {
          var p = _buildGeneratePayload(d, svc.name, svc.methods);
          // Multi-file import: per-service .proto content overrides the
          // shared d.importedProtoContent (which is empty in multi-file mode).
          if (svc.protoContent) {
            p.proto_content_override = svc.protoContent;
          }
          return fetch(apiUrl + '/api/scaffold/generate-v2', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(p)
          })
            .then(function (r) { return r.json(); })
            .then(function (data) {
              if (data.status === 'ok') results.ok++;
              else { results.fail++; results.errors.push(svc.name + ': ' + (data.error || '')); }
            })
            .catch(function (err) {
              results.fail++;
              results.errors.push(svc.name + ': ' + err.message);
            });
        });
      });
      chain.then(function () {
        if (results.fail === 0) {
          MM.showToast('Success',
            results.ok + ' services generated in ' + d.outputPath, 'success');
        } else {
          MM.showToast('Partial: ' + results.ok + ' ok / ' + results.fail + ' failed',
            results.errors.join('; '), 'warning');
        }
      });
      return;
    }

    // Single-service path (manual wizard or single imported service).
    var payload = _buildGeneratePayload(d, d.serviceName, d.methods);

    fetch(apiUrl + '/api/scaffold/generate-v2', {
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
          var msg = data.file_count
            ? data.file_count + ' files saved to ' + data.path
            : 'Files saved to ' + data.path;
          MM.showToast('Success', msg, 'success');
          _warnIfStubsRequestedButMissing(d, data);
        } else {
          MM.showToast('Error', data.error || 'Generation failed.', 'danger');
        }
      })
      .catch(function (err) {
        MM.showToast('Error', 'Failed to save: ' + err.message, 'danger');
      });
  }

  // Build a generate-v2 POST payload. Factored out so multi-service
  // imports can loop and pass a per-service name + methods while reusing
  // every other wizard field (language, GUI, Nomad, paths, …).
  function _buildGeneratePayload(d, serviceName, methods) {
    return {
      service_name: serviceName,
      version: d.version,
      description: d.description,
      short_desc: d.shortDescription,
      group: d.group,
      tag: d.tag,
      language: d.language || 'python',
      gui_type: d.guiType || 'none',
      server_grpc_kind: (d.language === 'cpp') ? (d.serverGrpcKind || 'msys2') : 'msys2',
      client_grpc_kind: (d.guiType && d.guiType !== 'none' && d.language === 'cpp')
        ? (d.clientGrpcKind || 'google') : 'google',
      gen_nomad: d.genNomad !== false,
      gen_build_scripts: d.genBuildScripts !== false,
      gen_readme: d.genReadme !== false,
      gen_stubs: d.genStubs !== false,
      vcpkg_root: d.vcpkgRoot || '',
      protoc_path: d.protocPath || '',
      grpc_plugin_path: d.grpcPluginPath || '',
      nomad_dc: d.nomadDc || 'dc1',
      nomad_driver: d.nomadDriver || 'raw_exec',
      nomad_command: d.nomadCommand || '',
      nomad_cpu: d.nomadCpu || 100,
      nomad_mem: d.nomadMem || 128,
      nomad_consul_addr: d.nomadConsulAddr || 'http://127.0.0.1:8500',
      methods: (methods || []).map(function (m) {
        return {
          name: m.name,
          params: (m.params || []).map(function (p) {
            return { name: p.name, type: p.type || 'string',
                     required: p.required !== false, description: p.description || '' };
          }),
          return_type: m.returnType || 'string',
          description: m.description || '',
          server_streaming: !!m.serverStreaming,
          input_type: m.inputType || '',
          output_type: m.outputType || ''
        };
      }),
      output_path: d.outputPath,
      proto_content_override: d.importedProtoContent || '',
      proto_package: d.protoPackage || ''
    };
  }

  // ---- Post-save sanity check ----

  /**
   * If the user ticked "Pre-generate proto stubs" and language=python,
   * verify the bridge actually wrote *_pb2.py / *_pb2_grpc.py.  If not,
   * surface a yellow toast pointing them at the diagnostic command.
   * The bridge logs the real reason (grpcio-tools missing, protoc
   * non-zero, etc.) at WARNING level — the toast just tells the user
   * where to look.
   */
  function _warnIfStubsRequestedButMissing(d, data) {
    if (!d || d.genStubs === false) return;
    if ((d.language || 'python') !== 'python') return;
    var files = (data && data.files) || [];
    var hasPb2     = files.some(function (p) { return /\/.+_pb2\.py$/.test(p); });
    var hasPb2Grpc = files.some(function (p) { return /\/.+_pb2_grpc\.py$/.test(p); });
    if (hasPb2 && hasPb2Grpc) return;
    MM.showToast(
      'Proto stubs not generated',
      'You ticked "Pre-generate proto stubs" but the bridge did not ' +
      'produce *_pb2.py / *_pb2_grpc.py.  Most common cause: ' +
      'grpcio-tools is not installed in the bridge\'s Python — fix with ' +
      '`pip install grpcio-tools` in that environment.  Check the ' +
      'bridge log (launcher.log) for the exact reason, or run ' +
      '`python scripts/generate_protos.py` from inside the generated ' +
      'service folder.',
      'warning'
    );
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
