import os
import github
import requests
from researchseminarsdotorg import *
from requests import get, post, put
from io import StringIO
from ruamel.yaml import YAML
from common import *

TALKS_FILE = "speakers_corner_talks.yml"

def schedule_zoom_talk(talk) -> string:

    # Form the talk registration body
    request_body =
    {
      "topic": "Speakers\' corner talk by %s"%(talk.get("name")),
      "type": 2, # Scheduled meeting
      "start_time": talk.get("time"), #2020-03-31T17:00:00
      "timezone": "UTC",
      "duration": 60, # 90 minutes
      "schedule_for": "vsf@virtualscienceforum.org",  # Zoom user ID or Zoom email address
      "agenda":talk.get("title"),
      "password": "",

      # Meeting settings
      "settings": {
        "host_video": True,
        "participant_video": True,
        "cn_meeting": False,  # Host the meeting in China?
        "in_meeting": False,  # Host the meeting in India?
        "join_before_host": False,
        "mute_upon_entry": True,
        "watermark": False,  # Add a watermark when screensharing?
        "use_pmi": False, # Don't use the Personal Meeting ID, but generate one
        "approval_type": 0, # Automatically approve
        "audio": "both",
        "auto_recording": "cloud",
        "enforce_login": False,
        "alternative_hosts": "",
        "registrants_email_notification": True,
        "contact_email": "vsf@virtualscienceforum.org",
      }
    }

    response = zoom_request(
        requests.post,
        f"{ZOOM_API}users/{user_id}/meetings",
        params={"body":request_body}
    )

    return response.id

def parse_talks(talks) -> int:
    num_updated = 0
    for talk in talks:
        if( talk.get('zoom_link', "") == "" && talk.get('event_type') == "speakers_corner" ):
            # Schedule the talk
            meeting_id = schedule_zoom_talk(talk)
            # Update the talk
            talk.get("zoom_meeting_id") = meeting_id
            num_updated += 1

            # Add this talk to researchseminars.org
            add_talk_to_speakerscorner(talk)

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