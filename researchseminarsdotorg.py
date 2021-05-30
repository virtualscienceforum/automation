import os
import re
from requests import get, post
from datetime import timedelta

SPEAKERS_CORNER_SEMINAR_SERIES = {"series_id": "speakerscorner",
           "name": "Speakers\' Corner",
           "is_conference": False,
           "topics": ["physics"], # https://researchseminars.org/api/0/topics
           "language": "en",
           "institutions": [""],
           "timezone": "UTC",
           "homepage": "https://virtualscienceforum.org/speakerscorner.md",
           "visibility": 1, # 0=private, 1=unlisted, 2=public
           "access_control": 0, # 0=open, see schema for more
           "frequency": 0,
           "organizers": [{"name": "Virtual Science Forum",
                           "email": "researchseminars@antonakhmerov.org",
                           "homepage": "https://virtualscienceforum.org",
                           "organizer": True,
                           "order": 0,
                           "display": True}]}


def find_seminar_series(series_id):
    url = f"https://researchseminars.org/api/0/search/series?series_id={series_id}"
    r = get(url)
    if r.status_code == 200:
        J = r.json()
        results = J["properties"]["results"]
        return (len(results) != 0)


def create_seminar_series(payload, authorization):
    url = "https://researchseminars.org/api/0/save/series/"
    r = post(url, json=payload, headers={"authorization":authorization})
    J = r.json()
    code = J.get("code")

    if r.status_code == 200:
        if code == "warning":
            return True, J["warnings"]
        else:
            return True, ""
    else:
        return False, ""


def edit_seminar_series(name, payload, authorization):
    url = "https://researchseminars.org/api/0/save/series/"
    r = post(url, json=payload, headers={"authorization":authorization})
    J = r.json()
    code = J.get("code")

    if r.status_code == 200:
        if code == "warning":
            return True, J["warnings"]
        else:
            return True, ""
    else:
        return False, ""

def add_talk_to_series(series_id, payload, authorization):
    url = "https://researchseminars.org/api/0/save/talk/"
    r = post(url, json=payload, headers={"authorization":authorization})
    J = r.json()
    code = J.get("code")
    if r.status_code == 200:
        if code == "warning":
            return J["series_ctr"], J["warnings"]
        else:
            return J["series_ctr"]
    else:
        return "", r.status_code

def publish_to_researchseminars(talk):
    # talk should be provided in yaml format
    api_token = os.getenv("RESEARCHSEMINARS_API_TOKEN")
    authorization = "researchseminars@antonakhmerov.org %s" % api_token

    # Set series ID
    series_id = "none"
    if talk["event_type"] == "speakers_corner":
        series_id = "speakerscorner"
    if talk["event_type"] == "lrc":
        series_id = "VSFLRC"

    # Check that we have a valid series_id
    if series_id == "none":
        print("Invalid series_id for publishing to researchseminars")
        return

    # Find the series, and create it if it doesn't exist
    if not find_seminar_series(series_id):
        create_seminar_series(SPEAKERS_CORNER_SEMINAR_SERIES, authorization)

    # TODO: If the series did not exist, it's creation has to be approved.
    #       That means the rest of this code will fail on the first attempt.

    # Set up payload for talk creation
    talk_payload = {
        "series_id": series_id,
        "language":"en",
        # Speaker info
        "speaker":talk.get('speaker_name'),
        "speaker_email":talk.get('email'),
        "speaker_affiliation":talk.get('speaker_affiliation', 'Unknown'),

        # Talk info
        "title":talk.get('title'),
        "abstract":talk.get('abstract'),
        "start_time":talk["time"].strftime('%Y-%m-%dT%H:%M:%S'),
        "end_time":(talk["time"] + timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:%S'),
        "timezone":"UTC", # Not required per se, copied from seminar series

        # Zoom info
        "online": True,
        "access_control":5, # Manual registration
        "access_registration":talk.get('registration_url'),

        # Extra info
        # ! Leave these out if unavailable
        #"slides_link":"http://Unavailable.org",
        #"video_link":"http://ToBeUpdated",
    }

    # If an arxiv identifier is available, add it. Not all talks have preprints
    if re.fullmatch(r"\d{4}\.\d{5}", talk.get("preprint", "")):
        talk_payload["paper_link"] = "https://arxiv.org/abs/"+talk.get('preprint')

    # Add extra authors if available
    if (authors := talk.get('authors', '')):
        talk_payload["abstract"] += "\n\n" + "Authors: " + authors

    # Make request to remote API
    series_ctr, warnings = add_talk_to_series(series_id, talk_payload, authorization)

    if series_ctr != "":
        print("Talk with id {0} successfully added".format(series_ctr))
        if warnings != "":
            print("Warnings: {0}".format(warnings))
        return True
    else:
        print("-- ERROR -- ")
        print("Could not add talk to series, status code {0}".format(warnings))
        return False
