"""Every API route of the app, for the guard scans.

FastAPI 0.139 includes a router lazily: app.routes holds an _IncludedRouter per include_router call,
and the APIRoutes live on its original_router. A scan over app.routes alone sees no APIRoute and
passes vacuously, so the guard tests walk through here and assert the walk found routes.
"""
from fastapi.routing import APIRoute


def api_routes(router, prefix: str = "") -> list[tuple[str, APIRoute]]:
    """[(full path, route)] for every APIRoute reachable from `router` (an app or an APIRouter)."""
    out: list[tuple[str, APIRoute]] = []
    for r in router.routes:
        if isinstance(r, APIRoute):
            out.append((prefix + r.path, r))
            continue
        original = getattr(r, "original_router", None)
        if original is not None:
            out.extend(api_routes(original, prefix + getattr(getattr(r, "include_context", None), "prefix", "")))
    return out


def dependency_calls(dependant) -> set:
    calls, stack = set(), [dependant]
    while stack:
        d = stack.pop()
        if d.call is not None:
            calls.add(d.call)
        stack.extend(d.dependencies)
    return calls
