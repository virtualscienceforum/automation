from functools import lru_cache
import os
from time import time
import json
from io import StringIO
import markdown

import jwt
import requests
import github
import datetime
from ruamel.yaml import YAML

yaml = YAML()

ZOOM_API = "https://api.zoom.us/v2/"
SPEAKERS_CORNER_USER_ID = "D0n5UNEHQiajWtgdWLlNSA"
VSF_USER_ID = "iJFotmmLRgOHJrTe9MKHRA"
TALKS_FILE = "talks.yml"

MAILGUN_BASE_URL = "https://api.eu.mailgun.net/v3/"
MAILGUN_DOMAIN = "mail.virtualscienceforum.org/"


class CollectExceptions:
    def __init__(self):
        self.exceptions = []

    def __enter__(self):
        pass

    def __exit__(self, exc_type, exc_value, traceback):
        if exc_type is None:
            return

        self.exceptions.append([exc_type, exc_value])
        return True

    def reraise(self):
        if not self.exceptions:
            return
        elif len(self.exceptions) == 1:
            raise RuntimeError() from self.exceptions[0][1]

        raise RuntimeError([
            exc_value
            for _, exc_value in self.exceptions
        ])


@lru_cache()
def zoom_headers(duration: int=100) -> dict:
    zoom_api_key = os.getenv("ZOOM_API_KEY")
    zoom_api_secret = os.getenv("ZOOM_API_SECRET")
    token = jwt.encode(
        # Create a payload of the token containing API Key & expiration time
        {"iss": zoom_api_key, "exp": time() + duration},
        zoom_api_secret,
        algorithm='HS256'
    ).decode('utf-8')

    return {'authorization': f'Bearer {token}', 'content-type': 'application/json'}


def vsf_repo():
    gh = github.Github(os.getenv("VSF_BOT_TOKEN"))
    return gh.get_repo("virtualscienceforum/virtualscienceforum")


def talks_data(ref="master", repo=None):
    if repo is None:
        repo = vsf_repo()

    # Read the talks file
    talks_data = repo.get_contents(TALKS_FILE, ref=ref)
    talks = yaml.load(StringIO(talks_data.decoded_content.decode()))
    for talk in talks:
        # Workaround against issues
        # https://sourceforge.net/p/ruamel-yaml/tickets/365/
        # https://sourceforge.net/p/ruamel-yaml/tickets/366
        # Note that we rely on the current behavior that returns UTC time
        talk["time"] = datetime.datetime.fromtimestamp(
            talk["time"]
            .replace(tzinfo=datetime.timezone.utc)
            .timestamp(),
            tz=datetime.timezone.utc
        )
    return talks, talks_data.sha


def zoom_request(method: callable, *args, **kwargs):
    """A minimal wrapper around requests for querying zoom API with error handling"""
    response = method(*args, **kwargs, headers=zoom_headers())
    if response.status_code > 299:
        raise RuntimeError(response.content.decode())

    if response.content:
        return response.json()


def speakers_corner_user_id() -> str:
    users = zoom_request(requests.get, ZOOM_API + "users")["users"]
    sc_user_id = next(
        u["id"] for u in users
        if u["first_name"] == "Speakers'" and u["last_name"] == "Corner"
        )
    return sc_user_id


def all_meetings(user_id) -> list:
    """Return all meetings by a user.

    Handles pagination, and adds ``live: True`` to a meeting that is running (if any).
    """
    meetings = []
    next_page_token = ""
    while True:
        meetings_page = zoom_request(
            requests.get,
            f"{ZOOM_API}users/{user_id}/meetings",
            params={"type": "scheduled", "page_size": 300, "next_page_token": next_page_token}
        )
        meetings += meetings_page["meetings"]
        next_page_token = meetings_page["next_page_token"]
        if not next_page_token:
            break

    live_meetings = zoom_request(
        requests.get,
        f"{ZOOM_API}users/{user_id}/meetings",
        params={"type": "live", "page_size": 300}
    )["meetings"]

    if live_meetings:
        for meeting in meetings:
            if meeting["id"] == live_meetings[0]["id"]:
                meeting["live"] = True

    return meetings


def decode(response):
    if response.status_code > 299:  # Not OK
        raise RuntimeError(response.content.decode())
    return json.loads(response.content.decode())


def api_query(method, endpoint, **params):
    return decode(method(
        MAILGUN_BASE_URL + endpoint,
        auth=("api", os.getenv("MAILGUN_API_KEY")),
        **params
    ))


def markdown_to_email(text: str) -> str:
    html = markdown.markdown(text)
    return (
        '<table cellspacing="0" cellpadding="0" border="0"><tr>'
        '<td style="word-break:normal;border-collapse:collapse!important;max-width:600px">'
        f'{html}</td></tr></table>'
    )


def markdown_to_plain(text: str) -> str:
    return text.replace('[', '').replace(']', ' ').replace('  \n', '\n').replace('*', '')


def meeting_registrants(zoom_meeting_id: int) -> dict:
    registrants = []
    next_page_token = ""
    while True:
        response = requests.get(
            f"https://api.zoom.us/v2/meetings/{zoom_meeting_id}/registrants",
            headers=zoom_headers(),
            params={"next_page_token": next_page_token}
        ).json()
        registrants += response["registrants"]
        next_page_token = response["next_page_token"]
        if not next_page_token:
            break

    registrants = [
        {**i, **{q["title"]: q["value"] for q in i.pop("custom_questions")}}
        for i in registrants
    ]

    return registrants


def send_to_participants(
    template: str,
    subject: str,
    talk: dict,
    from_email: str,
):
    """
    Send an email to meeting participants.

    template : jinja2.Template
        Email body, variables are keys of ``talk`` (see talks yaml).
    subject : str
        Email subject, format string expecting as variables keys of ``talk`` (see talks yaml).
    talk : dict
        Dictionary corresponding to an entry in the talks yaml file.
    other_parameters :
        Keyword arguments to be passed to format the templates.
    """
    message = template.render(**talk)
    registrants = meeting_registrants(talk['zoom_meeting_id'])

    # Defensively filter out invalid registrants
    # See https://github.com/virtualscienceforum/automation/issues/27
    registrants = [r for r in registrants if "email" in r and "join_url" in r]
    data = {
        "from": from_email,
        "to": list({
            f"{r.get('first_name', '')} {r.get('last_name', '')} <{r['email']}>"
            for r in registrants
        }),
        "subject": subject.format(**talk),
        "text": markdown_to_plain(message),
        "html": markdown_to_email(message),
        "recipient-variables": json.dumps(
            {r["email"]: {"join_url": r["join_url"]}
            for r in registrants}
        ),
    }

    return api_query(
        requests.post,
        MAILGUN_DOMAIN + "messages",
        data=data
    )
