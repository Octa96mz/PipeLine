from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

# Solo para anotaciones: los lectores importan este módulo y no deben cargar código de red.
if TYPE_CHECKING:
    from pipeline.http import HttpClient


@dataclass(frozen=True)
class ProviderQuote:
    symbol: str
    price: float
    change_percent: float | None
    price_time: int
    series: tuple[tuple[int, float], ...]


class Provider(Protocol):
    name: str
    display_name: str
    attribution: str
    # Períodos que cubren el minigráfico y la variación, para rotularlos.
    series_label: str
    change_label: str
    asset_class: str
    price_kind: str
    # Tiempo máximo sin refresco antes de dejar de mostrar y conservar el dato.
    retention_seconds: int

    def request_count(self, symbols: tuple[str, ...]) -> int:
        """Peticiones de una pasada, sin contar reintentos."""
        ...

    def fetch(
        self, symbols: tuple[str, ...], currency: str, client: HttpClient
    ) -> list[ProviderQuote]:
        """Devuelve los símbolos que venían bien formados; el resto simplemente se omite."""
        ...
