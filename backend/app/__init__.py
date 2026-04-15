"""Flask application factory."""
from flask import Flask
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_smorest import Api

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

    # OpenAPI / Swagger configuration
    app.config["API_TITLE"] = "DTU Diabetes ML Dashboard API"
    app.config["API_VERSION"] = "v1"
    app.config["OPENAPI_VERSION"] = "3.0.3"
    app.config["OPENAPI_URL_PREFIX"] = "/api"
    app.config["OPENAPI_SWAGGER_UI_PATH"] = "/swagger"
    app.config["OPENAPI_SWAGGER_UI_URL"] = (
        "https://cdn.jsdelivr.net/npm/swagger-ui-dist/"
    )

    # Initialize extensions
    db.init_app(app)
    migrate.init_app(app, db)
    CORS(app, resources={r"/api/*": {"origins": app.config["CORS_ORIGINS"]}})

    # Initialize flask-smorest (serves Swagger UI at /api/docs)
    api = Api(app)

    # Register blueprints through the smorest Api so routes are documented
    from app.routes.patients import patients_bp
    from app.routes.glucose import glucose_bp
    from app.routes.anomalies import anomalies_bp

    api.register_blueprint(patients_bp, url_prefix="/api/patients")
    api.register_blueprint(glucose_bp, url_prefix="/api/glucose")
    api.register_blueprint(anomalies_bp, url_prefix="/api/anomalies")

    # Health check endpoint (plain Flask route, not documented by smorest)
    @app.route("/api/health")
    def health():
        return {"status": "healthy"}

    # Health check endpoint (plain Flask route, not documented by smorest)
    @app.route("/api/hello")
    def hello():
        return {"il piu' bello del mondo": "guido"}

    return app
