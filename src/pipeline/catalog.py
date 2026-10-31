# Nombre completo y etiqueta corta para la barra. Una acción fuera del catálogo usa su símbolo.
NAMES = {
    "BTC": ("Bitcoin", "BTC"),
    "ETH": ("Ethereum", "ETH"),
    "XRP": ("XRP", "XRP"),
    "NEAR": ("NEAR Protocol", "NEAR"),
    "SPX": ("S&P 500", "S&P"),
    "DJI": ("Dow Jones", "Dow"),
    "IXIC": ("Nasdaq Composite", "Nasdaq"),
    "IBEX": ("IBEX 35", "IBEX"),
    "AAPL": ("Apple", "AAPL"),
    "MSFT": ("Microsoft", "MSFT"),
    "NVDA": ("NVIDIA", "NVDA"),
    "AMZN": ("Amazon", "AMZN"),
    "GOOGL": ("Alphabet", "GOOGL"),
    "META": ("Meta Platforms", "META"),
    "TSLA": ("Tesla", "TSLA"),
}


def names(symbol: str) -> tuple[str, str]:
    return NAMES.get(symbol, (symbol, symbol))
