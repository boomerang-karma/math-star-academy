"""Name -> connector factory registry used by the connector-runner Lambda and the API."""

from __future__ import annotations

from collections.abc import Callable

from leadintel.connectors.base import Connector
from leadintel.core.config import Settings
from leadintel.core.errors import NotFoundError

ConnectorFactory = Callable[[Settings], Connector]

_REGISTRY: dict[str, ConnectorFactory] = {}


def register(name: str) -> Callable[[ConnectorFactory], ConnectorFactory]:
    def decorator(factory: ConnectorFactory) -> ConnectorFactory:
        if name in _REGISTRY:
            raise ValueError(f"connector {name!r} registered twice")
        _REGISTRY[name] = factory
        return factory

    return decorator


def create(name: str, settings: Settings) -> Connector:
    _load_builtin()
    try:
        factory = _REGISTRY[name]
    except KeyError as exc:
        raise NotFoundError(f"unknown connector {name!r}") from exc
    return factory(settings)


def names() -> list[str]:
    _load_builtin()
    return sorted(_REGISTRY)


def _load_builtin() -> None:
    # Imported for their @register side effect; deferred to keep cold starts lean.
    from leadintel.connectors.scrapebadger import connector  # noqa: F401
