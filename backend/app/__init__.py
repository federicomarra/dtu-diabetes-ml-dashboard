"""Flask application factory."""
from flask import Flask
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate

db = SQLAlchemy()
migrate = Migrate()


def create_app(config_name: str = "development") -> Flask:
    """Create and configure the Flask application.

    Args:
        config_name: Configuration environment name
            ('development', 'production', 'testing').
    """
    app = Flask(__name__)

    # Load configuration
    from app.config import config_by_name
    app.config.from_object(config_by_name[config_name])

    # Initialize extensions
    db.init_app(app)
    migrate.init_app(app, db)
    CORS(app, resources={r"/api/*": {"origins": app.config["CORS_ORIGINS"]}})

    # Register blueprints
    from app.routes.patients import patients_bp
    from app.routes.glucose import glucose_bp
    from app.routes.anomalies import anomalies_bp

    app.register_blueprint(patients_bp, url_prefix="/api/patients")
    app.register_blueprint(glucose_bp, url_prefix="/api/glucose")
    app.register_blueprint(anomalies_bp, url_prefix="/api/anomalies")

    # Health check endpoint
    @app.route("/api/health")
    def health():
        return {"status": "healthy"}

    return app
