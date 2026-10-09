"""Brokers — registry + factory. Ab naya broker add karna = ek file + register. 🏭

Usage:
  from apps.engine.brokers import get_broker, available_brokers
  broker = get_broker("kite", dry_run=True)          # simulated, safe
  broker = get_broker("dhan", dry_run=False, client_id=..., access_token=...)  # real
"""
from __future__ import annotations

import os

from apps.engine.brokers.base import BrokerBase

_REGISTRY: dict[str, type[BrokerBase]] = {}


def register_broker(cls: type[BrokerBase]) -> type[BrokerBase]:
    """Class decorator — broker ko registry mein daal deta hai."""
    _REGISTRY[cls.name] = cls
    return cls


def get_broker(name: str, dry_run: bool = True, **kwargs) -> BrokerBase:
    """Name se broker instance. dry_run=True default — hamesha safe start."""
    if name not in _REGISTRY:
        raise ValueError(
            f"Unknown broker '{name}'. Available: {', '.join(sorted(_REGISTRY))}"
        )
    return _REGISTRY[name](dry_run=dry_run, **kwargs)


def available_brokers() -> list[dict]:
    """UI/API ke liye: kaun-kaun se brokers hain + creds present hain ya nahi."""
    out = []
    for name, cls in sorted(_REGISTRY.items()):
        out.append({
            "name": name,
            "required_env": list(cls.required_env),
            "credentials_present": all(os.environ.get(v) for v in cls.required_env),
        })
    return out


# Brokers register hote hain import pe
from apps.engine.brokers.dhan_broker import DhanBroker  # noqa: E402,F401
from apps.engine.brokers.fyers_broker import FyersBroker  # noqa: E402,F401
from apps.engine.brokers.kite_broker import KiteBroker  # noqa: E402,F401
from apps.engine.brokers.upstox_broker import UpstoxBroker  # noqa: E402,F401
