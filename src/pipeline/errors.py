class PipelineError(Exception):
    """Error esperado que la CLI muestra sin traza. Su mensaje nunca incluye claves."""


class ConfigError(PipelineError):
    pass


class DatabaseError(PipelineError):
    pass


class KeystoreError(PipelineError):
    pass


class ProviderError(PipelineError):
    """Respuesta inutilizable: estado HTTP inesperado o contenido no válido."""


class NetworkError(ProviderError):
    """Sin conexión con el proveedor: sin red, DNS, tiempo agotado o kill switch de VPN."""


class RateLimited(ProviderError):
    """El proveedor pide esperar (HTTP 429). No es un fallo del colector."""

    def __init__(self, retry_after: int) -> None:
        super().__init__(f"HTTP 429: el proveedor pide esperar {retry_after} s")
        self.retry_after = retry_after


class FetchInProgress(PipelineError):
    pass
