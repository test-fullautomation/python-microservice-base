#  Copyright 2020-2026 Robert Bosch GmbH
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
"""MicroserviceBase.tools.ui_component: a component.json from existing protos."""

import json
import os
import shutil
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..")))

from MicroserviceBase.tools import ui_component as uc  # noqa: E402

GUI = os.path.abspath(os.path.join(HERE, "..", "..", "MicroserviceBase", "MicroserviceManagerGUI"))

SUPPLY = """
syntax = "proto3";
package supply;

message Empty {}
message ChannelRequest { int32 channel = 1; }   // 1-4
message SetVoltageRequest {
  int32 channel = 1;
  float voltage = 2;  // Volts, must be >= 0 and <=60
}
message Reading {
  int32 errorcode = 1;
  float value     = 2;
}
message Sample { repeated float values = 1; Mode mode = 2; }
enum Mode { DC = 0; AC = 1; }
service SupplyService {
  rpc ReadVoltage (ChannelRequest) returns (Reading);
  rpc SetVoltage (SetVoltageRequest) returns (Empty);
  rpc InitDevice (Empty) returns (Empty);
  rpc Watch (ChannelRequest) returns (stream Reading);
  rpc Upload (stream Sample) returns (Empty);
}
"""

CONFIG = """
syntax = "proto3";
package config;
message Empty {}
message TypeRequest { int32 type = 1; }
service ConfigService {
  rpc SetInterfaceType (TypeRequest) returns (Empty);
  rpc Connect (Empty) returns (Empty);
}
"""


def _build(**kw):
    return uc.build_component([uc.parse_proto(SUPPLY), uc.parse_proto(CONFIG)],
                              title="Supply", component="bits.supply", layer="bits", **kw)


class Test_Parse:

    def test_messages_enums_services(self):
        p = uc.parse_proto(SUPPLY)
        assert p["package"] == "supply"
        assert [f["name"] for f in p["messages"]["SetVoltageRequest"]] == ["channel", "voltage"]
        assert "Mode" in p["enums"]
        rpcs = {r["name"]: r for r in p["services"][0]["rpcs"]}
        assert rpcs["Watch"]["server_streaming"] and rpcs["Upload"]["client_streaming"]


class Test_Build:

    def test_binds_both_services_and_orders_tiles(self):
        m = _build()
        assert m["binds"]["grpc"] == ["supply.SupplyService", "config.ConfigService"]
        calls = [t.get("call") or t.get("rpc") for t in m["tiles"]]
        # set-up, then commands, then reads; the second service's calls are qualified
        assert calls[:3] == ["InitDevice", "SetVoltage", "ReadVoltage"]
        assert "config.ConfigService/SetInterfaceType" in calls
        assert "Upload" not in calls           # a form cannot feed a request stream

    def test_typed_form_with_bounds_and_default(self):
        tile = next(t for t in _build()["tiles"] if t.get("call") == "SetVoltage")
        assert tile["form"]["voltage"] == {"type": "float", "label": "Voltage", "min": 0.0, "max": 60.0}
        assert tile["form"]["channel"]["default"] == 1
        assert tile["size"] == "2x1"

    def test_reads_show_value_and_streams_are_logs(self):
        tiles = {t["id"]: t for t in _build()["tiles"]}
        assert tiles["read-voltage"]["resultPath"] == "value"
        assert tiles["watch"]["kind"] == "log"

    def test_live_tile_only_when_asked(self):
        assert not any(t["kind"] == "live-status" for t in _build()["tiles"])
        live = _build(live=True)["tiles"][0]
        assert live["kind"] == "live-status"
        assert live["fields"][0] == {"label": "Read voltage", "rpc": "ReadVoltage", "path": "value",
                                     "digits": 3, "args": {"channel": 1}}


DEVICES = """
syntax = "proto3";
package cfg;
message Empty {}
message CommandResponse { int32 errorcode = 1; }
message InterfaceTypeRequest { int32 type = 1; } // 0-> RS232; 1-> client; 2-> NI-Visa
message GetInterfaceTypeResponse { int32 type = 1; }
message DeviceTypeRequest { int32 index = 1; }   // 1-n type
message GetDeviceTypeResponse { int32 errorcode = 1; int32 index = 2; }
message CountResponse {
  int32 errorcode = 1;
  int32 index     = 2;  // max index supported
}
message NameResponse { int32 errorcode = 1; string name = 2; }
message SubDeviceTypeRequest { int32 index = 1; } // 0-n see table
service ConfigService {
  rpc SetInterfaceType (InterfaceTypeRequest) returns (CommandResponse);
  rpc GetInterfaceType (Empty) returns (GetInterfaceTypeResponse);
  rpc SetDeviceType (DeviceTypeRequest) returns (CommandResponse);
  rpc GetDeviceType (Empty) returns (GetDeviceTypeResponse);
  rpc GetDeviceType_ListCount (Empty) returns (CountResponse);
  rpc GetDeviceType_Name (DeviceTypeRequest) returns (NameResponse);
  rpc SetSubDeviceType (SubDeviceTypeRequest) returns (CommandResponse);
  rpc GetSubDeviceType_ListCount (DeviceTypeRequest) returns (CountResponse);
  rpc GetSubDeviceType_Name (SubDeviceTypeRequest) returns (NameResponse);
}
"""


