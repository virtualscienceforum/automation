#!/usr/bin/env python

import os
import hashlib
import datetime
import json

import requests
import pytz
from dateutil.parser import parse

import common
from common import zoom_request


def host_key(timeslot: datetime.datetime) -> int:
    """Generate a host key for a specified time."""
    key_salt = os.getenv("HOST_KEY_SALT").encode()
    timestamp = timeslot.replace(second=0, microsecond=0, minute=0).timestamp()
    hashed = hashlib.sha512(int(timestamp.to_bytes(5, "big")) + key_salt)
    return f"{int(hashed.hexdigest(), 16) % int(1e7):06}"


def update_host_key():
    """Update the host key of the speakers' corner user for the upcoming hour."""
    zoom_request(
        requests.patch,
        common.ZOOM_API + "users/" + common.SPEAKERS_CORNER_USER_ID,
        data=json.dumps({
            "host_key": host_key(datetime.datetime.now() + datetime.timedelta(hours=1))
        })
    )


def rotate_meetings():
    """Update the Speakers' corner meeting settings and statuses.
    
    1. If there is an upcoming meeting in less than an hour, allow joining
       before host.
    2. Stop the running meeting if there is an upcoming one or if it runs for too long.
    3. Disable joining before host on recent meetings to prevent restarting.
    """
    now = datetime.datetime.now(tz=pytz.UTC)
    sc_meetings = common.all_meetings(common.SPEAKERS_CORNER_USER_ID)
    for m in sc_meetings:
        m["start_time"] = parse(m["start_time"])

    live = [m for m in sc_meetings if m["live"]]

    try:
        upcoming = min(
            (m for m in sc_meetings if m["start_time"] > now),
            key=(lambda meeting: meeting["start_time"])
        )
        upcoming_start = upcoming["start_time"]
    except ValueError:
        upcoming = None
        upcoming_start = now + datetime.timedelta(weeks=1)
    
    recent = [
        m for m in sc_meetings
        if (now > m["start_time"] > now - datetime.timedelta(hours=2))
        and not m["live"]
    ]

    starting_soon = upcoming_start - now < datetime.timedelta(hours=1)
    if starting_soon:
        common.zoom_request(
            requests.patch,
            f"{common.ZOOM_API}meetings/{upcoming['id']}",
            data=json.dumps({"settings": {"join_before_host": True}}),
        )

    if (
        live
        and (
            starting_soon 
            or live[0]["start_time"] < now - datetime.timedelta(minutes=90)
        )
    ):
        live_id = live[0]["id"]
        common.zoom_request(
            requests.put,
            f"{common.ZOOM_API}meetings/{live_id}/status",
            data=json.dumps({"action": "end"}),
        )
        common.zoom_request(
            requests.patch,
            f"{common.ZOOM_API}meetings/{live_id}",
            data=json.dumps({"settings": {"join_before_host": False}}),
        )

    for meeting in recent:
        common.zoom_request(
            requests.patch,
            f"{common.ZOOM_API}meetings/{meeting['id']}",
            data=json.dumps({"settings": {"join_before_host": False}}),
        )

if __name__ == "__main__":
    update_host_key()
    rotate_meetings()