import logging
import re

REDACTED = "[REDACTED]"

_QUERY_SECRET = re.compile(
    r"(?i)\b(api_token|api_key|apikey|token|key|x_cg_demo_api_key|x_cg_pro_api_key)=[^&\s\"'#]+"
)
_HEADER_SECRET = re.compile(r"(?i)\b(x-cg-demo-api-key|x-cg-pro-api-key|authorization)(\s*:\s*)\S+")


def redact_text(text: str) -> str:
    """Oculta las claves de cualquier texto: URL, cabeceras o mensajes de excepción."""
    text = _QUERY_SECRET.sub(lambda m: f"{m.group(1)}={REDACTED}", text)
    return _HEADER_SECRET.sub(lambda m: f"{m.group(1)}{m.group(2)}{REDACTED}", text)


class RedactingFormatter(logging.Formatter):
    # Actúa sobre el texto ya formateado para cubrir también las trazas de excepción,
    # que un logging.Filter no llega a ver.
    def format(self, record: logging.LogRecord) -> str:
        return redact_text(super().format(record))


def setup_logging(level: int = logging.WARNING) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(RedactingFormatter("%(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(level=level, handlers=[handler], force=True)
