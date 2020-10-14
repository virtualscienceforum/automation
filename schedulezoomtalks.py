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
"I've now created a Zoom meeting for your talk, with meeting ID "
"{{ meeting_id }}. You'll receive a separate email with a host key."
)

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

Date: {{ meeting_date }} (yyyy-mm-dd)

Time slot: {{ meeting_start }} - {{ meeting_end }}

Zoom link: {{ meeting_zoom_link }}

Host key: {{ meeting_host_key }}

Thank you in advance for contributing to the Speakers' Corner!

- The VSF team
""")

REGISTRATION_QUESTIONS = {
    "questions": [
        {"field_name": "org", "required": True},
    ],

    "custom_questions": [
        {
            "title": "May we contact you about future Virtual Science Forum events?",
            "type": "single",
            "answers": ["Yes", "No"],
            "required": False,
        },
        {
            "title": "How did you hear about the Virtual Science Forum?",
            "type": "single",
            "answers": [
                "Email list",
                "One of the organizers",
                "A colleague (not an organizer)",
                "Other",
            ],
            "required": False,
        },
        {
            "title": (
                "Please confirm you agree to follow the participant instructions: "
                "http://virtualscienceforum.org/#/attendeeguide"
            ),
            "type": "single",
            "answers": ["Yes", "Yes"],
            "required": True,
        },
    ]
}



def schedule_zoom_talk(talk) -> Tuple[str, str]:
    # Form the talk registration body
    request_body = {
        "topic": "Speakers\' corner talk by %s"%(talk["speaker_name"]),
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

    patch_registration_questions(meeting_id)
    speaker_join_url = register_speaker(meeting_id, talk)["join_url"]
    patch_registration_notification(meeting_id)

    return meeting_id, response["registration_url"], speaker_join_url


def register_speaker(meeting_id, talk):
    # The splitting is approximate, and is done merely to satisfy the Zoom
    # registration requirements
    first_name, last_name = talk["speaker_name"].split(maxsplit=1) 
    request_payload = {
        "email": talk["email"],
        "first_name": first_name,
        "last_name": last_name,
        "org": talk["speaker_affiliation"],
        "custom_questions": [
            {
                "title": (
                    "Please confirm you agree to follow the participant instructions: "
                    "http://virtualscienceforum.org/#/attendeeguide"
                ),
                "value": "Yes",
            }
        ]
    }

    # Send request
    response = common.zoom_request(
        requests.post,
        f"{common.ZOOM_API}meetings/{meeting_id}/registrants",
        data=json.dumps(request_payload)
    )

    return response


def patch_registration_questions(meeting_id):
    response = common.zoom_request(
        requests.patch,
        f"{common.ZOOM_API}meetings/{meeting_id}/registrants/questions",
        data=json.dumps(REGISTRATION_QUESTIONS)
    )

    return response


def patch_registration_notification(meeting_id):

    # Form the talk registration body
    request_body = {
        "settings": {
            "registrants_email_notification": True,
        },
    }

    # Create the meeting
    response = common.zoom_request(
        requests.patch,
        f"{common.ZOOM_API}meetings/{meeting_id}",
        data=json.dumps(request_body)
    )

    return response


def notify_issue_about_zoom_meeting(repo, talk):
    issue_comment = ISSUE_RESPONSE_TEMPLATE.render(meeting_id=talk["zoom_meeting_id"])

    issue = repo.get_issue(number=talk["workflow_issue"])
    issue.create_comment(issue_comment)


def notify_author(talk, join_url) -> str:
    # Get the host key
    meeting_host_key = host_key(talk["time"])

    # Format the email body
    meeting_start = talk["time"].strftime('%H:%M')
    meeting_end = (talk["time"] + datetime.timedelta(hours=1)).strftime('%H:%M')
    meeting_date = talk["time"].strftime('%Y-%m-%d')

    email_text = EMAIL_TEMPLATE.render(author=talk["speaker_name"],
                                       meeting_zoom_link=join_url,
                                       meeting_host_key=meeting_host_key,
                                       meeting_talk_title=talk["title"],
                                       meeting_date=meeting_date,
                                       meeting_start=meeting_start,
                                       meeting_end=meeting_end)

    data = {
        "from": "Speakers' Corner <no-reply@mail.virtualscienceforum.org>",
        "to": "{0} <{1}>".format(talk["speaker_name"], talk["email"]),
        "subject": "Speakers' Corner talk",
        "text": common.markdown_to_plain(email_text),
        "html": common.markdown_to_email(email_text),
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

        meeting_id, registration_url, join_url = schedule_zoom_talk(talk)
        if meeting_id:
            talk["zoom_meeting_id"] = meeting_id
            talk["registration_url"] = registration_url
            # Add this talk to researchseminars.org
            # publish_to_researchseminars(talk)
            # Create comment in issue
            # notify_issue_about_zoom_meeting(repo, talk)
            # Email the author
            notify_author(talk, join_url)

            num_updated += 1

    return num_updated

if __name__ == "__main__":
    # Get a handle on the repository
    gh = github.Github(os.getenv("VSF_BOT_TOKEN"))
    target_branch = "test_zoom_meeting_registering_workflow"
    repo = gh.get_repo("virtualscienceforum/virtualscienceforum")

    # Read the talks file
    yaml = YAML()
    try:
        talks_data = repo.get_contents(common.TALKS_FILE, ref=target_branch)
        talks = yaml.load(StringIO(talks_data.decoded_content.decode()))
    except github.UnknownObjectException:
        talks_data = None
        talks = []

    # If we added Zoom links, we should update the file in the repo
    if (num_updated := schedule_talks(repo, talks)):
        commit_message = f"add Zoom link{'s' * (num_updated > 1)} for {num_updated} talks"
        serialized = StringIO()
        yaml.dump(talks, serialized)

        # repo.update_file(
        #     common.TALKS_FILE,
        #     commit_message,
        #     serialized.getvalue(),
        #     sha=talks_data.sha,
        #     branch=target_branch,
        # )
