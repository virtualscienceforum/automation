import os
import secrets
from io import StringIO
from typing import Tuple
import datetime
import json
import github
import requests
from ruamel.yaml import YAML
import jinja2
import pytz

import common
from researchseminarsdotorg import publish_to_researchseminars
from host_key_rotation import host_key


ISSUE_RESPONSE_TEMPLATE = jinja2.Template(
"""I've now created a Zoom meeting for your talk, with meeting ID
   {{ meeting_id }}. You'll receive a separate email with a host key.
""")

EMAIL_TEMPLATE = jinja2.Template(
"""Hi {{ author }},

A Zoom meeting has now been scheduled for your Speakers' Corner talk.
Five minutes before your timeslot starts, you and your audience will be
able to join the meeting. You will then be able to claim the host role by
using the host key below. After an hour the meeting will automatically
be terminated. Once the recording finishes processing, you will get the
opportunity to cut out parts of it.

Your meeting information:
Talk title: {{ meeting_talk_title }}
Date: {{ meeting_date }}
Time slot: {{ meeting_start }} - {{ meeting_end }}

Zoom link: {{ meeting_zoom_link }}
Host key: {{ meeting_host_key }}

Thank you in advance for contributing to the Speakers' Corner!
- The VSF team
""")


def schedule_zoom_talk(talk) -> Tuple[str, str]:
    # Form the talk registration body
    request_body = {
      "topic": "Speakers\' corner talk by %s"%(talk.get("name")),
      "type": 2, # Scheduled meeting
      "start_time": talk["time"].strftime('%Y-%m-%dT%H:%M:%S'),
      "timezone": "UTC",
      "duration": 60,
      "schedule_for": common.SPEAKERS_CORNER_USER_ID,

      # Generate a password for the meeting. This is required since
      # otherwise the meeting room will be forced. Zoom limits the
      # password length to max 10 characters.
      "password": secrets.token_urlsafe(16)[:10],

      # Meeting settings
      "settings": {
        "host_video": True,
        "participant_video": False,
        "cn_meeting": False,  # Host the meeting in China?
        "in_meeting": False,  # Host the meeting in India?

        # This will be switched to True shortly before the meeting starts
        # by the VSF bot. It will also be switched back to False afterwards
        "join_before_host": False,
        "mute_upon_entry": True,
        "watermark": False,  # Don't add a watermark when screensharing
        "use_pmi": False, # Don't use Personal Meeting ID, but generate one
        "approval_type": 0, # Automatically approve
        "close_registration" : True, # Close registration after event date
        "waiting_room" : False,    # No waiting room
        "audio": "both",
        "auto_recording": "cloud",
        "enforce_login": False,
        "alternative_hosts": "",

        # Email notifications are turned off when created, so that we can
        # register the speaker without them receiving an invitation to
        # their own talk. They will receive a separate email with info.
        # This will be turned on with a PATCH once the speaker is registered.
        "registrants_email_notification": False,
        "contact_email": "vsf@virtualscienceforum.org",
      }
    }

    # Create the meeting
    response = common.zoom_request(
        requests.post,
        f"{common.ZOOM_API}users/{common.SPEAKERS_CORNER_USER_ID}/meetings",
        data=json.dumps(request_body)
    )

    meeting_id = response["id"]

    register_speaker(meeting_id, talk)
    patch_registration_questions(meeting_id)
    patch_registration_notification(meeting_id)

    return meeting_id, response["registration_url"]


def register_speaker(meeting_id, talk) -> int:
    request_payload = {
      "email": talk["email"],
      "first_name": talk["speaker_name"],
    }

    # Send request
    response = common.zoom_request(
        requests.post,
        f"{common.ZOOM_API}users/{common.SPEAKERS_CORNER_USER_ID}/meetings/{meeting_id}/registrants",
        data=json.dumps(request_payload)
    )

    return response.status


