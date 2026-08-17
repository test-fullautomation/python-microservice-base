#  Copyright 2020-2025 Robert Bosch GmbH
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
# *******************************************************************************
#
# File: nomad_client.py
#
# Initially created by Nguyen Huynh Tri Cuong (MS/EMC51) / Mar 2026.
#
# Description:
#
#   Thin HTTP client for the HashiCorp Nomad v1 API.
#   Handles authentication, blocking queries, and error mapping.
#
# History:
#
# 12.03.2026 / V 0.1 / Nguyen Huynh Tri Cuong
# - Initialize
#
# *******************************************************************************

import logging
import urllib.request
import urllib.error
import urllib.parse
import json
import ssl

logger = logging.getLogger(__name__)


class NomadAPIError(Exception):
   """
Raised when the Nomad API returns a non-2xx response.

**Attributes:**

* ``status_code``

  / *Type*: int /

  HTTP status code returned by Nomad (or ``0`` for transport errors).

* ``url``

  / *Type*: str /

  The URL that was being requested when the error occurred.
   """

   def __init__(self, status_code, message, url=''):
      """
Construct a NomadAPIError.

**Arguments:**

* ``status_code``

  / *Condition*: required / *Type*: int /

  HTTP status code (or ``0`` for network / transport errors).

* ``message``

  / *Condition*: required / *Type*: str /

  Human-readable message body from Nomad (or the network error).

* ``url``

  / *Condition*: optional / *Type*: str / *Default*: '' /

  URL that was being requested.  Included in the formatted message.
      """
      self.status_code = status_code
      self.url = url
      super().__init__(f'Nomad API {status_code}: {message} ({url})')


