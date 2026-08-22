from typing import Any


class AppError(Exception):
    code: str = "internal_error"
    message: str = "Внутренняя ошибка"

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.message = message or type(self).message
        self.code = code or type(self).code
        self.details = details or {}
        super().__init__(self.message)

    def __repr__(self) -> str:
        return f"{type(self).__name__}(code={self.code!r}, message={self.message!r})"


class NotFoundError(AppError):
    code = "not_found"
    message = "Ресурс не найден"


class TitleNotFoundError(NotFoundError):
    code = "title_not_found"
    message = "Тайтл не найден"

    def __init__(self, title_id: int) -> None:
        super().__init__(f"Тайтл {title_id} не найден", details={"title_id": title_id})


class ValidationError(AppError):
    code = "validation_error"
    message = "Данные не прошли валидацию"

    def __init__(
        self,
        message: str,
        *,
        field: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        payload = dict(details or {})
        if field:
            payload["field"] = field
        super().__init__(message, details=payload)


class ConflictError(AppError):
    code = "conflict"
    message = "Конфликт"


class DuplicateTitleError(ConflictError):
    code = "duplicate_title"

    def __init__(self, name: str, year: int | None) -> None:
        super().__init__(
            f"Тайтл {name} ({year or '-'}) уже есть",
            details={"name": name, "year": year},
        )


class AuthenticationError(AppError):
    code = "unauthorized"
    message = "Требуется авторизация Telegram"


class PermissionDeniedError(AppError):
    code = "forbidden"
    message = "Недостаточно прав"
