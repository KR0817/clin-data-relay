from pathlib import Path

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse


WORKBENCH_IMAGE_ASSETS = frozenset(
    {
        "workbench-central-context.webp",
        "workbench-review-empty.webp",
        "workbench-site-context.webp",
    }
)
NO_STORE_HEADERS = {
    "Cache-Control": "no-store, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}


def create_static_delivery_router(static_root: Path) -> APIRouter:
    """Serve the closed set of browser assets without mounting the project tree."""

    router = APIRouter()

    @router.get("/", include_in_schema=False)
    def homepage() -> FileResponse:
        return FileResponse(static_root / "index.html", headers=NO_STORE_HEADERS)

    @router.get("/static/css/app.css", include_in_schema=False)
    def stylesheet() -> FileResponse:
        return FileResponse(
            static_root / "css" / "app.css",
            media_type="text/css",
            headers=NO_STORE_HEADERS,
        )

    @router.get("/static/js/workbench.js", include_in_schema=False)
    def workbench_script() -> FileResponse:
        return FileResponse(
            static_root / "js" / "workbench.js",
            media_type="application/javascript",
            headers=NO_STORE_HEADERS,
        )

    @router.get("/static/img/{asset_name}", include_in_schema=False)
    def workbench_image(asset_name: str) -> FileResponse:
        if asset_name not in WORKBENCH_IMAGE_ASSETS:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="workbench_asset_not_found",
            )
        return FileResponse(
            static_root / "img" / asset_name,
            media_type="image/webp",
            headers=NO_STORE_HEADERS,
        )

    return router
