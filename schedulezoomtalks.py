import os
import github
import requests
import secrets
import common
from researchseminarsdotorg import publish_to_researchseminars
from host_key_rotation import host_key
from io import StringIO
from ruamel.yaml import YAML

ISSUE_RESPONSE_TEMPLATE = jinja2.Template(
"""Hi again! I've now created a Zoom meeting for your talk, with meeting ID
   {{ meeting_id }}. You'll receive a separate email with a host key.
""")

def schedule_zoom_talk(talk) -> string:

    # Form the talk registration body
    request_body =
    {
      "topic": "Speakers\' corner talk by %s"%(talk.get("name")),
      "type": 2, # Scheduled meeting
      "start_time": talk["time"],
      "timezone": "UTC",
      "duration": 60,
      "schedule_for": common.SPEAKERS_CORNER_USER_ID,

      # Generate a password for the meeting. This is required since
      # otherwise the meeting room will be forced. Zoom limits the
      # password length to max 10 characters.
      "password": secrets.token_urlsafe(10),

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
      },


    }

    # Create the meeting
    response = zoom_request(
        requests.post,
        f"{common.ZOOM_API}users/{user_id}/meetings",
        params={"body":request_body}
    )

    if( response.status != 201 ):
        return None

    # Extract meeting id
    meeting_id = response.id
    # Register the speaker
    register_speaker(meeting_id)
    # Update the meeting registration questions
    patch_registration_questions(meeting_id, talk)
    # Update the registrants email notification
    patch_registration_notification(meeting_id)

    return meeting_id

def register_speaker(meeting_id, talk) -> int:

    request_payload = {
      "email": talk["email"],
      "first_name": "talk["speaker_name"],
    }

    # Send request
    response = zoom_request(
        requests.post,
        f"{common.ZOOM_API}users/{user_id}/meetings/{meeting_id}/registrants",
        params={"body":request_body}
    )

    # 201: Registration created
    # 300: Meeting {meetingId} is not found or has expired.
    # 400:
        # Error Code: 1010
        # User does not belong to this account: {accountId}.
        # Error Code: 3003
        # You are not the meeting host.
        # Error Code: 3000
        # Cannot access meeting info.
    # 404: Meeting not found.
        # Error Code: 1001
        # Meeting host does not exist: {userId}.
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
            "required": true
          },
          {
            "title": "How did you hear about the Virtual Science Forum?",
            "type": "single", # short or single
            "answers": ["Email list",
                        "One of the organizers",
                        "A colleague (not an organizer)",
                        "Other"],
            "required": true
          },
          {
            "title": "Please confirm you have read the participant instructions: \
                      http://virtualscienceforum.org/#/attendeeguide*",
            "type": "short", # short or single
            "required": true
          },
        ]
    }

    response = zoom_request(
        requests.patch,
        f"{common.ZOOM_API}users/{user_id}/meetings/{meeting_id}/registrants/questions",
        params={"body":request_body}
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
    response = zoom_request(
        requests.patch,
        f"{common.ZOOM_API}users/{user_id}/meetings/{meeting_id}",
        params={"body":request_body}
    )

    return response.status

def notify_issue_about_zoom_meeting(repo, talk):
    issue_comment = ISSUE_RESPONSE_TEMPLATE.render(meeting_id=meeting_id)

    try:
        issue = repo.get_issue(number=talk["workflow_issue"])
        issue.create_comment(issue_comment)
    except:
        print("Couldn't create issue comment. The content would have been: ")
        print(issue_comment)

def notify_author(talk):
    # Get the host key
    meeting_host_key = host_key(talk["time"]

    # TODO: Email body, send email

def schedule_talks(repo, talks) -> int:
    num_updated = 0
    for talk in talks:
        # If we are not processing a speakers corner talk, or if the
        # zoom meeting id has already been set, there's nothing left to do
        if "zoom_meeting_id" in talk or talk["event_type"] != "speakers_corner":
            continue

        if( meetind_id := schedule_zoom_talk(talk) ):
            talk.get("zoom_meeting_id") = meeting_id
            # Add this talk to researchseminars.org
            publish_to_researchseminars(talk)
            # Create comment in issue
            notify_issue_about_zoom_meeting(repo, talk)
            # Email the author
            notify_author(talk)


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
          TALKS_FILE, f"Added Zoom link{1} for {0} scheduled speakers\'"\
                       "corner talk{1}".format(num_updated,'' if num_updated == 1 else 's'),
          serialized.getvalue(),
          sha=talks_data.sha,
          branch='test_zoom_meeting_registering_workflow'
        )
