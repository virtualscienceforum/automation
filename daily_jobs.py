
#!/usr/bin/env python

import datetime
import json
import logging

import jinja2
import requests
import pytz

import common
from common import api_query

LIST = 'vsf-announce'
MEMBERS_ENDPOINT = f'lists/{LIST}@{common.MAILGUN_DOMAIN}members.json'

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


def subscribe_registrants_to_mailinglist(zoom_meeting_id):
    """Add registrants from Zoom to Mailgun mailing list."""
    # Get registrants
    registrants = common.meeting_registrants(zoom_meeting_id)

    if registrants:
        # Filter those who want to sign up for emails
        member_data = dict(members=json.dumps([
            dict(address=i['email'], name="{0} {1}".format(i.get('first_name'), i.get('last_name','')))
            for i in registrants if (i.get('May we contact you about future Virtual Science Forum events?','') == "Yes")
        ]))

        api_query(requests.post, MEMBERS_ENDPOINT, data=member_data)

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

    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    for talk in talks:
        # Select the talks from yesterday
        if not(
            datetime.timedelta(days=2) > today - talk["time"] > datetime.timedelta(days=1)
        ):
            continue

        # Email speakers' corner speakers a video link for approval.
        if talk["event_type"] == "speakers_corner":
            with exceptions:
                email_video_link(talk)
                logging.info(
                    "Sent a video link to the speaker from "
                    f"{talk['zoom_meeting_id']}"
                )

        # Add people who signed up for the mailing list through Zoom registration
        # to our own mailgun mailing list
        with exceptions:
            subscribe_registrants_to_mailinglist(talk["zoom_meeting_id"])

    exceptions.reraise()
