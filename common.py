import os
from time import time
import json
from io import StringIO
import markdown

import requests
import github
import datetime
import logging
from time import sleep
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


def wait_until(minute):
    """Sleep until a specified minute of the hour starts."""
    now = datetime.datetime.now(tz=datetime.timezone.utc)
    desired = now.replace(minute=minute, second=0, microsecond=0)
    if desired < now:
        desired += datetime.timedelta(hours=1)
    logging.info(f"Sleeping until {desired}")
    sleep((desired - now).total_seconds())


def make_zoom_headers() -> callable:
    expiration = time()  # Always ask for a new token at the first call

    def zoom_headers() -> dict:
        zoom_account_id = os.getenv("ZOOM_ACCOUNT_ID")
        zoom_client_id = os.getenv("ZOOM_CLIENT_ID")
        zoom_client_secret = os.getenv("ZOOM_CLIENT_SECRET")

        nonlocal expiration
        if time() > expiration:
            # Get a new token
            response = requests.post(
                "https://zoom.us/oauth/token",
                data={
                    "grant_type": "account_credentials",
                    "account_id": zoom_account_id,
                },
                auth=(zoom_client_id, zoom_client_secret)
            )
            response.raise_for_status()
            token = response.json()["access_token"]
            expiration = time() + response.json()["expires_in"]

        return {'authorization': f'Bearer {token}', 'content-type': 'application/json'}

    return zoom_headers

zoom_headers = make_zoom_headers()


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
    response.raise_for_status()

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


def api_query(method, endpoint, **params):
    """A simple wrapper around mailgun API query"""
    response = method(
        MAILGUN_BASE_URL + endpoint,
        auth=("api", os.getenv("MAILGUN_API_KEY")),
        **params
    )
    try:
        result = response.json()
    except ValueError:
        result = response.text

    if response.status_code > 299:  # Not OK
        raise RuntimeError(result)

    return result


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
        )

        # Registration was not enabled for this meeting
        if response.status_code == 400:
            return []

        response = response.json()
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
