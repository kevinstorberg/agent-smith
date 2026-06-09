import logging

from config.loader import load_default_config
from config.models import MemoryConfig
from lib.agent_smith_core.singleton import singleton
from memory.base import MemoryBackend

logger = logging.getLogger(__name__)


def create_memory_backend(config: MemoryConfig) -> MemoryBackend:
    """Create a memory backend from explicit memory config."""
    backend_name = config.backend.lower()
    logger.info(f"Initializing memory backend: {backend_name}")

    if backend_name in ("in_memory", "faiss"):
        from memory.backends.in_memory import InMemoryVectorBackend

        return InMemoryVectorBackend(dimension=config.embedding_dimension)
    elif backend_name == "pgvector":
        from memory.backends.pgvector import PGVectorBackend

        return PGVectorBackend()
    elif backend_name == "pinecone":
        from memory.backends.pinecone import PineconeBackend

        return PineconeBackend()
    else:
        raise ValueError(f"Unknown memory backend: {backend_name}. " f"Valid options: in_memory, pgvector, pinecone")


@singleton
def get_backend() -> MemoryBackend:
    """Get or create singleton memory backend instance."""
    config = load_default_config()
    return create_memory_backend(config.memory)


# Expose reset for testing
reset_backend = get_backend.reset
