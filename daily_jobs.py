
#!/usr/bin/env python

import os
import hashlib
import datetime
import json
import logging

import pandas
import jinja2
import requests
import pytz
from dateutil.parser import parse

import common
from common import zoom_request

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

def weekly_speakers_corner_update(talks):
    # Filter out only the speakers' corner talks
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


def add_zoom_registrants_to_mailgun():
    """Add registrants from Zoom to Mailgun mailing list."""
    # Get all meetings
    meetings = common.all_meetings("me")

    # Filter by past meetings
    time_now = datetime.datetime.now(tz=pytz.UTC)
    time_yesterday = time_now - datetime.timedelta(days=60)
    past_meetings = [
        meeting for meeting in meetings
        if time_yesterday < pandas.to_datetime(meeting['start_time']) < time_now
    ]

    for meeting in past_meetings:
        # Get registrants
        registrants = common.meeting_registrants(meeting['id'])

        if( len(registrants) != 0 ):
            # Filter those who want to sign up for emails
            member_data = dict(members=json.dumps([
                dict(address=i['email'], name="{0} {1}".format(i.get('first_name'), i.get('last_name','')))
                for i in registrants if (i.get('May we contact you about future Virtual Science Forum events?','') == "Yes")
            ]))

            api_query(
                post, f'lists/{announce_list}/members.json',
                data=member_data
            )

    return

if __name__ == "__main__":
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    now = datetime.datetime.now(tz=pytz.UTC)
    exceptions = common.CollectExceptions()

    talks, _ = common.talks_data()
    talks = [talk for talk in talks if talk["event_type"] == "speakers_corner"]
    logging.info(f"Loaded {len(talks)} talks.")
    for talk in talks:
        talk["time"] = talk["time"].replace(tzinfo=pytz.UTC)

    # Weekly emails sent on Sundays
    if now.weekday() == 6:
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

    # Add people who signed up for the mailing list through Zoom registration
    # to our own mailgun mailinglist
    try:
        add_zoom_registrants_to_mailgun()
    except:
        logging.error("Could not move registrants to the mailgun list.")

    exceptions.reraise()
