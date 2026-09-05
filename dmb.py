import httpx

class DMBClient:
    def __init__(self, base_url, auth_token=None):
        self.base_url = base_url
        self.client = httpx.Client(base_url=self.base_url, timeout=10.0)
        if auth_token is None:
            self.client.headers['Authorization'] = 'Bearer viewer'
        else:
            self.client.headers['Authorization'] = f'Bearer {auth_token}'

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def check_health(self) -> None:
        self.client.get('/healthz', timeout=20.0).raise_for_status()

    def fetch_comic_info(self, comic_id: str):
        url = f"/v1/documents/{comic_id}"
        response = self.client.get(url)
        response.raise_for_status()
        return response.json()

    def close(self):
        self.client.close()
