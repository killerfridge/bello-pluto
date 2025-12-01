import asyncio
import os
import httpx
from dotenv import load_dotenv

load_dotenv()

RIOT_API_KEY = os.getenv("RIOT_API_KEY")


class RiotUser:
    def __init__(self, name, tag, region, puuid):
        self.name = name
        self.tag = tag
        self.region = region
        self.puuid = puuid

    @classmethod
    async def create(cls, client: httpx.AsyncClient, name: str, tag: str, region: str):
        """
        Async Factory: Fetches the PUUID first, then returns the initialized class.
        """
        url = f"https://{region}.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{name}/{tag}"

        try:
            response = await client.get(url)
            response.raise_for_status()  # Raises error for 404, 403, 429, etc.
            data = response.json()
            return cls(name, tag, region, data["puuid"])
        except httpx.HTTPStatusError as e:
            print(f"Error fetching user {name}#{tag}: {e}")
            return None

    async def get_match_ids(self, client: httpx.AsyncClient, start=0, count=20):
        url = f"https://{self.region}.api.riotgames.com/lol/match/v5/matches/by-puuid/{self.puuid}/ids"
        params = {"type": "ranked", "start": start, "count": count}

        response = await client.get(url, params=params)
        response.raise_for_status()
        return response.json()

    async def get_match_data(self, client: httpx.AsyncClient, match_ids):
        # Semaphore limits us to 10 concurrent requests to respect Riot rate limits
        sem = asyncio.Semaphore(10)

        async def fetch_with_sem(match_id):
            async with sem:
                return await self._fetch_single_match(client, match_id)

        tasks = [fetch_with_sem(m_id) for m_id in match_ids]
        match_results = await asyncio.gather(*tasks)

        # Filter out failed requests (None)
        valid_results = [m for m in match_results if m]
        return self._parse_match_data(valid_results)

    async def _fetch_single_match(self, client: httpx.AsyncClient, match_id):
        url = f"https://{self.region}.api.riotgames.com/lol/match/v5/matches/{match_id}"
        try:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            print(f"Failed to fetch match {match_id}: {e}")
            return None

    def _parse_match_data(self, match_results):
        rows = []
        for data in match_results:
            info = data.get("info", {})
            participants = info.get("participants", [])

            # Find our specific player in the match
            player = next((p for p in participants if p["puuid"] == self.puuid), None)

            if player:
                # Calculate KDA safely
                deaths = player["deaths"] if player["deaths"] > 0 else 1
                kda = round((player["kills"] + player["assists"]) / deaths, 2)

                rows.append(
                    {
                        "match_id": data["metadata"]["matchId"],
                        "champion": player["championName"],
                        "win": player["win"],
                        "kills": player["kills"],
                        "deaths": player["deaths"],
                        "assists": player["assists"],
                        "kda": kda,
                        "gold_per_min": player["challenges"].get("goldPerMinute", 0),
                        "damage": player["totalDamageDealtToChampions"],
                        "lane": player["lane"],
                    }
                )
        return rows


async def async_main():
    # Context manager handles the session lifecycle (opening/closing connection)
    async with httpx.AsyncClient(headers={"X-Riot-Token": RIOT_API_KEY}) as client:
        # 1. Initialize User (Fetching PUUID)
        print("Fetching User...")
        user = await RiotUser.create(client, "Bawlstranglers", "2014", "europe")

        if not user:
            return

        # 2. Get Match IDs
        print(f"Fetching matches for {user.name}...")
        match_ids = await user.get_match_ids(client, start=0, count=10)

        # 3. Get Details for all matches
        print(f"Analyzing {len(match_ids)} matches...")
        stats = await user.get_match_data(client, match_ids)

        # 4. Print results
        import pandas as pd  # Optional: just to make it look nice in console

        df = pd.DataFrame(stats)
        print(df.to_string())


def main():
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
