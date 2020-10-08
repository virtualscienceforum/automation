import os
import github
import requests
import secrets
from researchseminarsdotorg import *
from requests import get, post, put
from io import StringIO
from ruamel.yaml import YAML
from common import *

def schedule_zoom_talk(talk) -> Tuple[string, string]:

    # Generate a password for the meeting. This is required since
    # otherwise the meeting room will be forced. Zoom limits the
    # password length to max 10 characters.
    zoom_password = secrets.token_urlsafe(10)

    # Form the talk registration body
    request_body =
    {
      "topic": "Speakers\' corner talk by %s"%(talk.get("name")),
      "type": 2, # Scheduled meeting
      "start_time": talk["time"],
      "timezone": "UTC",
      "duration": 60,
      "schedule_for": SPEAKERS_CORNER_USER_ID,
      "password": zoom_password,

      # Meeting settings
      "settings": {
        "host_video": True,
        "participant_video": False,
        "cn_meeting": False,  # Host the meeting in China?
        "in_meeting": False,  # Host the meeting in India?
        "join_before_host": False, # This will be switched to True shortly
                                   # before the meeting starts by the VSF bot.
                                   # It will also be switched back to False
                                   # after the meetings ends.
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
        "registrants_email_notification": True,
        "contact_email": "vsf@virtualscienceforum.org",
      },

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
        requests.post,
        f"{ZOOM_API}users/{user_id}/meetings",
        params={"body":request_body}
    )

    return response.id, zoom_password

def parse_talks(talks) -> int:
    num_updated = 0
    for talk in talks:
        # If we are not processing a speakers corner talk, or if the
        # zoom meeting id has already been set, there's nothing left to do
        if "zoom_meeting_id" in talk or talk["event_type"] != "speakers_corner":
            continue

        # Schedule the talk
        meeting_id, meeting_password = schedule_zoom_talk(talk)
        # Update the talk
        talk.get("zoom_meeting_id") = meeting_id
        # Add this talk to researchseminars.org
        publish_to_researchseminars(talk)

        # TODO: Do something with the password
        # do_something_with_password()

        num_updated += 1

    return num_updated

if __name__ == "__main__":
    # Get a handle on the repository
    gh = github.Github(os.getenv("VSF_BOT_TOKEN"))
    repo = gh.get_repo("virtualscienceforum/virtualscienceforum")

    # Read the talks file
    yaml = YAML()
    try:
        talks_data = repo.get_contents(TALKS_FILE, ref="master")
        talks = yaml.load(StringIO(talks_data.decoded_content.decode()))
    except github.UnknownObjectException:
        talks_data = None
        talks = []

    # If there are talks to be parsed...
    if len(talks) != 0:
        # ... parse them and keep track of how many we updated
        num_updated = parse_talks(talks)

        # If we added Zoom links, we should update the file in the repo
        if num_updated != 0:
            serialized = StringIO()
            yaml.dump(talks, serialized)

            repo.update_file(
              TALKS_FILE, f"Added Zoom link{1} for {0} scheduled speakers\'"\
                           "corner talk{1}".format(num_updated,'' if num_updated == 1 else 's'),
              serialized.getvalue(),
              sha=talks_data.sha,
              branch='master'
            )
