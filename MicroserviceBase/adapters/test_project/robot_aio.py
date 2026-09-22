"""Robot Framework AIO adapter for test projects.

Layout (all folders configurable in ``testproject.json``)::

    <project>/
      testproject.json                      manifest (runner-neutral)
      testsuites/
        config/robot_config.jsonp           RF AIO config, level 3 (starter)
        <service>_smoke.robot               starter suite (starter)
      resources/<service>/<grpc>.resource   generated keywords (generated)
      proto/<service>/*.proto               copied protos, when available

Conventions followed from ``RobotFramework_TestsuitesManagement``:

* suites import the library ``WITH NAME testsuites`` and call
  ``testsuites.testsuite_setup`` / ``testsuite_teardown``;
* configuration level 3 -- ``config/robot_config.jsonp`` next to the
  suites -- is found without arguments; keys under ``params.global``
  become global Robot variables (``${CONSUL_ADDR}``).

Resources come from :mod:`MicroserviceBase.adapters.scaffold.robot_tmpl`,
the same generator as the CLI and the GUI's Robot Resource Generator.
They connect through Consul by service name, so no host/port is baked in
-- Nomad assigns a new port on every placement.
"""

from __future__ import annotations

import json
import os
import posixpath
import re
from typing import Dict, List

from ...ports.test_project import (
    PlannedFile,
    ServiceExport,
    TestProjectError,
    TestProjectRunner,
)
from ..scaffold.robot_tmpl import (
    RobotGenError,
    emit_resources,
    keyword_name,
    parse_proto_folder,
    resource_file_name,
    services_from_file_descriptors,
)

_CONFIG_REL = "config/robot_config.jsonp"


def _ident(name: str) -> str:
    """``hello-gui`` -> ``hello_gui``: safe as file stem and connection name."""
    return re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").lower() or "service"


def _config_jsonp(project_name: str, consul_addr: str) -> str:
    return (
        "// RobotFramework AIO configuration for this test project.\n"
        "//\n"
        "// Found automatically at configuration level 3 (config/robot_config.jsonp\n"
        "// next to the suites). Keys under params.global become global Robot\n"
        "// variables, e.g. ${CONSUL_ADDR}.\n"
        "//\n"
        "// Created by Microservice Manager and never overwritten by it: edit freely.\n"
        "{\n"
        f'  "Project"       : {json.dumps(project_name)},\n'
        f'  "WelcomeString" : {json.dumps(project_name + ": microservice tests")},\n'
        '  "TargetName"    : "bench",\n'
        '  "params"        : {\n'
        '    "global" : {\n'
        f'      "CONSUL_ADDR" : {json.dumps(consul_addr)}\n'
        "    }\n"
        "  }\n"
        "}\n"
    )


