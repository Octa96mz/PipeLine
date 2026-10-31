import errno
import http.client
import json
import socket
import ssl
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from email.utils import parsedate_to_datetime
from typing import Any

from pipeline import __version__
from pipeline.errors import NetworkError, ProviderError, RateLimited
from pipeline.redact import redact_text

MAX_RESPONSE_BYTES = 5 * 1024 * 1024
MAX_BACKOFF_SECONDS = 30

# Sin Retry-After se espera 10 minutos: en una IP compartida de VPN insistir antes no ayuda.
DEFAULT_COOLDOWN_SECONDS = 600
MIN_COOLDOWN_SECONDS = 60
MAX_COOLDOWN_SECONDS = 86_400


# Errores de conexión tras los que la petición no pudo salir. EPERM y EACCES son los que da un
# cortafuegos o el kill switch de una VPN.
_UNSENT_ERRNOS = {
    errno.ENETUNREACH,
    errno.ENETDOWN,
    errno.EHOSTUNREACH,
    errno.ECONNREFUSED,
    errno.EPERM,
    errno.EACCES,
}


def _never_reached_server(reason: object) -> bool:
    # El tiempo agotado aquí es de conexión o TLS: urllib solo envuelve en URLError lo que falla
    # antes de esperar la respuesta. Lo que no se reconoce se cuenta: para no pasarse de una
    # cuota, es mejor contar de más que de menos.
    if isinstance(reason, socket.gaierror | ssl.SSLError | TimeoutError):
        return True
    return isinstance(reason, OSError) and reason.errno in _UNSENT_ERRNOS


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    # Una redirección podría llevar la petición a otro host: se trata como respuesta no válida.
    def redirect_request(self, *_args: object, **_kwargs: object) -> None:
        return None


def _build_opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(_NoRedirect())


def parse_retry_after(value: str | None, now: float) -> int:
    """Convierte Retry-After (segundos o fecha HTTP) en segundos de espera, dentro de unos topes."""
    seconds: float = DEFAULT_COOLDOWN_SECONDS
    if value:
        try:
            seconds = int(value.strip())
        except ValueError:
            try:
                seconds = parsedate_to_datetime(value).timestamp() - now
            except TypeError, ValueError:
                seconds = DEFAULT_COOLDOWN_SECONDS
    return int(min(max(seconds, MIN_COOLDOWN_SECONDS), MAX_COOLDOWN_SECONDS))


def _reject_constant(name: str) -> None:
    raise ValueError(f"Valor JSON no admitido: {name}")


class HttpClient:
    def __init__(
        self,
        on_request: Callable[[], None],
        timeout: int,
        max_retries: int,
        opener: urllib.request.OpenerDirector | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self._on_request = on_request
        self._timeout = timeout
        self._max_retries = max_retries
        self._opener = opener or _build_opener()
        self._sleep = sleep or time.sleep

    def get_json(self, url: str) -> Any:
        """Reintenta con backoff los fallos de red y los 5xx. Un 429 nunca se reintenta."""
        if not url.startswith("https://"):
            raise ProviderError("Solo se admiten URL https")

        for attempt in range(self._max_retries + 1):
            try:
                return self._get_once(url)
            except NetworkError:
                if attempt == self._max_retries:
                    raise
            except _ServerError as error:
                if attempt == self._max_retries:
                    raise ProviderError(str(error)) from None
            self._sleep(min(2**attempt, MAX_BACKOFF_SECONDS))
        raise AssertionError("El bucle siempre devuelve o lanza una excepción")

    def _get_once(self, url: str) -> Any:
        request = urllib.request.Request(  # noqa: S310 - get_json solo admite https
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": f"pipeline-market-bar/{__version__}",
            },
        )
        # Solo se cuentan las peticiones que pudieron llegar al servidor, también las de una
        # respuesta perdida: el proveedor pudo haberlas anotado en la cuota.
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                body = response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as error:
            self._on_request()
            with error:
                self._raise_for_status(error)
        except urllib.error.URLError as error:
            if not _never_reached_server(error.reason):
                self._on_request()
            raise NetworkError(redact_text(f"Sin conexión: {error}")) from None
        except (http.client.HTTPException, OSError) as error:
            self._on_request()
            raise NetworkError(redact_text(f"Sin conexión: {error}")) from None
        self._on_request()

        if len(body) > MAX_RESPONSE_BYTES:
            raise ProviderError("Respuesta demasiado grande")
        try:
            return json.loads(body, parse_constant=_reject_constant)
        except ValueError:
            raise ProviderError("Respuesta JSON no válida") from None

    def _raise_for_status(self, error: urllib.error.HTTPError) -> None:
        if error.code == 429:
            raise RateLimited(parse_retry_after(error.headers.get("Retry-After"), time.time()))
        if error.code >= 500:
            raise _ServerError(f"HTTP {error.code}")
        raise ProviderError(f"HTTP {error.code}")


class _ServerError(Exception):
    pass
