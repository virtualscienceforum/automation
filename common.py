from functools import lru_cache
import os
from time import time

import jwt
import requests

ZOOM_API = "https://api.zoom.us/v2/"
SPEAKERS_CORNER_USER_ID = "D0n5UNEHQiajWtgdWLlNSA"

@lru_cache()
def zoom_headers(duration: int=100) -> dict:
    zoom_api_key = os.getenv("ZOOM_API_KEY")
    zoom_api_secret = os.getenv("ZOOM_API_SECRET")
    token = jwt.encode(
        # Create a payload of the token containing API Key & expiration time
        {"iss": zoom_api_key, "exp": time() + duration},
        zoom_api_secret,
        algorithm='HS256'
    ).decode('utf-8')

    return {'authorization': f'Bearer {token}', 'content-type': 'application/json'}


def zoom_request(method: callable, *args, **kwargs):
    """A minimal wrapper around requests for querying zoom API with error handling"""
    response = method(*args, **kwargs, headers=zoom_headers())
    if response.status_code > 299:
        raise RuntimeError(response.content.decode())

    if response.content:
        return response.json()


def speakers_corner_user_id() -> str:
    users = zoom_request(requests.get, ZOOM_API + "users")["users"]
    sc_user_id = next(
        u["id"] for u in users
        if u["first_name"] == "Speakers'" and u["last_name"] == "Corner"
        )
    return sc_user_id


def all_meetings(user_id) -> list:
    """Return all meetings by a user.
    
    Handles pagination, and adds ``live: True`` to a meeting that is running (if any).
    """
    meetings = []
    next_page_token = ""
    while True:
        meetings_page = zoom_request(
            requests.get,
            f"{ZOOM_API}users/{user_id}/meetings",
            params={"type": "scheduled", "page_size": 300, "next_page_token": next_page_token}
        )
        meetings += meetings_page["meetings"]
        next_page_token = meetings_page["next_page_token"]
        if not next_page_token:
            break
    
        live_meetings = zoom_request(
            requests.get,
            f"{ZOOM_API}users/{user_id}/meetings",
            params={"type": "scheduled", "page_size": 300, "next_page_token": next_page_token}
        )["meetings"]

        if live_meetings:
            for meeting in meetings:
                if meeting["id"] == live_meetings[0]["id"]:
                    meeting["live"] = True
        
        return meetings
