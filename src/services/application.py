from db.unit_of_work import UnitOfWork, UnitOfWorkFactory


class ApplicationService:
    def __init__(self, uow_factory: UnitOfWorkFactory | None = None) -> None:
        self.uow_factory = uow_factory or UnitOfWorkFactory()

    def create_unit_of_work(self) -> UnitOfWork:
        return self.uow_factory.create()
