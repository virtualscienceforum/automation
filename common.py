from functools import lru_cache
import os
from time import time

import jwt
import requests

ZOOM_API = "https://api.zoom.us/v2/"
SPEAKERS_CORNER_USER_ID = "D0n5UNEHQiajWtgdWLlNSA"

@lru_cache()
def zoom_headers(duration: int=10) -> dict:
    zoom_api_key = os.getenv("ZOOM_API_KEY")
    zoom_api_secret = os.getenv("ZOOM_API_SECRET")
    token = jwt.encode(
        # Create a payload of the token containing API Key & expiration time
        {"iss": zoom_api_key, "exp": time() + duration},
        zoom_api_secret,
        algorithm='HS256'
    ).decode('utf-8')

    return {'authorization': f'Bearer {token}', 'content-type': 'application/json'}


def speakers_corner_user_id() -> str:
    users = requests.get(ZOOM_API + "users", headers=zoom_headers()).json()["users"]
    sc_user_id = next(
        u["id"] for u in users
        if u["first_name"] == "Speakers'" and u["last_name"] == "Corner"
        )
    return sc_user_id