import uvicorn

from arena.api.app import create_app
from arena.infrastructure.config import HOST, PORT

app = create_app()

if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT)
