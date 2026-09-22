"""Fixture: UDS embedding blocks the way story 05 would write them."""


def register_block(name):
    def deco(cls):
        return cls
    return deco


class Block:
    def __init__(self, block_id, params):
        self.id = block_id
        self.params = params


@register_block("UdsWriteSinkBlock")
class UdsWriteSinkBlock(Block):
    """Embeds a setpoint write as a UDS request through the request service."""

    inputs = ("value",)
    outputs = ("ack", "last_nrc")

    def __init__(self, block_id, params, client):
        super().__init__(block_id, params)
        self._svc = params["request_service"]   # graph-studio: device_ref
        self.allowlist = params.get("allowlist", [])   # [{service, min, max, min_interval_s}]
        self.service_name = params["service_name"]     # graph-studio: allowed_from allowlist.service
        self.limits = dict(params.get("limits", {}))
        self.trigger = params.get("trigger", "on_change")
        self.min_interval_s = params.get("min_interval_s", 0.5)
        self.priority = params.get("priority", "mid")  # graph-studio: enum high|mid|low
        if self.trigger not in ("on_change", "every_write", "edge"):
            raise ValueError("bad trigger")

    @classmethod
    def build(cls, cfg, ctx):
        return cls(cfg.id, cfg.params, None)


@register_block("UdsRoutineTriggerBlock")
class UdsRoutineTriggerBlock(Block):
    """Starts a RoutineControl on a rising edge of `trigger`."""

    inputs = ("trigger",)
    outputs = ("ack",)

    def __init__(self, block_id, params, client):
        super().__init__(block_id, params)
        self._svc = params["request_service"]   # graph-studio: device_ref
        self.routine = params["routine_name"]   # graph-studio: signal_ref
        self.retries = int(params["retries"])
