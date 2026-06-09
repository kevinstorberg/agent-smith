import pytest

from src.services.base import SERVICE_REGISTRY, ServiceProtocol, create_service, register_service


@pytest.mark.unit
class TestServiceRegistry:
    def test_register_service_adds_to_registry(self):
        @register_service("test_svc_registry")
        class TestSvc:
            async def health_check(self):
                return True

            async def close(self):
                pass

            @classmethod
            def from_settings(cls, settings):
                return cls()

        assert "test_svc_registry" in SERVICE_REGISTRY

    def test_create_service_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown service"):
            create_service("nonexistent_service_xyz_99")

    def test_create_service_returns_instance(self):
        @register_service("test_svc_create")
        class CreateSvc:
            async def health_check(self):
                return True

            async def close(self):
                pass

            @classmethod
            def from_settings(cls, settings):
                return cls()

        svc = create_service("test_svc_create")
        assert isinstance(svc, ServiceProtocol)

    def test_registered_service_implements_protocol(self):
        @register_service("test_svc_protocol")
        class ProtoSvc:
            async def health_check(self):
                return True

            async def close(self):
                pass

            @classmethod
            def from_settings(cls, settings):
                return cls()

        svc = ProtoSvc()
        assert isinstance(svc, ServiceProtocol)
