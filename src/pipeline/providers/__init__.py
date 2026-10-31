from pipeline.providers.base import Provider
from pipeline.providers.coingecko import CoinGecko

CRYPTO_PROVIDER: Provider = CoinGecko()

PROVIDERS: dict[str, Provider] = {CRYPTO_PROVIDER.name: CRYPTO_PROVIDER}
