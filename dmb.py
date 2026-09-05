import httpx
import asyncio

class DMBClient:
    def __init__(self, base_url, auth_token=None):
        self.base_url = base_url
        self.client = httpx.AsyncClient(base_url=self.base_url, timeout=10.0)
        if auth_token is None:
            self.client.headers['Authorization'] = 'Bearer viewer'
        else:
            self.client.headers['Authorization'] = f'Bearer {auth_token}'

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.client.aclose()

    async def fetch_comic_info(self, comic_id: str):
        url = f"/v1/documents/{comic_id}"
        response = await self.client.get(url)
        response.raise_for_status()
        return response.json()

    async def close(self):
        await self.client.aclose()
