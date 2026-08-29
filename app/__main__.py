import os

import uvicorn

if __name__ == "__main__":
    port = int(os.environ.get("PORT") or "8787")
    host = os.environ.get("HOST") or "0.0.0.0"
    uvicorn.run("app.main:app", host=host, port=port, reload=False)
