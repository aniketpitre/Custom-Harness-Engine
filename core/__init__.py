__version__ = "0.3.0"


def _apply_env_aliases() -> None:
    """Settings are named PENKO_*; the engine reads them through one internal prefix.
    Earlier variable names are still accepted so existing setups keep working."""
    import os

    for key, value in list(os.environ.items()):
        if key.startswith("PENKO_"):
            os.environ["HARNESS_" + key[6:]] = value


_apply_env_aliases()
