from src.routers.base import create_router


def test_create_router_applies_prefix_and_tags():
    router = create_router(prefix="/api/items", tags=["items"])

    assert router.prefix == "/api/items"
    assert router.tags == ["items"]


def test_create_router_defaults_tags_to_empty_list():
    router = create_router()

    assert router.prefix == ""
    assert router.tags == []
