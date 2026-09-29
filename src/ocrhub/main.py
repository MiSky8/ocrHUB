from contextlib import asynccontextmanager

import uvicorn

from ocrhub.api import build_registry, create_app
from ocrhub.mcp_server import mcp_asgi_app
from ocrhub.storage import build_store

registry = build_registry()
store = build_store()
app = create_app(registry, store)
mcp_app = mcp_asgi_app(registry, store)

# The MCP streamable-HTTP sub-app starts a TaskGroup inside its own lifespan
# (see StreamableHTTPSessionManager.run()). Starlette does not propagate
# lifespan events to mounted sub-apps automatically, so without this the
# session manager's TaskGroup is never initialized and any request to /mcp
# fails with "Task group is not initialized. Make sure to use run().".
# Compose the sub-app's lifespan into the outer FastAPI app's lifespan so
# both start/stop together.
_app_lifespan = app.router.lifespan_context


@asynccontextmanager
async def lifespan(app):
    async with _app_lifespan(app):
        async with mcp_app.router.lifespan_context(mcp_app):
            yield


app.router.lifespan_context = lifespan
app.mount("/mcp", mcp_app)


def run() -> None:
    uvicorn.run("ocrhub.main:app", host="0.0.0.0", port=8000)


if __name__ == "__main__":
    run()
