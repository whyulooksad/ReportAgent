from __future__ import annotations

import uvicorn

from NL2SQL.agent_mod import app
from NL2SQL.config.settings import SERVICE_HOST, SERVICE_PORT


def main() -> None:
    uvicorn.run("NL2SQL.agent_mod:app", host=SERVICE_HOST, port=SERVICE_PORT, reload=True)


if __name__ == "__main__":
    main()
