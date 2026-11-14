"""Target stacks the planner can map a legacy site onto."""

from stackbooster.targets.base import TargetMapping, TargetStack
from stackbooster.targets.fastapi_react import FastApiReactTarget

TARGETS: dict[str, type[TargetStack]] = {
    FastApiReactTarget.key: FastApiReactTarget,
}
DEFAULT_TARGET = FastApiReactTarget.key


def get_target(key: str = DEFAULT_TARGET) -> TargetStack:
    try:
        return TARGETS[key]()
    except KeyError:
        known = ", ".join(sorted(TARGETS))
        raise ValueError(f"unknown target stack {key!r} (known: {known})") from None


__all__ = ["DEFAULT_TARGET", "TARGETS", "TargetMapping", "TargetStack", "get_target"]
