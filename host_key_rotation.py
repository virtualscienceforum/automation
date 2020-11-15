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


def host_key(timeslot: datetime.datetime) -> int:
    """Generate a host key for a specified time."""
    key_salt = os.getenv("HOST_KEY_SALT").encode()
    timestamp = timeslot.replace(second=0, microsecond=0, minute=0).timestamp()
    hashed = hashlib.sha512(int(timestamp).to_bytes(5, "big") + key_salt)
    return f"{int(hashed.hexdigest(), 16) % int(1e6):06}"


def update_host_key():
    """Update the host key of the speakers' corner user for the upcoming hour."""
    logging.info("Updated the host key.")
    zoom_request(
        requests.patch,
        common.ZOOM_API + "users/" + common.SPEAKERS_CORNER_USER_ID,
        data=json.dumps({
            "host_key": host_key(datetime.datetime.now(tz=pytz.UTC) + datetime.timedelta(hours=1))
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

    live = [m for m in sc_meetings if m.get("live")]

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
        and not m.get("live")
    ]

    starting_soon = upcoming_start - now < datetime.timedelta(hours=1)
    if starting_soon:
        common.zoom_request(
            requests.patch,
            f"{common.ZOOM_API}meetings/{upcoming['id']}",
            data=json.dumps({"settings": {"join_before_host": True}}),
        )
        logging.info(f"Allowed joining {upcoming['id']} before host.")

    running = bool(live)
    if (
        live
        and (
            starting_soon
            or live[0]["start_time"] < now - datetime.timedelta(minutes=90)
        )
    ):
        running = False
        for live_meeting in live:
            live_id = live_meeting["id"]
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
            logging.info(f"Stopped {live_id} and disabled joining.")

    for meeting in recent:
        common.zoom_request(
            requests.patch,
            f"{common.ZOOM_API}meetings/{meeting['id']}",
            data=json.dumps({"settings": {"join_before_host": False}}),
        )
        logging.info(f"Disabled joining {meeting['id']}")
    
    return running


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

WEEKLY_ANNOUNCEMENT_TEMPLATE = jinja2.Template("""Dear %recipient_name%,


This week the Speakers' Corner seminar series will have the following talks:

{% for talk in talks | sort(attribute="time") if now < talk.time < this_week  %}
- {{ talk.time.strftime("%A %B %-d %-H:%M UTC") }}: *{{ talk.title }}* by {{ talk.speaker_name }} ({{ talk.speaker_affiliation }})
{%- endfor %}

The next week's talks are:

{% for talk in talks | sort(attribute="time") if this_week < talk.time < next_week %}
- {{ talk.time.strftime("%A %B %-d %-H:%M UTC") }}: *{{ talk.title }}* by {{ talk.speaker_name }} ({{ talk.speaker_affiliation }})
{%- endfor %}

To view the abstracts and register please visit the [Speakers' Corner page](https://virtualscienceforum.org/#/speakers-corner).

Best regards,  
The VSF Organizers

---
You are receiving this email because you are signed up for the Speakers' Corner weekly program updates.  
To unsubscribe visit [this URL](%mailing_list_unsubscribe_url%).
""")


def weekly_speakers_corner_update(talks):
    now = datetime.datetime.now(tz=pytz.UTC)
    message = WEEKLY_ANNOUNCEMENT_TEMPLATE.render(
        talks=talks,
        now=now,
        this_week=now + datetime.timedelta(days=7),
        next_week=now + datetime.timedelta(days=14),
    )
    data = {
        "from": "VSF team <no-reply@mail.virtualscienceforum.org>",
        "to": "speakers_corner@mail.virtualscienceforum.org",
        "subject": "Speakers' Corner weekly schedule",
        "text": common.markdown_to_plain(message),
        "html": common.markdown_to_email(message),
    }

    return common.api_query(
        requests.post,
        common.MAILGUN_DOMAIN + "messages",
        data=data
    )


if __name__ == "__main__":
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    now = datetime.datetime.now(tz=pytz.UTC)
    exceptions = common.CollectExceptions()

    with exceptions:
        meeting_running = rotate_meetings()
        if not meeting_running:
            update_host_key()

    talks, _ = common.talks_data()
    logging.info(f"Loaded {len(talks)} talks.")
    for talk in talks:
        talk["time"] = talk["time"].replace(tzinfo=pytz.UTC)

    with exceptions:
        # Remind about a talk starting in 2 hours.
        try:
            upcoming_talk = next(
                talk for talk in talks
                if (talk["time"] - now).seconds // 3600 == 2
            )

            common.send_to_participants(
                template=REMINDER_TEMPLATE,
                subject=REMINDER_SUBJECT,
                talk=upcoming_talk,
                from_email="Speakers' Corner <no-reply@mail.virtualscienceforum.org>",
            )
            logging.info(f"Sent a reminder to {talk['zoom_meeting_id']} registrants.")
        except StopIteration:
            pass

    # Weekly emails sent Sunday UTC evening
    if now.hour == 20 and now.weekday() == 6:
        with exceptions:
            weekly_speakers_corner_update(talks)
            logging.info(f"Sent a weekly Speakers' corner announcement")

    exceptions.reraise()