def patch_registration_questions(meeting_id) -> int:

    request_body = {
        "questions": [
          {"field_name": "First Name", "required": True},
          {"field_name": "Last Name", "required": True},
          {"field_name": "Email Address", "required": True},
          {"field_name": "Confirm Email Address", "required": True},
          {"field_name": "Organization", "required": True},
        ],

        "custom_questions": [
          {
            "title": "May we contact you about future Virtual Science Forum events?",
            "type": "single", # short or single
            "answers": ["Yes", "No"], # only single
            "required": True
          },
          {
            "title": "How did you hear about the Virtual Science Forum?",
            "type": "single", # short or single
            "answers": ["Email list",
                        "One of the organizers",
                        "A colleague (not an organizer)",
                        "Other"],
            "required": True
          },
          {
            "title": "Please confirm you have read the participant instructions: \
                      http://virtualscienceforum.org/#/attendeeguide*",
            "type": "short", # short or single
            "required": True
          },
        ]
    }

    response = common.zoom_request(
        requests.patch,
        f"{common.ZOOM_API}users/{common.SPEAKERS_CORNER_USER_ID}/meetings/{meeting_id}/registrants/questions",
        pdata=json.dumps(request_body)
    )

    return response.status

def patch_registration_notification(meeting_id) -> int:

    # Form the talk registration body
    request_body = {
      "settings": {
        "registrants_email_notification": True,
      },
    }

    # Create the meeting
    response = common.zoom_request(
        requests.patch,
        f"{common.ZOOM_API}users/{common.SPEAKERS_CORNER_USER_ID}/meetings/{meeting_id}",
        data=json.dumps(request_body)
    )

    return response.status

def notify_issue_about_zoom_meeting(repo, talk):
    issue_comment = ISSUE_RESPONSE_TEMPLATE.render(meeting_id=talk["meeting_id"])

    issue = repo.get_issue(number=talk["workflow_issue"])
    issue.create_comment(issue_comment)


def notify_author(talk, join_url) -> str:
    # Get the host key
    meeting_host_key = host_key(talk["time"])

    # Format the email body
    meeting_start = talk["time"]
    meeting_end = meeting_start + datetime.timedelta(hours=1)
    email_text = EMAIL_TEMPLATE.render(author=talk["speaker_name"],
                                       meeting_zoom_link=join_url,
                                       meeting_host_key=meeting_host_key,
                                       meeting_talk_title=talk["title"],
                                       meeting_date=meeting_start.date,
                                       meeting_start=meeting_start.time,
                                       meeting_end=meeting_end.time)

    data = {
        "from": "Speakers' Corner <no-reply@mail.virtualscienceforum.org>",
        "to": "{0} <{1}>".format(talk["speaker_name"], talk["email"]),
        "subject": "Speakers' Corner talk",
        "text": email_text,
        "html": email_text,
    }

    return common.api_query(
        requests.post,
        f"{common.MAILGUN_DOMAIN}messages",
        data=data
    )

def schedule_talks(repo, talks) -> int:
    num_updated = 0
    for talk in talks:
        # If we are not processing a speakers corner talk, or if the
        # zoom meeting id has already been set, there's nothing left to do
        if "zoom_meeting_id" in talk or talk["event_type"] != "speakers_corner":
            continue

        meeting_id, join_url = schedule_zoom_talk(talk)
        if meeting_id:
            talk["zoom_meeting_id"] = meeting_id
            # Add this talk to researchseminars.org
            # publish_to_researchseminars(talk)
            # Create comment in issue
            notify_issue_about_zoom_meeting(repo, talk)
            # Email the author
            notify_author(talk, join_url)

            num_updated += 1

    return num_updated

if __name__ == "__main__":
    # Get a handle on the repository
    gh = github.Github(os.getenv("VSF_BOT_TOKEN"))
    repo = gh.get_repo("virtualscienceforum/virtualscienceforum")

    # Read the talks file
    yaml = YAML()
    try:
        talks_data = repo.get_contents(common.TALKS_FILE, ref="test_zoom_meeting_registering_workflow")
        talks = yaml.load(StringIO(talks_data.decoded_content.decode()))
    except github.UnknownObjectException:
        talks_data = None
        talks = []

    # If we added Zoom links, we should update the file in the repo
    if (num_updated := schedule_talks(repo, talks) ):
        serialized = StringIO()
        yaml.dump(talks, serialized)

        repo.update_file(
          common.TALKS_FILE, f"Added Zoom link{1} for {0} scheduled speakers\'"\
                       "corner talk{1}".format(num_updated,'' if num_updated == 1 else 's'),
          serialized.getvalue(),
          sha=talks_data.sha,
          branch='test_zoom_meeting_registering_workflow'
        )
