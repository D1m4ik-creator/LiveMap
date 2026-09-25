def main() -> None:
    import uvicorn

    from livemap.core.config import get_settings

    settings = get_settings()
    uvicorn.run(
        "livemap.api.app:app",
        host=settings.app_host,
        port=settings.app_port,
    )
