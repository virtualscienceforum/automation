#!/usr/bin/env python

import os
import hashlib
import datetime
import json

import requests
import pytz

import common


def host_key(timeslot: datetime.datetime) -> int:
    """Generate a host key for a specified time."""
    key_salt = os.getenv("HOST_KEY_SALT").encode()
    timestamp = timeslot.replace(second=0, microsecond=0, minute=0).timestamp()
    hashed = hashlib.sha512(int(timestamp.to_bytes(5, "big")) + key_salt)
    return f"{int(hashed.hexdigest(), 16) % int(1e7):06}"


def update_host_key():
    """Update the host key of the speakers' corner user for the upcoming hour."""
    response = requests.patch(
        common.ZOOM_API + "users/" + common.SPEAKERS_CORNER_USER_ID,
        headers=common.zoom_headers(),
        data=json.dumps({
            "host_key": host_key(datetime.datetime.now() + datetime.timedelta(hours=1))
        })
    )
    if response.status_code != 204:
        raise RuntimeError(response.content.decode())