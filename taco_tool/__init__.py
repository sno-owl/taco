from taco_tool.buildinfo import BASE_VERSION, get_build_info

__all__ = ["__version__", "build_info"]

__version__ = BASE_VERSION
build_info = get_build_info()
