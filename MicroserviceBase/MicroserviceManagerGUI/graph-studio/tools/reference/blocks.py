# EXTRACTED SNAPSHOT — services/signals/signal_graph/core/domain/blocks.py
# from PR #253 revision 2 (253_update.diff, 2026-09-13). Reference input for
# generate_catalog.py until the PR is checked out; then point at the real file.
"""Block library for ``signal_graph``.

Blocks are the reusable computational units wired together by a ``graph.json``.
Each block declares its input and output ports and implements ``step`` (executed
once per graph cycle). Source blocks have no inputs (they acquire data from a
device, a setpoint, or an upstream service via :class:`SignalCatalogPort`); sink
blocks have no outputs (they persist data or drive an output device).

A value of ``None`` flowing on a port means "no sample this cycle" (used by the
``DecimatorBlock`` for rate reduction); downstream blocks skip when their input
is ``None``. This module has no transport dependencies — gRPC/protobuf live in
the outbound adapters behind the ports.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Callable

from signal_graph.core.domain.graph_config import BlockConfig
from signal_graph.core.domain.measurement import Measurement
from signal_graph.core.domain.signal_store import SetpointHandle
from signal_graph.core.ports.outbound.device_port import DevicePort
from signal_graph.core.ports.outbound.measurement_repository_port import (
    MeasurementRepositoryPort,
)
from signal_graph.core.ports.outbound.signal_catalog_port import SignalCatalogPort

logger = logging.getLogger(__name__)

Value = float | None


@dataclass
class BuildContext:
    """Dependencies available to blocks at construction time."""

    device_adapters: dict[str, DevicePort]
    measurement_repo: MeasurementRepositoryPort
    flow_mode: str = "push"
    catalog_client: SignalCatalogPort | None = None
    setpoints: dict[str, SetpointHandle] = field(default_factory=dict)


class Block:
    """Base class for all blocks."""

    inputs: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ()

    def __init__(self, block_id: str, params: dict) -> None:
        self.id = block_id
        self.params = params
        self.units: dict[str, str] = {}

    async def start(self) -> None:  # optional lifecycle hook
        pass

    async def stop(self) -> None:
        pass

    async def step(self, inputs: dict[str, Value]) -> dict[str, Value]:
        raise NotImplementedError


# -- block registry --------------------------------------------------------

BlockFactory = Callable[[BlockConfig, BuildContext], Block]
_REGISTRY: dict[str, BlockFactory] = {}


def register_block(type_name: str) -> Callable[[type[Block]], type[Block]]:
    def decorator(cls: type[Block]) -> type[Block]:
        _REGISTRY[type_name] = cls.build
        return cls

    return decorator


def create_block(cfg: BlockConfig, ctx: BuildContext) -> Block:
    factory = _REGISTRY.get(cfg.type)
    if factory is None:
        raise KeyError(f"unknown block type {cfg.type!r}")
    return factory(cfg, ctx)


# -- source blocks ---------------------------------------------------------


@register_block("AdcBlock")
class AdcBlock(Block):
    """Reads an analog input channel from a device service each cycle."""

    outputs = ("out",)

    def __init__(self, block_id: str, params: dict, device: DevicePort) -> None:
        super().__init__(block_id, params)
        self._device = device
        self._channel = int(params["channel"])
        self.units["out"] = params.get("unit", "V")

    @classmethod
    def build(cls, cfg: BlockConfig, ctx: BuildContext) -> "AdcBlock":
        device_name = cfg.params["device"]
        device = ctx.device_adapters[device_name]
        return cls(cfg.id, cfg.params, device)

    async def step(self, inputs: dict[str, Value]) -> dict[str, Value]:
        value = await self._device.read_analog_input(self._channel)
        return {"out": value}


@register_block("SetpointBlock")
class SetpointBlock(Block):
    """Holds a controllable value updated via SetSignal; emits it each cycle."""

    outputs = ("out",)

    def __init__(self, block_id: str, params: dict, handle: SetpointHandle) -> None:
        super().__init__(block_id, params)
        self._handle = handle
        self.signal_name = params["signal_name"]
        self.units["out"] = params.get("unit", "")

    @classmethod
    def build(cls, cfg: BlockConfig, ctx: BuildContext) -> "SetpointBlock":
        handle = SetpointHandle(value=float(cfg.params.get("initial_value", 0.0)))
        ctx.setpoints[cfg.params["signal_name"]] = handle
        return cls(cfg.id, cfg.params, handle)

    async def step(self, inputs: dict[str, Value]) -> dict[str, Value]:
        return {"out": self._handle.get()}


@register_block("SubscriberSourceBlock")
class SubscriberSourceBlock(Block):
    """Consumes a signal owned by another ``signal_graph`` service.

    ``flow_mode="push"``: consumes the :class:`SignalCatalogPort` value stream in
    a background task and caches the latest value. ``flow_mode="pull"``: reads
    the current value each cycle. The owning service always serves both,
    regardless of its own flow mode.
    """

    outputs = ("out",)

    def __init__(
        self,
        block_id: str,
        params: dict,
        catalog: SignalCatalogPort,
        flow_mode: str,
    ) -> None:
        super().__init__(block_id, params)
        self._catalog = catalog
        self._flow_mode = flow_mode
        self._signal_name = params["signal_name"]
        self.units["out"] = params.get("unit", "")
        self._latest: Value = None
        self._pump_task: asyncio.Task | None = None

    @classmethod
    def build(cls, cfg: BlockConfig, ctx: BuildContext) -> "SubscriberSourceBlock":
        if ctx.catalog_client is None:
            raise RuntimeError("SubscriberSourceBlock requires a catalog client")
        return cls(cfg.id, cfg.params, ctx.catalog_client, ctx.flow_mode)

    async def start(self) -> None:
        if self._flow_mode == "push":
            self._pump_task = asyncio.create_task(self._pump())

    async def stop(self) -> None:
        if self._pump_task is not None:
            self._pump_task.cancel()
            try:
                await self._pump_task
            except asyncio.CancelledError:
                pass

    async def _pump(self) -> None:
        async for value in self._catalog.subscribe(self._signal_name):
            self._latest = value

    async def step(self, inputs: dict[str, Value]) -> dict[str, Value]:
        if self._flow_mode == "pull":
            value = await self._catalog.read(self._signal_name)
            if value is not None:
                self._latest = value
        return {"out": self._latest}


# -- function blocks -------------------------------------------------------


@register_block("LinearScaleBlock")
class LinearScaleBlock(Block):
    """``out = gain * in + offset`` (linear calibration / unit conversion)."""

    inputs = ("in",)
    outputs = ("out",)

    def __init__(self, block_id: str, params: dict) -> None:
        super().__init__(block_id, params)
        self._gain = float(params.get("gain", 1.0))
        self._offset = float(params.get("offset", 0.0))
        self.units["out"] = params.get("out_unit", params.get("in_unit", ""))

    @classmethod
    def build(cls, cfg: BlockConfig, ctx: BuildContext) -> "LinearScaleBlock":
        return cls(cfg.id, cfg.params)

    async def step(self, inputs: dict[str, Value]) -> dict[str, Value]:
        x = inputs.get("in")
        if x is None:
            return {"out": None}
        return {"out": self._gain * x + self._offset}


@register_block("ClampBlock")
class ClampBlock(Block):
    """Clamps its input to ``[min_value, max_value]``."""

    inputs = ("in",)
    outputs = ("out",)

    def __init__(self, block_id: str, params: dict) -> None:
        super().__init__(block_id, params)
        self._min = float(params["min_value"])
        self._max = float(params["max_value"])

    @classmethod
    def build(cls, cfg: BlockConfig, ctx: BuildContext) -> "ClampBlock":
        return cls(cfg.id, cfg.params)

    async def step(self, inputs: dict[str, Value]) -> dict[str, Value]:
        x = inputs.get("in")
        if x is None:
            return {"out": None}
        return {"out": max(self._min, min(self._max, x))}


@register_block("DecimatorBlock")
class DecimatorBlock(Block):
    """Passes every ``n``-th sample; emits ``None`` otherwise (rate reduction)."""

    inputs = ("in",)
    outputs = ("out",)

    def __init__(self, block_id: str, params: dict) -> None:
        super().__init__(block_id, params)
        self._n = max(1, int(params.get("n", 1)))
        self._count = 0

    @classmethod
    def build(cls, cfg: BlockConfig, ctx: BuildContext) -> "DecimatorBlock":
        return cls(cfg.id, cfg.params)

    async def step(self, inputs: dict[str, Value]) -> dict[str, Value]:
        x = inputs.get("in")
        if x is None:
            return {"out": None}
        emit = self._count % self._n == 0
        self._count += 1
        return {"out": x if emit else None}


@register_block("ThresholdBlock")
class ThresholdBlock(Block):
    """Emits ``1.0`` when ``in`` crosses ``threshold``, else ``0.0``."""

    inputs = ("in",)
    outputs = ("out",)

    def __init__(self, block_id: str, params: dict) -> None:
        super().__init__(block_id, params)
        self._threshold = float(params["threshold"])
        self.units["out"] = params.get("unit", "bool")

    @classmethod
    def build(cls, cfg: BlockConfig, ctx: BuildContext) -> "ThresholdBlock":
        return cls(cfg.id, cfg.params)

    async def step(self, inputs: dict[str, Value]) -> dict[str, Value]:
        x = inputs.get("in")
        if x is None:
            return {"out": None}
        return {"out": 1.0 if x > self._threshold else 0.0}


# -- sink blocks -----------------------------------------------------------


@register_block("RecordSignalBlock")
class RecordSignalBlock(Block):
    """Batches incoming samples and flushes them to the measurement store."""

    inputs = ("in",)
    outputs = ()

    def __init__(
        self,
        block_id: str,
        params: dict,
        repo: MeasurementRepositoryPort,
    ) -> None:
        super().__init__(block_id, params)
        self._repo = repo
        self.signal_name = params["signal_name"]
        self._batch_size = int(params.get("batch_size", 100))
        self._buffer: list[Measurement] = []

    @classmethod
    def build(cls, cfg: BlockConfig, ctx: BuildContext) -> "RecordSignalBlock":
        return cls(cfg.id, cfg.params, ctx.measurement_repo)

    async def step(self, inputs: dict[str, Value]) -> dict[str, Value]:
        x = inputs.get("in")
        if x is None:
            return {}
        self._buffer.append(Measurement(self.signal_name, x, time.time()))
        if len(self._buffer) >= self._batch_size:
            await self._flush()
        return {}

    async def _flush(self) -> None:
        if self._buffer:
            await self._repo.write_measurements(self._buffer)
            self._buffer.clear()

    async def stop(self) -> None:
        await self._flush()


@register_block("DacBlock")
class DacBlock(Block):
    """Writes its input to an analog output channel on a device service."""

    inputs = ("in",)
    outputs = ()

    def __init__(self, block_id: str, params: dict, device: DevicePort) -> None:
        super().__init__(block_id, params)
        self._device = device
        self._channel = int(params["channel"])

    @classmethod
    def build(cls, cfg: BlockConfig, ctx: BuildContext) -> "DacBlock":
        device = ctx.device_adapters[cfg.params["device"]]
        return cls(cfg.id, cfg.params, device)

    async def step(self, inputs: dict[str, Value]) -> dict[str, Value]:
        x = inputs.get("in")
        if x is not None:
            await self._device.write_analog_output(self._channel, x)
        return {}
