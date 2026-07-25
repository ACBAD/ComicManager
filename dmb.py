import httpx
import asyncio

class DMBClient:
    def __init__(self, base_url):
        self.base_url = base_url
        self.client = httpx.AsyncClient(base_url=self.base_url)

    async def fetch_comic_info(self, comic_id: str):
        url = f"/comics/{comic_id}"
        response = await self.client.get(url)
        response.raise_for_status()
        return response.json()

    async def close(self):
        await self.client.aclose()