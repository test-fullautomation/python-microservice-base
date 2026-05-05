# Service Template

A ready-to-use template for creating new microservices with MicroserviceBase.

## Quick Start

1. **Copy** this folder and rename it to your service name:

   ```
   cp -r service_template/ my_awesome_service/
   ```

2. **Update `_SERVICE_INFO`** in `main.py`:

   ```python
   _SERVICE_INFO = {
       'name': 'AwesomeService',
       'version': '1.0.0',
       'routing_key': 'service.awesome',
       'description': 'Does awesome things.',
       'shortdesc': 'Awesome!',
       'group': 'my_group',
       ...
   }
   ```

3. **Add your API methods** — any method starting with `svc_api_` is automatically discovered and exposed:

   ```python
   def svc_api_do_something(self, arg1, arg2):
       """
   Description of the method.

   **Arguments:**

   * ``arg1``

     / *Condition*: required / *Type*: str /

     Description of arg1.

   * ``arg2``

     / *Condition*: optional / *Type*: int / *Default*: 0 /

     Description of arg2.

   **Returns:**

     / *Type*: dict /

     Description of return value.
       """
       return {"result": arg1, "count": int(arg2)}
   ```

4. **Run** the service:

   ```
   python -m my_awesome_service --host localhost --port 5672
   ```

   Or via the Local Hub by importing the folder through the Service Manager GUI.

## Folder Structure

```
service_template/
  __main__.py         # Entry point for `python -m <folder>` (required by Local Hub)
  main.py             # Service definition and main() function
  GUIs/               # Optional GUI files (for gui_support: True)
    MyService.html    # GUI panel loaded into Service Manager
    MyService.js      # GUI logic (uses MM namespace)
  README.md           # This file
```

The Local Hub's `_validate_service_structure()` requires either `__main__.py` or `main.py`
in the service folder. This template includes both:

- **`main.py`** — contains the service class, logging setup, and `main()` function.
- **`__main__.py`** — thin wrapper that imports and calls `main()`, enabling
  `python -m <folder>` execution. The hub auto-generates this file during import
  if only `main.py` is present, but including it explicitly avoids surprises.

## Features

### `_SERVICE_INFO` Properties

| Property       | Type   | Default | Description |
|----------------|--------|---------|-------------|
| `name`         | str    | —       | Unique service name (must match class reference) |
| `version`      | str    | `1.0.0` | Semantic version |
| `routing_key`  | str    | —       | RabbitMQ routing key (e.g. `service.myservice`) |
| `description`  | str    | `""`    | Full description |
| `shortdesc`    | str    | `""`    | One-line summary |
| `group`        | str    | `""`    | Sidebar group in the GUI |
| `tag`          | str    | `""`    | Version tag |
| `gui_support`  | bool   | `False` | Serve custom GUI files from `GUIs/` folder |
| `downloadable` | bool   | `False` | Allow ZIP download of service source from GUI |
| `methods`      | list   | `[]`    | Auto-populated at runtime |
| `methods_info` | dict   | `{}`    | Auto-populated at runtime |

### GUI Support

To add a custom GUI panel in the Service Manager:

1. Set `'gui_support': True` in `_SERVICE_INFO`.
2. Place your HTML and JS files in the `GUIs/` subfolder.
3. Name the main HTML file `{ServiceName}.html` (e.g. `MyService.html`).
4. In the JS file, use the `MM` (MicroserviceManager) namespace:

   ```javascript
   var MM = window.MicroserviceManager;

   // Call a service method
   MM.requestService(
     { method: 'svc_api_hello', args: ['World'] },
     'services_request',
     MM.servicesInfor['MyService'].routing_key
   ).then(function (data) {
     console.log(data.result_data);
   });

   // Show a toast notification
   MM.showToast('Title', 'Message', 'success');
   ```

### Downloadable Service

To let users download your service source as a ZIP from the GUI sidebar:

1. Set `'downloadable': True` in `_SERVICE_INFO`.
2. A download icon will appear next to your service in the sidebar.
3. Clicking it downloads the entire service directory as `{ServiceName}.zip`.

### Docstring Format

API methods use a structured docstring format for auto-generated documentation:

```python
def svc_api_example(self, param1, param2):
    """
Short description of the method.

**Arguments:**

* ``param1``

  / *Condition*: required / *Type*: str /

  Description of param1.

* ``param2``

  / *Condition*: optional / *Type*: int / *Default*: 10 /

  Description of param2.

**Returns:**

  / *Type*: str /

  Description of return value.
    """
    return "result"
```

## Prerequisites

- RabbitMQ server running (default: `localhost:5672`)
- MicroserviceBase package installed or available on `sys.path`
