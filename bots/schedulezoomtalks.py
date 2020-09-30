import os
import re
from copy import deepcopy
from pathlib import Path
from io import StringIO
import github
from ruamel.yaml import YAML

import base64
from subprocess import check_output

import jwt
import requests
from requests import get, post, put

yaml = YAML()
TALKS_FILE = "speakers_corner_talks.yml"

def zoom_headers():
    token = jwt.encode(
        # Create a payload of the token containing API Key & expiration time
        {"iss": os.getenv("ZOOM_API_KEY"), "exp": time() + 5000},
        os.getenv("ZOOM_API_SECRET"),
        algorithm='HS256'
    ).decode('utf-8')
    return {'authorization': f'Bearer {token}', 'content-type': 'application/json'}

def schedule_zoom_talk(talk, headers):
    time = talk.get("time")

    request_body =
    {
      "topic": "Speakers\' corner talk by %s"%(talk.get("name")),
      "type": 2, # Scheduled meeting
      "start_time": talk.get("time"), #2020-03-31T17:00:00
      "timezone": "UTC",
      "duration": 90, # 90 minutes
      "schedule_for": "string",  # Zoom user ID or Zoom email address
      "agenda":talk.get("title"),
      "password": "",
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
        "contact_email": "...",
      }
    }

    response = requests.post(
        f"https://api.zoom.us/v2/users/{0}/meetings",
        body=request_body,
        headers=headers,
    )

    # Extract JSON
    response = response.json()

    return response.id, ""

def parse_talks(gh):
    repo = gh.get_repo("virtualscienceforum/virtualscienceforum")
    headers = zoom_headers()

    try:
        talks_data = repo.get_contents(TALKS_FILE, ref="master")
        talks = yaml.load(StringIO(talks_data.decoded_content.decode()))
    except github.UnknownObjectException:
        talks_data = None
        talks = []

    num_updated = 0
    for talk in talks:
        if( talk.get('zoom_link', "") == "" && talk.get('event_type') == "speakers_corner" ):
            # Schedule the talk
            meeting_id, hostkey = schedule_zoom_talk(talk, headers)
            # Update the talk
            talk.get("zoom_meeting_id") = meeting_id

            # Do something with hostkey
            
            num_updated += 1

    serialized = StringIO()
    yaml.dump(talks, serialized)

    # If we added Zoom links, we should update the file in the repo
    if num_updated:
          repo.update_file(
              TALKS_FILE, f"Added Zoom link{1} for {0} scheduled speakers\'"\
                           "corner talk{1}".format(num_updated,'' if num_updated == 1 else 's'),
              serialized.getvalue(),
              sha=talks_data.sha,
              branch='master'
          )


if __name__ == "__main__":
    gh = github.Github(os.getenv("VSF_BOT_TOKEN"))
    #host_key = parse_talks(gh)

