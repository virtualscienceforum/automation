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

WEEKLY_ANNOUNCEMENT_TEMPLATE = jinja2.Template("""Dear %recipient_name%,


{% if this_week_talks %}This week the Speakers' Corner seminar series will have the following talks:

{% for talk in this_week_talks | sort(attribute="time") %}
- {{ talk.time.strftime("%A %B %-d %-H:%M UTC") }}: *{{ talk.title }}* by {{ talk.speaker_name }} ({{ talk.speaker_affiliation }})
{%- endfor %}{% endif %}

{% if next_week_talks %}The next week's talks {% if not this_week_talks %}in the Speakers' Corner seminar series {% endif %}are:

{% for talk in next_week_talks | sort(attribute="time") %}
- {{ talk.time.strftime("%A %B %-d %-H:%M UTC") }}: *{{ talk.title }}* by {{ talk.speaker_name }} ({{ talk.speaker_affiliation }})
{%- endfor %}{% endif %}

To view the abstracts and register please visit the [Speakers' Corner page](https://virtualscienceforum.org/#/speakers-corner).

Best regards,  
The VSF Organizers

---
You are receiving this email because you are signed up for the Speakers' Corner weekly program updates.  
To unsubscribe visit [this URL](%mailing_list_unsubscribe_url%).
""")


def weekly_speakers_corner_update(talks):
    # Filter out only the speakers' corner talks
    talks = [t for t in talks if t["event_type"] == "speakers_corner"]
    now = datetime.datetime.now(tz=pytz.UTC)
    week = datetime.timedelta(days=7)
    this_week_talks = list(filter(
        (lambda talk: now < talk["time"] < now + week),
        talks
    ))
    next_week_talks = list(filter(
        (lambda talk: now + week < talk["time"] < now + 2*week),
        talks
    ))

    if not any([this_week_talks, next_week_talks]):
        # Nothing to announce
        return

    message = WEEKLY_ANNOUNCEMENT_TEMPLATE.render(
        this_week_talks=this_week_talks,
        next_week_talks=next_week_talks,
    )
    data = {
        "from": "VSF team <no-reply@mail.virtualscienceforum.org>",
        "to": "speakers_corner@mail.virtualscienceforum.org",
        "subject": "Speakers' Corner weekly schedule",
        "text": common.markdown_to_plain(message),
        "html": common.markdown_to_email(message),
    }

    response = common.api_query(
        requests.post,
        common.MAILGUN_DOMAIN + "messages",
        data=data
    )
    logging.info("Sent the weekly update.")
    return response


RECORDING_AVAILABLE_TEMPLATE = jinja2.Template("""Dear {{speaker_name}},

The recording of your talk is available at [this URL]({{share_url}}).

Please review the video, and check if you approve its posting on our youtube channel.
Because the recording may start too early or end too late, please check the time when
the posted video should start and end.

After you've done that, please reply in your
[application issue](https://github.com/virtualscienceforum/virtualscienceforum/issues/{{workflow_issue}})
with the following phrase:

"I approve publishing of the recording. Talk start is HH:MM:SS, talk end is HH:MM:SS."

Naturally, you may download and use the video for your own purposes.

Best,  
Virtual Science Forum team
""")


def email_video_link(talk):
    """Send the presenter a link to their video, asking to confirm."""
    meeting_recordings = common.zoom_request(
        requests.get,
        common.ZOOM_API + f"/meetings/{talk['zoom_meeting_id']}/recordings"
    )
    if not len(meeting_recordings["recording_files"]):
        raise RuntimeError("No recordings found")

    message = RECORDING_AVAILABLE_TEMPLATE.render(
        share_url=meeting_recordings["share_url"],
        **talk,
    )

    response = common.api_query(
        requests.post,
        common.MAILGUN_DOMAIN + "messages",
        data={
            "from": "VSF team <no-reply@mail.virtualscienceforum.org>",
            "to": f"{talk['speaker_name']} <{talk['email']}>",
            "subject": "Approve your Speakers' Corner recording",
            "text": common.markdown_to_plain(message),
            "html": common.markdown_to_email(message),
        }
    )
    logging.info(f"Notified the speaker of {talk['zoom_meeting_id']} about recording.")
    return response


if __name__ == "__main__":
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    now = datetime.datetime.now(tz=pytz.UTC)
    exceptions = common.CollectExceptions()

    with exceptions:
        upcoming_talk = rotate_meetings()

    talks, _ = common.talks_data()
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

    # Weekly emails sent Sunday UTC evening
    if now.hour == 20 and now.weekday() == 6:
        with exceptions:
            weekly_speakers_corner_update(talks)
            logging.info(f"Sent a weekly Speakers' corner announcement")

    # Email the speaker their video link for a talk that took place 10h ago
    # In principle we could be faster, but this is to guarantee that the
    # Transcription finished.
    with exceptions:
        finished_talk = next(
            (
                talk for talk in talks
                if (now - talk["time"]).total_seconds() // 3600 == 9
            ),
            None
        )
        if finished_talk is not None:
            email_video_link(finished_talk)
            logging.info(
                "Sent a video link to the speaker from "
                f"{finished_talk['zoom_meeting_id']}"
            )

    exceptions.reraise()
