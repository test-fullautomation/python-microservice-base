"""Fixture: extraction block with the choices check outside __init__."""


def register_block(name):
    def deco(cls):
        return cls
    return deco


class Block:
    def __init__(self, block_id, params):
        self.id = block_id
        self.params = params


@register_block("UdsDecodeBlock")
class UdsDecodeBlock(Block):
    """Decodes a response into scaled signals."""

    inputs = ("raw",)
    outputs = ("v1", "v2")

    def __init__(self, block_id, params):
        super().__init__(block_id, params)
        self.on_nrc = params.get("on_nrc", "none")
        self.scale = float(params.get("scale", 1.0))

    async def step(self, inputs):
        if self.on_nrc not in {"none", "hold"}:
            raise ValueError("bad on_nrc")
        return {"v1": None, "v2": None}
