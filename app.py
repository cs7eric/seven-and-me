from backend.app_factory import create_app
from backend.runner import run_dev_server

app = create_app()


if __name__ == '__main__':
    run_dev_server(app)
