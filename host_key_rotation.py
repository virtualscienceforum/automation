#!/usr/bin/env python

import os
import hashlib
import datetime
import json
import logging

import jinja2
import requests
import pytz
from dateutil.parser import parse

import common
from common import zoom_request

def host_key(zoom_meeting_id: int) -> str:
    """Generate a host key for a specified time."""
    key_salt = os.getenv("HOST_KEY_SALT").encode()
    hashed = hashlib.sha512(zoom_meeting_id.to_bytes(10, "big") + key_salt)
    return f"{int(hashed.hexdigest(), 16) % int(1e6):06}"


def update_host_key(key: str):
    """Update the host key of the speakers' corner user for the upcoming hour."""
    logging.info("Updated the host key.")
    zoom_request(
        requests.patch,
        common.ZOOM_API + "users/" + common.SPEAKERS_CORNER_USER_ID,
        data=json.dumps({"host_key": key})
    )


def rotate_meetings():
    """Update the Speakers' corner meeting settings and statuses.

    1. Stop a running meeting if it runs for too long.
    2. Disable joining before host on recent meetings to prevent restarting.
    3. If there is an upcoming meeting in less than an hour, allow joining
       before host.
    """
    now = datetime.datetime.now(tz=pytz.UTC)
    hour = datetime.timedelta(hours=1)
    sc_meetings = common.all_meetings(common.SPEAKERS_CORNER_USER_ID)
    for m in sc_meetings:
        m["start_time"] = parse(m["start_time"])

    for recent in (
        m for m in sc_meetings
        if now - hour > m["start_time"] > now - 2*hour
    ):
        recent_id = recent["id"]
        if recent.get("live"):
            common.zoom_request(
                requests.put,
                f"{common.ZOOM_API}meetings/{recent_id}/status",
                json={"action": "end"},
            )
            logging.info(f"Stopped {recent_id}.")

        common.zoom_request(
            requests.patch,
            f"{common.ZOOM_API}meetings/{recent_id}",
            json={"settings": {"join_before_host": False}},
        )
        logging.info(f"Disabled joining {recent_id}.")


    for upcoming in (
        m for m in sc_meetings
        if now + hour > m["start_time"] > now
    ):
        upcoming_id = upcoming['id']
        common.zoom_request(
            requests.patch,
            f"{common.ZOOM_API}meetings/{upcoming_id}",
            json={"settings": {"join_before_host": True}},
        )
        logging.info(f"Allowed joining {upcoming_id}.")

        update_host_key(host_key(upcoming_id))


# Emails

REMINDER_SUBJECT = "Speakers' Corner presentation by {speaker_name} starting soon"

REMINDER_TEMPLATE = jinja2.Template("""Dear %recipient_name%,

Thank you for registering for today's Speakers' Corner talk by {{speaker_name}}!
The talk will begin in two hours ({{time.strftime('%-H:%M')}} UTC).

Your can join starting five minutes before the talk using your [registration link](%recipient.join_url%).

The title and the abstract of the talk are below.

**Title:** {{title}}

**Abstract:** {{abstract}}

Enjoy the talk,  
The Virtual Science Forum team
""")

if __name__ == "__main__":
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    common.wait_until(45)
    now = datetime.datetime.now(tz=pytz.UTC)
    exceptions = common.CollectExceptions()

    with exceptions:
        rotate_meetings()

    talks, _ = common.talks_data()
    talks = [talk for talk in talks if talk["event_type"] == "speakers_corner"]
    logging.info(f"Loaded {len(talks)} talks.")
    for talk in talks:
        talk["time"] = talk["time"].replace(tzinfo=pytz.UTC)

    with exceptions:
        # Remind about a talk starting in 2 hours.
        upcoming_talk = next(
            (
                talk for talk in talks
                if (talk["time"] - now).total_seconds() // 3600 == 2
            ),
            None
        )
        if upcoming_talk is not None:
            logging.info(
                f"Found a talk with ID {upcoming_talk['zoom_meeting_id']}"
                " that is starting soon."
            )

            common.send_to_participants(
                template=REMINDER_TEMPLATE,
                subject=REMINDER_SUBJECT,
                talk=upcoming_talk,
                from_email="Speakers' Corner <no-reply@mail.virtualscienceforum.org>",
            )
            logging.info(
                f"Sent a reminder to {upcoming_talk['zoom_meeting_id']} registrants."
            )

    exceptions.reraise()
