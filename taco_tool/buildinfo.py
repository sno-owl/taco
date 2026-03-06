from __future__ import annotations

from dataclasses import dataclass

BASE_VERSION = "0.1.0"

try:
    from taco_tool import _generated_buildinfo as generated
except ImportError:  # pragma: no cover - generated at build time
    generated = None


@dataclass(frozen=True)
class BuildInfo:
    version: str
    commit: str
    built_at: str
    dirty: bool


def get_build_info() -> BuildInfo:
    if generated is None:
        return BuildInfo(
            version=BASE_VERSION,
            commit="dev",
            built_at="",
            dirty=False,
        )

    return BuildInfo(
        version=getattr(generated, "VERSION", BASE_VERSION),
        commit=getattr(generated, "COMMIT", "dev"),
        built_at=getattr(generated, "BUILT_AT", ""),
        dirty=bool(getattr(generated, "DIRTY", False)),
    )


def version_string() -> str:
    info = get_build_info()
    if info.commit:
        return f"{info.version} ({info.commit})"
    return info.version


def cli_version_string(prog: str) -> str:
    return f"{prog} {version_string()}"
