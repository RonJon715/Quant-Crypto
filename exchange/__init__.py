"""Exchange layer – authentication, REST/WS clients, and execution engine."""

from exchange.auth import load_credentials, sign_request
from exchange.executor import VWAPExecutor
from exchange.rest_client import CoinbaseRestClient
from exchange.ws_client import CoinbaseWebSocket

__all__ = [
    "sign_request",
    "load_credentials",
    "CoinbaseRestClient",
    "CoinbaseWebSocket",
    "VWAPExecutor",
]
