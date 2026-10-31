from pipeline.db import Database


def active_cooldown(database: Database, provider_name: str, now: int) -> int | None:
    until = database.cooldown_until(provider_name)
    return until if until is not None and until > now else None


def offline_interval(base_seconds: int, streak: int, cap_seconds: int) -> int:
    """Intervalo tras `streak` pasadas sin conexión: se duplica a partir de la segunda."""
    if streak <= 1:
        return base_seconds
    # El tope limita la espera añadida: nunca acorta un intervalo normal más largo.
    return max(base_seconds, min(base_seconds * 2 ** (streak - 1), cap_seconds))


def next_attempt_at(
    database: Database, provider_name: str, base_seconds: int, cap_seconds: int
) -> int | None:
    # Cuenta cualquier intento, no solo los correctos: fallar no acelera el ritmo de llamadas.
    last = database.last_attempt(provider_name)
    if last is None:
        return None
    streak = database.offline_streak(provider_name)
    return last.finished_at + offline_interval(base_seconds, streak, cap_seconds)
