"""Ошибки бизнес-логики. Сервисы не знают про HTTP: коды ответа проставляют обработчики в main."""


class DomainError(Exception):
    status_code = 400

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class NotFoundError(DomainError):
    """Объекта нет или нет доступа к нему - не раскрываем существование чужих заявок."""

    status_code = 404


class ConflictError(DomainError):
    """Действие недопустимо в текущем статусе или устарела версия."""

    status_code = 409


class ValidationFailedError(DomainError):
    """Данные заявки не проходят бизнес-правила (лимиты продукта, обязательный залог...)."""

    status_code = 422
