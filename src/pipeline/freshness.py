from pipeline.db import FetchAttempt, Quote

FRESH = "fresh"
STALE = "stale"
EXPIRED = "expired"


def freshness(
    quote: Quote,
    now: int,
    stale_after_seconds: int,
    retention_seconds: int,
    last_attempt: FetchAttempt | None,
) -> str:
    # Se comprueba también al leer: los lectores no pueden borrar y el colector podría no correr.
    if now - quote.fetched_at > retention_seconds:
        return EXPIRED
    if now - quote.price_time > stale_after_seconds:
        return STALE
    # Un refresco fallido marca el dato como obsoleto al momento, sin esperar a que envejezca.
    if (
        last_attempt is not None
        and last_attempt.outcome != "ok"
        and last_attempt.finished_at > quote.fetched_at
    ):
        return STALE
    return FRESH
