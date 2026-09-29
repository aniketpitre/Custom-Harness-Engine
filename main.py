import uvicorn

from core.home import load_env

load_env()

from core.gateway.api import app, registry
from core.settings import settings


def reload_registry() -> bool:
    """Transactional reload of agent profiles without restarting the process."""
    return registry.reload()


if __name__ == "__main__":
    st = settings()
    uvicorn.run(app, host=st.api_host, port=st.api_port)
