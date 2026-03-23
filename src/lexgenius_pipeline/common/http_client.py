import httpx


def create_http_client(
    timeout: float = 30.0,
    max_retries: int = 3,
) -> httpx.AsyncClient:
    transport = httpx.AsyncHTTPTransport(retries=max_retries)
    return httpx.AsyncClient(
        timeout=httpx.Timeout(timeout),
        follow_redirects=True,
        headers={"User-Agent": "lexgenius-pipeline/0.1.0"},
        transport=transport,
    )
