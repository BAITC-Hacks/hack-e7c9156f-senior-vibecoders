import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from app.config import Settings, settings
from app.routers.analyses import router
from app.services.analyses import AnalysisStore


def create_app(config: Settings | None = None) -> FastAPI:
    config = config or settings
    app = FastAPI(title="Senior Vibecoders API")
    app.state.store = AnalysisStore(config)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[config.frontend_origin],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(HTTPException)
    async def http_error(_request: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"error": str(exc.detail)}, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, _exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"error": "Некорректный запрос"})

    @app.exception_handler(Exception)
    async def unexpected_error(_request: Request, exc: Exception) -> JSONResponse:
        logging.exception("Unhandled API error", exc_info=exc)
        return JSONResponse(status_code=500, content={"error": "Внутренняя ошибка сервера"})

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(router)
    return app


app = create_app()