class RobotAioRunner(TestProjectRunner):
    """Robot Framework AIO (``RobotFramework_TestsuitesManagement``)."""

    runner_id = "robotframework-aio"
    display_name = "Robot Framework AIO"

    def default_layout(self) -> Dict[str, str]:
        return {"suites": "testsuites", "resources": "resources", "proto": "proto"}

    def _config_path(self, layout: Dict[str, str]) -> str:
        return f"{layout['suites']}/{_CONFIG_REL}"

    def _suite_path(self, layout: Dict[str, str], export: ServiceExport) -> str:
        return f"{layout['suites']}/{_ident(export.consul_name)}_smoke.robot"

    def init_files(self, layout, project_name, consul_addr):
        return {self._config_path(layout): _config_jsonp(project_name, consul_addr)}

    def _services(self, export: ServiceExport):
        try:
            if export.proto_dir:
                services = parse_proto_folder(export.proto_dir)
            else:
                services = services_from_file_descriptors(
                    export.file_descriptors or [], source_label="server reflection")
        except RobotGenError as exc:
            raise TestProjectError(str(exc)) from exc

        wanted = set(export.grpc_services or [])
        if wanted:
            services = [s for s in services if s.full_name in wanted or s.name in wanted]
        unique, seen = [], set()
        for svc in services:
            if svc.full_name not in seen:
                seen.add(svc.full_name)
                unique.append(svc)
        if not unique:
            raise TestProjectError(
                "None of the gRPC services "
                f"({', '.join(sorted(wanted)) or 'none advertised'}) were found in the "
                f"API description of {export.consul_name}."
            )
        return unique

    def service_files(self, layout, export, *, create_starter=True) -> List[PlannedFile]:
        services = self._services(export)
        res_dir = f"{layout['resources']}/{export.consul_name}"
        files = [PlannedFile(f"{res_dir}/{name}", content, "generated")
                 for name, content in emit_resources(services).items()]
        if create_starter:
            files.append(PlannedFile(self._suite_path(layout, export),
                                     self._starter_suite(layout, export, services, res_dir),
                                     "starter"))
            files.append(PlannedFile(self._config_path(layout),
                                     _config_jsonp(export.project_name, export.consul_addr),
                                     "starter"))
        return files

    def advisories(self, root, layout, export) -> List[str]:
        rel = self._config_path(layout)
        path = os.path.join(root, *rel.split("/"))
        if not os.path.isfile(path):
            return []
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            return []
        match = re.search(r'"CONSUL_ADDR"\s*:\s*"([^"]*)"', text)
        if match is None:
            return [f"{rel} does not define CONSUL_ADDR under params.global; suites fall "
                    f"back to {export.consul_addr}. Add it there to point every suite at "
                    "the right Consul."]
        if export.consul_addr and match.group(1).rstrip("/") != export.consul_addr.rstrip("/"):
            return [f"{rel} points suites at Consul {match.group(1)}, but "
                    f"{export.consul_name} is registered in {export.consul_addr}."]
        return []

    def run_hint(self, layout, export) -> str:
        return f"python -m robot -d results {self._suite_path(layout, export)}"

    def project_run_hint(self, layout) -> str:
        return f"python -m robot -d results {layout['suites']}"

    def suite_template(self, layout, suite_path, service, resource_paths,
                       consul_addr, proto_rel_dir) -> str:
        suites_dir = posixpath.dirname(suite_path)
        stem = posixpath.splitext(posixpath.basename(suite_path))[0]
        title = re.sub(r"[_-]+", " ", stem).strip().title() or "New Suite"

        # Resource stem -> keyword prefix + connection name, the same mapping
        # the generator uses (hello_service.resource -> "Hello Service").
        conns = []
        for res in resource_paths:
            res_stem = posixpath.splitext(posixpath.basename(res))[0]
            conns.append((res_stem.replace("_", " ").title(), res_stem))

        lines = [
            "*** Settings ***",
            f"Documentation     {title}.",
            "Library           RobotFramework_TestsuitesManagement    WITH NAME    testsuites",
        ]
        lines += [f"Resource          {posixpath.relpath(res, suites_dir)}" for res in resource_paths]
        if conns:
            lines += ["Suite Setup       Open Service Connections",
                      "Suite Teardown    Close Service Connections"]
        else:
            lines += ["Suite Setup       testsuites.testsuite_setup",
                      "Suite Teardown    testsuites.testsuite_teardown"]
        if conns:
            proto_value = ("${CURDIR}/" + posixpath.relpath(proto_rel_dir, suites_dir)
                           if proto_rel_dir else "${EMPTY}")
            lines += [
                "",
                "*** Variables ***",
                "# CONSUL_ADDR normally comes from config/robot_config.jsonp; this is the fallback.",
                f"${{CONSUL_ADDR}}      {consul_addr}",
                f"${{SERVICE_NAME}}     {service}",
                f"${{PROTO_DIR}}        {proto_value}",
            ]
        lines += [
            "",
            "*** Test Cases ***",
            f"{title} Works",
            "    [Documentation]    Describe what this test checks.",
            "    No Operation",
        ]
        if conns:
            lines += ["", "*** Keywords ***", "Open Service Connections", "    testsuites.testsuite_setup"]
            for prefix, conn in conns:
                lines += [f"    {prefix} Open Connection    {conn}",
                          "    ...    service_name=${SERVICE_NAME}    consul_addr=${CONSUL_ADDR}    proto_dir=${PROTO_DIR}"]
            lines += ["", "Close Service Connections"]
            lines += [f"    Run Keyword And Ignore Error    {prefix} Close Connection    {conn}"
                      for prefix, conn in conns]
            lines.append("    testsuites.testsuite_teardown")
        return "\n".join(lines) + "\n"

    # ------------------------------------------------------------------

    def _starter_suite(self, layout, export, services, res_dir) -> str:
        suites = layout["suites"]

        def rel(target: str) -> str:
            return posixpath.relpath(target, suites)

        # Connection name = resource stem (HelloService -> hello_service), so
        # it reads the same as the generator's file naming.
        conns = [(svc, resource_file_name(svc)[:-len(".resource")]) for svc in services]
        if export.proto_rel_dir:
            proto_note = "# The service's protos, copied into the project; used when it has no server reflection."
            proto_value = "${CURDIR}/" + rel(export.proto_rel_dir)
        else:
            proto_note = "# No .proto was copied: the service is reached through server reflection."
            proto_value = "${EMPTY}"

        lines: List[str] = [
            "*** Settings ***",
            f"Documentation     Starter suite for the ``{export.consul_name}`` service.",
            "...               Created by Microservice Manager and never overwritten by it: edit freely.",
            f"...               Run from the project root:  {self.run_hint(layout, export)}",
            "Library           RobotFramework_TestsuitesManagement    WITH NAME    testsuites",
        ]
        lines += [f"Resource          {rel(f'{res_dir}/{resource_file_name(svc)}')}" for svc in services]
        lines += [
            "Suite Setup       Open Service Connections",
            "Suite Teardown    Close Service Connections",
            "",
            "*** Variables ***",
            "# CONSUL_ADDR normally comes from config/robot_config.jsonp (params.global);",
            "# this value is only the fallback.",
            f"${{CONSUL_ADDR}}      {export.consul_addr}",
            f"${{SERVICE_NAME}}     {export.consul_name}",
            proto_note,
            f"${{PROTO_DIR}}        {proto_value}",
            "",
            "*** Test Cases ***",
            f"{export.consul_name} Is Reachable",
            "    [Documentation]    The suite setup resolved the service through Consul and opened",
            "    ...                a connection; replace this with real checks.",
            "    No Operation",
        ]

        svc0, conn0 = conns[0]
        methods = [m for m in svc0.methods if not m.server_streaming] or list(svc0.methods)
        if methods:
            method = methods[0]
            args = "".join(f"    {p.name}=<{p.type}>" for p in method.params)
            lines += [
                f"    # Example -- call {method.name}, then check the result:",
                f"    # ${{res}}=    {keyword_name(svc0, method)}    {conn0}{args}",
                "    # Log    ${res}",
            ]

        lines += ["", "*** Keywords ***", "Open Service Connections", "    testsuites.testsuite_setup"]
        for svc, conn in conns:
            lines += [
                f"    {keyword_name(svc)} Open Connection    {conn}",
                "    ...    service_name=${SERVICE_NAME}    consul_addr=${CONSUL_ADDR}    proto_dir=${PROTO_DIR}",
            ]
        lines += ["", "Close Service Connections"]
        lines += [f"    Run Keyword And Ignore Error    {keyword_name(svc)} Close Connection    {conn}"
                  for svc, conn in conns]
        lines.append("    testsuites.testsuite_teardown")
        return "\n".join(lines) + "\n"
