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
# File: nomad_hub_adapter.py
#
# Initially created by Nguyen Huynh Tri Cuong (MS/EMC51) / Mar 2026.
#
# Description:
#
#   HubManagerPort implementation backed by the HashiCorp Nomad HTTP API.
#   Translates hub operations into Nomad job lifecycle calls.
#
# History:
#
# 12.03.2026 / V 0.1 / Nguyen Huynh Tri Cuong
# - Initialize
#
# *******************************************************************************

import logging
import threading
import time

from ...ports.hub_manager import HubManagerPort
from .nomad_client import NomadClient, NomadAPIError

logger = logging.getLogger(__name__)

# Prefix for all Nomad jobs created by this adapter — prevents collision
# with jobs managed outside DevAtServ.
JOB_PREFIX = 'das-'


def _job_id(name):
   """Convert a human-friendly service name to a Nomad-safe job ID."""
   return JOB_PREFIX + name.lower().replace(' ', '-')


def _service_name_from_job(job):
   """Extract the original service name from a Nomad job."""
   meta = (job.get('Meta') or {})
   return meta.get('das_service_name', job.get('Name', job.get('ID', '')))


class NomadHubAdapter(HubManagerPort):
   """
HubManagerPort implementation that manages services as Nomad jobs.

Each service config is translated into a Nomad job spec using the
``raw_exec`` driver (Python processes, no Docker required).
   """

   def __init__(self, address='http://127.0.0.1:4646', token='',
                namespace='default', datacenter='dc1',
                on_status_change=None):
      self._client = NomadClient(
         address=address, token=token, namespace=namespace
      )
      self._datacenter = datacenter
      self._running = False
      self._mode = 'nomad'
      self._configs = {}
      self._last_status = None
      self._on_status_change = on_status_change
      self._poll_thread = None

   # --- Lifecycle --------------------------------------------------------

   def start_hub(self, mode='standalone', **kwargs):
      if self._running:
         return {'status': 'already running'}

      try:
         agent_info = self._client.agent_self()
         server_name = agent_info.get('member', {}).get('Name', 'unknown')
      except NomadAPIError as e:
         return {'status': 'error',
                 'message': f'Cannot connect to Nomad: {e}'}

      self._running = True

      # Start background poll for status changes
      self._poll_thread = threading.Thread(
         target=self._poll_loop, daemon=True, name='nomad-poll'
      )
      self._poll_thread.start()

      logger.info('NomadHubAdapter connected to %s (server: %s)',
                  self._client._address, server_name)
      return {'status': 'started', 'mode': 'nomad',
              'nomad_server': server_name}

   def stop_hub(self):
      self._running = False
      if self._poll_thread:
         self._poll_thread.join(timeout=5)
         self._poll_thread = None
      logger.info('NomadHubAdapter disconnected')
      return {'status': 'stopped'}

   # --- Status -----------------------------------------------------------

   def get_status(self):
      if not self._running:
         return {
            'running': False, 'mode': 'nomad',
            'processes': [], 'configured_processes': [],
            'process_configs': {},
         }

      processes = []
      try:
         jobs = self._client.list_jobs(prefix=JOB_PREFIX)
         for job in jobs:
            name = _service_name_from_job(job)
            status = job.get('Status', 'unknown')
            alloc_info = self._get_latest_alloc(job['ID'])
            processes.append({
               'name': name,
               'state': self._map_nomad_status(status),
               'pid': alloc_info.get('alloc_id', ''),
               'nomad_job_id': job['ID'],
               'nomad_status': status,
               'nomad_type': job.get('Type', ''),
               'task_group': alloc_info.get('task_group', ''),
               'node': alloc_info.get('node', ''),
            })
      except NomadAPIError as e:
         logger.error('Failed to list Nomad jobs: %s', e)

      return {
         'running': self._running,
         'mode': 'nomad',
         'processes': processes,
         'configured_processes': list(self._configs.keys()),
         'process_configs': self._configs,
      }

   # --- Process control --------------------------------------------------

   def start_processes(self, names):
      results = {}
      for name in names:
         config = self._configs.get(name)
         if not config:
            results[name] = {
               'success': False,
               'message': f'No config found for "{name}"',
            }
            continue
         results[name] = self._register_and_run(name, config)
      return results

   def stop_processes(self, names, force=False):
      results = {}
      for name in names:
         job_id = _job_id(name)
         try:
            self._client.stop_job(job_id, purge=False)
            results[name] = {
               'success': True,
               'message': f'Job {job_id} stopped',
            }
         except NomadAPIError as e:
            results[name] = {
               'success': False,
               'message': f'Failed to stop job {job_id}: {e}',
            }
      return results

   # --- Config management ------------------------------------------------

   def get_config(self):
      return dict(self._configs)

   def add_config(self, name, config):
      if name in self._configs:
         return {'success': False,
                 'message': f'Config "{name}" already exists'}
      self._configs[name] = config
      return {'success': True, 'message': f'Config "{name}" added'}

   def update_config(self, name, config):
      if name not in self._configs:
         return {'success': False,
                 'message': f'Config "{name}" not found'}
      self._configs[name] = config
      return {'success': True, 'message': f'Config "{name}" updated'}

   def remove_config(self, name):
      if name not in self._configs:
         return {'success': False,
                 'message': f'Config "{name}" not found'}
      del self._configs[name]
      return {'success': True, 'message': f'Config "{name}" removed'}

   # --- Logs -------------------------------------------------------------

   def get_service_log(self, name, tail=100):
      job_id = _job_id(name)
      try:
         allocs = self._client.get_allocations(job_id)
         if not allocs:
            return {'name': name, 'log': '(no allocations)',
                    'log_file': ''}

         # Get logs from latest allocation
         latest = sorted(allocs,
                         key=lambda a: a.get('CreateIndex', 0),
                         reverse=True)[0]
         alloc_id = latest['ID']
         task_name = self._get_task_name(latest)
         if not task_name:
            return {'name': name, 'log': '(no task found)',
                    'log_file': ''}

         log_text = self._client.get_logs(alloc_id, task_name)
         # Tail last N lines
         lines = log_text.splitlines()
         if len(lines) > tail:
            lines = lines[-tail:]
         return {'name': name, 'log': '\n'.join(lines),
                 'log_file': f'nomad://alloc/{alloc_id}/{task_name}'}

      except NomadAPIError as e:
         return {'name': name,
                 'log': f'(error reading logs: {e})',
                 'log_file': ''}

   # --- Import / Remove --------------------------------------------------

   def import_service(self, name, source_path='', zip_data='',
                      wait_time=1.0):
      # For Nomad, import means creating a job config.
      # Actual artifact delivery is via Nomad's artifact stanza
      # or pre-deployed to a shared filesystem.
      config = {
         'script': 'python',
         'args': ['-m', name],
         'wait_time': wait_time,
      }
      if source_path:
         config['source_path'] = source_path
      self._configs[name] = config
      return {
         'success': True,
         'message': (f'Service "{name}" config created for Nomad. '
                     f'Deploy artifacts to Nomad-accessible path or '
                     f'configure artifact stanza.'),
         'warnings': [],
         'config': config,
      }

   def remove_service(self, name):
      job_id = _job_id(name)
      # Stop and purge the job
      try:
         self._client.stop_job(job_id, purge=True)
      except NomadAPIError:
         pass  # Job may not exist in Nomad
      # Remove local config
      self._configs.pop(name, None)
      return {'success': True,
              'message': f'Service "{name}" removed (job {job_id} purged)'}

   def reset(self):
      # Stop all DAS-managed jobs
      stopped = []
      try:
         jobs = self._client.list_jobs(prefix=JOB_PREFIX)
         for job in jobs:
            try:
               self._client.stop_job(job['ID'], purge=False)
               stopped.append(job['ID'])
            except NomadAPIError as e:
               logger.error('Failed to stop %s: %s', job['ID'], e)
      except NomadAPIError as e:
         return {'success': False,
                 'message': f'Failed to list jobs: {e}'}
      return {'success': True,
              'message': f'Stopped {len(stopped)} jobs: {stopped}'}

   # --- Internal helpers -------------------------------------------------

   def _register_and_run(self, name, config):
      """Build a Nomad job spec from config and register it."""
      job_id = _job_id(name)
      task_name = name.lower().replace(' ', '-')

      command = config.get('script', 'python')
      args = list(config.get('args', []))
      env = dict(config.get('env', {}))
      cwd = config.get('cwd', '')

      # If using python -m, set PYTHONPATH so the module is found
      if command == 'python' and args and args[0] == '-m':
         if cwd:
            env.setdefault('PYTHONPATH', cwd)

      job_spec = {
         'ID': job_id,
         'Name': job_id,
         'Type': 'service',
         'Datacenters': [self._datacenter],
         'Meta': {
            'das_service_name': name,
            'das_managed': 'true',
         },
         'TaskGroups': [{
            'Name': task_name,
            'Count': 1,
            'RestartPolicy': {
               'Attempts': 3,
               'Interval': 300000000000,  # 5 min in nanoseconds
               'Delay': 10000000000,      # 10 s in nanoseconds
               'Mode': 'fail',
            },
            'Tasks': [{
               'Name': task_name,
               'Driver': 'raw_exec',
               'Config': {
                  'command': command,
                  'args': args,
               },
               'Env': env,
               'Resources': {
                  'CPU': config.get('cpu', 500),
                  'MemoryMB': config.get('memory_mb', 256),
               },
               'LogConfig': {
                  'MaxFiles': 3,
                  'MaxFileSizeMB': 10,
               },
            }],
         }],
      }

      try:
         result = self._client.register_job(job_spec)
         eval_id = result.get('EvalID', '')
         return {
            'success': True,
            'message': f'Job {job_id} registered (eval: {eval_id})',
            'pid': eval_id,
         }
      except NomadAPIError as e:
         return {
            'success': False,
            'message': f'Failed to register job {job_id}: {e}',
         }

   def _get_latest_alloc(self, job_id):
      """Get summary info from the latest allocation of a job."""
      try:
         allocs = self._client.get_allocations(job_id)
         if not allocs:
            return {}
         latest = sorted(allocs,
                         key=lambda a: a.get('CreateIndex', 0),
                         reverse=True)[0]
         return {
            'alloc_id': latest.get('ID', ''),
            'task_group': latest.get('TaskGroup', ''),
            'node': latest.get('NodeID', '')[:8] if latest.get('NodeID') else '',
            'client_status': latest.get('ClientStatus', ''),
         }
      except NomadAPIError:
         return {}

   @staticmethod
   def _get_task_name(alloc):
      """Extract the first task name from an allocation."""
      task_states = alloc.get('TaskStates') or {}
      if task_states:
         return next(iter(task_states))
      # Fallback: parse from TaskGroup
      tg = alloc.get('TaskGroup', '')
      return tg if tg else None

   @staticmethod
   def _map_nomad_status(nomad_status):
      """Map Nomad job status to ProcessHub-compatible state string."""
      mapping = {
         'running': 'RUNNING',
         'pending': 'STARTING',
         'dead': 'STOPPED',
      }
      return mapping.get(nomad_status, nomad_status.upper())

   def _poll_loop(self):
      """Background thread: long-poll Nomad for job status changes."""
      logger.debug('Nomad poll loop started')
      while self._running:
         try:
            jobs = self._client.list_jobs_blocking(
               prefix=JOB_PREFIX, wait='30s'
            )
            status = self._build_poll_status(jobs)
            if status != self._last_status:
               self._last_status = status
               if self._on_status_change:
                  self._on_status_change(self.get_status())
         except NomadAPIError as e:
            if self._running:
               logger.error('Nomad poll error: %s', e)
               time.sleep(5)
         except Exception as e:
            if self._running:
               logger.error('Nomad poll unexpected error: %s', e)
               time.sleep(5)
      logger.debug('Nomad poll loop stopped')

   @staticmethod
   def _build_poll_status(jobs):
      """Build a hashable fingerprint from job list for change detection."""
      entries = []
      for j in (jobs or []):
         entries.append((j.get('ID', ''), j.get('Status', ''),
                         j.get('JobModifyIndex', 0)))
      return tuple(sorted(entries))
