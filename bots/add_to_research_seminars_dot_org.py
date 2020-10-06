import os
from requests import get, post

SPEAKERS_CORNER_SEMINAR_SERIES = {"series_id": "speakerscorner",
           "name": "Speakers\' Corner",
           "is_conference": False,
           "topics": [""], # TODO: Get a list of topics
           "language": "en",
           "institutions": ["Global"],
           "timezone": "America/New_York",
           "homepage": "https://virtualscienceforum.org/speakerscorner.md",
           "visibility": 1, # 0=private, 1=unlisted, 2=public
           "access_control": 0, # 0=open, see schema for more
           "slots": [""],
           "organizers": [{"name": "Virtual Science Forum",
                           "email": "vsf@virtualscienceform.org",
                           "homepage": "https://virtualscienceforum.org",
                           "organizer": True,
                           "order": 0,
                           "display": True}]}

def find_seminar_series(series_id):
    url = "https://researchseminars.org/api/0/search/series?series_id=%s"%series_id
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

def add_talk(series_id, payload, authorization):
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

def add_talk_to_speakerscorner(talk):
    # talk should be provided in yaml format
    api_token = os.getenv("RESEARCHSEMINARS_API_TOKEN")
    authorization = "vsf@virtualscienceform.org %s" % api_token

    # Find speakers' corner series, and create it if it doesn't exist
    if( !find_seminar_series("speakerscorner") ):
        create_seminar_series(SPEAKERS_CORNER_SEMINAR_SERIES)

    # TODO: Figure out if we need to edit the series;
    #       Would be annoying since edits have to be approved

    # Set up payload for talk creation
    talk_payload = {"title":talk['title'],
                    "speaker":talk['author'], # TODO: will be 'speakerS'
                    "live_link":talk['zoom_link'],
                    "online":1,
                    "start_time":0, #TODO timestamptz format
                    "timezone":"America/New York"
                    }

    # Make request to remote API
    series_ctr, warnings = add_talk_to_series("speakerscorner", talk_payload, authorization)

    if series_ctr != "":
        print("Talk with id {0} successfully added".format(series_ctr))
        if warnings != "":
            print("Warnings: {0}".format(warnings))
        return True
    else:
        print("-- ERROR -- ")
        print("Could not add talk to series, status code {0}".format(warnings))
        return False
