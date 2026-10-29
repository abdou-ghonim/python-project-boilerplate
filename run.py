"""WSGI entry point. `run:app` for gunicorn, `python run.py` for development."""
from app import create_app

app = create_app()

if __name__ == "__main__":
    import config

    app.run(host="0.0.0.0", port=5000, debug=config.is_development())
