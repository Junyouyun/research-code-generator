from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes_auth import router as auth_router
from app.api.routes_code import router as code_router
from app.api.routes_conversations import router as conversations_router
from app.api.routes_graph import router as graph_router
from app.api.routes_memories import router as memories_router
from app.api.routes_projects import router as projects_router
from app.api.routes_qa import router as qa_router
from app.api.routes_reports import router as reports_router
from app.api.routes_upload import router as upload_router
from app.core.database import init_database


def create_app() -> FastAPI:
    app = FastAPI(title="Research Code Generator")

    @app.on_event("startup")
    def startup() -> None:
        init_database()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(auth_router, prefix="/api")
    app.include_router(upload_router, prefix="/api")
    app.include_router(conversations_router, prefix="/api")
    app.include_router(memories_router, prefix="/api")
    app.include_router(graph_router, prefix="/api")
    app.include_router(projects_router, prefix="/api")
    app.include_router(reports_router, prefix="/api")
    app.include_router(code_router, prefix="/api")
    app.include_router(qa_router, prefix="/api")

    return app


app = create_app()
