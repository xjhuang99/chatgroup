"""
ACTR entry point. Application logic lives under the ``actr`` package.
"""

from actr.factory import app

__all__ = ["app"]

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
