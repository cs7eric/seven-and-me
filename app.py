import os

from backend.app_factory import create_app
from backend.runner import run_dev_server


def _env_flag(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _should_start_schedulers() -> bool:
    hot_reload = _env_flag("FLASK_HOT_RELOAD", True)
    if __name__ == "__main__" and hot_reload and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        return False
    return True


app = create_app(start_schedulers=_should_start_schedulers())


if __name__ == '__main__':
    run_dev_server(app)