class Test_Groups:

    def _m(self):
        return uc.build_component([uc.parse_proto(SUPPLY), uc.parse_proto(DEVICES)],
                                  title="Supply", component="bits.supply", layer="bits")

    def test_few_tiles_stay_flat(self):
        assert "groups" not in _build()          # 6 tiles: headers would only add clutter

    def test_own_rpcs_by_role_others_by_topic_collapsed(self):
        g = {x["id"]: x for x in self._m()["groups"]}
        assert [x["id"] for x in self._m()["groups"]] == ["commands", "readings", "streams", "interface", "device"]
        assert g["commands"]["tiles"] == ["init-device", "set-voltage"] and "collapsed" not in g["commands"]
        assert g["readings"]["tiles"] == ["read-voltage"] and g["streams"]["tiles"] == ["watch"]
        # another service: by topic, in the order its proto declares them, collapsed
        assert g["interface"] == {"id": "interface", "title": "Interface type", "collapsed": True,
                                  "tiles": ["set-interface-type", "get-interface-type"]}
        assert g["device"]["title"] == "Device type" and g["device"]["collapsed"] is True
        # sub-device types go with the device types
        assert "set-sub-device-type" in g["device"]["tiles"] and "get-sub-device-type-name" in g["device"]["tiles"]

    def test_tiles_are_ordered_group_by_group(self):
        m = self._m()
        assert [t["id"] for t in m["tiles"]] == [tid for grp in m["groups"] for tid in grp["tiles"]]

    def test_topic(self):
        assert uc._topic("GetSubDeviceType_Name") == "DeviceType"
        assert uc._topic("LoadInterfaceConfig") == "InterfaceConfig"
        assert uc._topic("DisConnect") == "Connect"
        assert uc._topic("GetConnectState") == "ConnectState"


class Test_Dropdowns:

    def _forms(self):
        m = uc.build_component([uc.parse_proto(DEVICES)], title="Cfg", component="bits.cfg", layer="bits")
        return {t["id"]: t.get("form", {}) for t in m["tiles"]}

    def test_choices_from_the_field_comment_with_the_current_one(self):
        f = self._forms()["set-interface-type"]["type"]
        assert f["options"] == [{"value": 0, "label": "RS232"}, {"value": 1, "label": "client"},
                                {"value": 2, "label": "NI-Visa"}]
        assert f["current"] == {"rpc": "GetInterfaceType", "path": "type"}

    def test_choices_listed_by_the_service(self):
        # 0 .. count-1, whatever the "1-n" / "max index" comments say: an index
        # past the end crashed a service that does not check it.
        f = self._forms()["set-device-type"]["index"]
        assert f["optionsFrom"] == {"count": {"rpc": "GetDeviceType_ListCount", "path": "index"},
                                    "name": {"rpc": "GetDeviceType_Name", "arg": "index", "path": "name"}}
        assert f["current"] == {"rpc": "GetDeviceType", "path": "index"}

    def test_sub_devices_follow_the_selected_device_type(self):
        f = self._forms()["set-sub-device-type"]["index"]
        assert "first" not in f["optionsFrom"] and "inclusive" not in f["optionsFrom"]
        # read again after a new device type is set (no GetSubDeviceType here,
        # so nothing "current" to refresh after its own setter)
        assert f["reloadAfter"] == ["SetDeviceType"]
        # the device type's current value is refreshed after its own setter
        assert self._forms()["set-device-type"]["index"]["reloadAfter"] == ["SetDeviceType"]
        # the count's argument is not guessed from GetDeviceType: a service may
        # read it as something else (the BITS ones: the unit) and miscount
        assert "args" not in f["optionsFrom"]["count"]

    def test_a_count_rpc_gets_no_dropdown_of_itself(self):
        assert "optionsFrom" not in self._forms()["get-sub-device-type-list-count"]["index"]


def test_cli_writes_a_folder_that_lints(tmp_path):
    (tmp_path / "supply.proto").write_text(SUPPLY, encoding="utf-8")
    (tmp_path / "config.proto").write_text(CONFIG, encoding="utf-8")
    rc = uc.main(["--proto", str(tmp_path / "supply.proto"), "--proto", str(tmp_path / "config.proto"),
                  "--title", "Supply", "--folder", "SupplyService1.0.0", "--out", str(tmp_path)])
    assert rc == 0
    manifest = tmp_path / "SupplyService1.0.0" / "component.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert data["component"] == "bits.supply-service"
    assert (tmp_path / "SupplyService1.0.0" / "README.md").exists()
    node = shutil.which("node")
    if not node:
        pytest.skip("node not on PATH: lint not run")
    r = subprocess.run([node, os.path.join(GUI, "tools", "endo-lint.js"), str(manifest)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