class NomadClient:
   """
HTTP client for the HashiCorp Nomad v1 API.

Uses only ``urllib`` from the standard library — no external
dependencies.  Supports ACL token authentication and blocking queries
(long-poll).
   """

   def __init__(self, address='http://127.0.0.1:4646', token='',
                namespace='default', timeout=30.0, verify_ssl=True):
      """
Construct a NomadClient bound to a Nomad server.

**Arguments:**

* ``address``

  / *Condition*: optional / *Type*: str / *Default*: 'http://127.0.0.1:4646' /

  Nomad HTTP API endpoint, e.g. ``"http://nomad.example.com:4646"``.

* ``token``

  / *Condition*: optional / *Type*: str / *Default*: '' /

  Nomad ACL token.  Sent in the ``X-Nomad-Token`` header on every
  request when non-empty.

* ``namespace``

  / *Condition*: optional / *Type*: str / *Default*: 'default' /

  Default Nomad namespace.  Forwarded as the ``namespace`` query
  parameter on every request.

* ``timeout``

  / *Condition*: optional / *Type*: float / *Default*: 30.0 /

  Per-request timeout in seconds.

* ``verify_ssl``

  / *Condition*: optional / *Type*: bool / *Default*: True /

  When ``False``, disables certificate verification for HTTPS endpoints
  (use only for dev clusters with self-signed certs).
      """
      self._address = address.rstrip('/')
      self._namespace = namespace
      self._timeout = timeout
      self._token = token
      self._last_index = {}
      self._ssl_context = None
      if not verify_ssl:
         # Deliberate, opt-in escape hatch for dev clusters using
         # self-signed certs; `verify_ssl` defaults to True so the secure
         # path is what you get unless a caller explicitly asks otherwise.
         # Static analysis flags these two lines regardless of the guard
         # (CodeQL, CWE-295 disabled certificate validation) -- that alert
         # is expected here and should be dismissed as "used in tests /
         # intended behaviour" rather than "fixed", since removing the
         # option would break local Nomad setups.
         self._ssl_context = ssl.create_default_context()
         self._ssl_context.check_hostname = False
         self._ssl_context.verify_mode = ssl.CERT_NONE

   def _url(self, path, params=None):
      url = f'{self._address}/v1/{path.lstrip("/")}'
      if params:
         filtered = {k: v for k, v in params.items() if v is not None}
         if filtered:
            url += '?' + urllib.parse.urlencode(filtered)
      return url

   def _request(self, method, path, params=None, body=None):
      if params is None:
         params = {}
      params.setdefault('namespace', self._namespace)

      url = self._url(path, params)
      data = json.dumps(body).encode('utf-8') if body is not None else None
      req = urllib.request.Request(url, data=data, method=method)
      req.add_header('Content-Type', 'application/json')
      if self._token:
         req.add_header('X-Nomad-Token', self._token)

      try:
         resp = urllib.request.urlopen(
            req, timeout=self._timeout, context=self._ssl_context
         )
      except urllib.error.HTTPError as e:
         error_body = e.read().decode('utf-8', errors='replace')
         raise NomadAPIError(e.code, error_body, url) from e
      except urllib.error.URLError as e:
         raise NomadAPIError(0, str(e.reason), url) from e

      # Track blocking query index
      nomad_index = resp.headers.get('X-Nomad-Index')
      if nomad_index:
         self._last_index[path] = nomad_index

      raw = resp.read().decode('utf-8')
      if not raw:
         return {}
      return json.loads(raw)

   def _request_text(self, method, path, params=None):
      if params is None:
         params = {}
      params.setdefault('namespace', self._namespace)

      url = self._url(path, params)
      req = urllib.request.Request(url, method=method)
      if self._token:
         req.add_header('X-Nomad-Token', self._token)

      try:
         resp = urllib.request.urlopen(
            req, timeout=self._timeout, context=self._ssl_context
         )
      except urllib.error.HTTPError as e:
         error_body = e.read().decode('utf-8', errors='replace')
         raise NomadAPIError(e.code, error_body, url) from e
      except urllib.error.URLError as e:
         raise NomadAPIError(0, str(e.reason), url) from e

      return resp.read().decode('utf-8')

   # --- Health -----------------------------------------------------------

   def agent_self(self):
      """GET /v1/agent/self — verify agent connectivity."""
      return self._request('GET', '/agent/self')

   # --- Jobs -------------------------------------------------------------

   def list_jobs(self, prefix=''):
      """GET /v1/jobs — list all jobs (optional prefix filter)."""
      params = {}
      if prefix:
         params['prefix'] = prefix
      return self._request('GET', '/jobs', params=params)

   def get_job(self, job_id):
      """GET /v1/job/:id — read full job specification."""
      return self._request('GET', f'/job/{job_id}')

   def register_job(self, job_spec):
      """POST /v1/jobs — register (create or update) a job."""
      return self._request('POST', '/jobs', body={'Job': job_spec})

   def parse_hcl(self, hcl_text, canonicalize=True):
      """POST /v1/jobs/parse — convert an HCL job spec to JSON.

      Used by the GUI "Submit Job" dialog so users can paste HCL directly
      instead of JSON.  Nomad's own ``nomad job run`` does the same under
      the hood.

      Returns the parsed job dict ready to be wrapped in ``{"Job": ...}``
      and POSTed to ``/v1/jobs``.
      """
      body = {
         'JobHCL': hcl_text,
         'Canonicalize': bool(canonicalize),
      }
      return self._request('POST', '/jobs/parse', body=body)

   def stop_job(self, job_id, purge=False):
      """DELETE /v1/job/:id — stop a job. purge=True removes it entirely."""
      params = {}
      if purge:
         params['purge'] = 'true'
      return self._request('DELETE', f'/job/{job_id}', params=params)

   # --- Allocations ------------------------------------------------------

   def get_allocations(self, job_id):
      """GET /v1/job/:id/allocations — list allocations for a job."""
      return self._request('GET', f'/job/{job_id}/allocations')

   def get_allocation(self, alloc_id):
      """GET /v1/allocation/:id — read a single allocation."""
      return self._request('GET', f'/allocation/{alloc_id}')

   # --- Logs -------------------------------------------------------------

   def get_logs(self, alloc_id, task, log_type='stdout', plain=True,
                origin='end', offset=50000):
      """
GET /v1/client/fs/logs/:alloc_id — read task logs.

Returns plain text when ``plain=True``, otherwise JSON frames.
      """
      params = {
         'task': task,
         'type': log_type,
         'plain': 'true' if plain else 'false',
         'origin': origin,
         'offset': str(offset),
      }
      return self._request_text('GET', f'/client/fs/logs/{alloc_id}',
                                params=params)

   # --- Blocking queries (long-poll) -------------------------------------

   def list_jobs_blocking(self, prefix='', wait='30s'):
      """
GET /v1/jobs with blocking query.

Blocks until the job list changes or ``wait`` expires.
Uses the ``X-Nomad-Index`` from the previous call.
      """
      params = {}
      if prefix:
         params['prefix'] = prefix
      index = self._last_index.get('/jobs', '0')
      params['index'] = index
      params['wait'] = wait
      return self._request('GET', '/jobs', params=params)
