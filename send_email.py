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

MAILING_LIST_DESCRIPTIONS = {
    "vsf_announce": "updates from VSF",
    "speakers_corner": "Speakers' Corner news"
}

MAILING_LIST_FOOTER = """---
You are receiving this email because you indicated that you are interested in {list_description}.  
To unsubscribe, use [this link](%mailing_list_unsubscribe_url%)
""".format

MEETING_MESSAGE_FOOTER = """---
You are receiving this email because you registered for a VSF Zoom meeting with ID {meeting_id}.
""".format

if __name__ == "__main__":
    yaml = YAML()
    repo = common.vsf_repo()
    issue = repo.get_issue(int(os.getenv("ISSUE_NUMBER")))
    data = issue.body.replace('\r', '')
    header, body = data.split('---', maxsplit=1)
    header = yaml.load(header)
    if header["to"] in ("vsf_announce", "speakers_corner"):
        to = header["to"] + "@mail.virtualscienceforum.org"
        body += MAILING_LIST_FOOTER(MAILING_LIST_DESCRIPTIONS[header["to"]])
        response = common.api_query(
            requests.post,
            common.MAILGUN_BASE_URL + "messages",
            data={
                "from": header["from"],
                "to": to,
                "subject": header["subject"],
                "text": common.markdown_to_plain(body),
                "html": common.markdown_to_email(body),
            }
        )
    else:
        meeting_id = int(header["to"])
        # We are sending an email to zoom meeting participants
        talks = common.talks_data(repo=repo)
        try:
            talk = next(talk for talk in talks if talk["zoom_meeting_id"] == meeting_id)
        except StopIteration:
            # Not a speakers corner talk, no extra data associated.
            talk = {"zoom_meeting_id": meeting_id}

        body += MEETING_MESSAGE_FOOTER(meeting_id)

        response = common.send_to_participants(
            template=jinja2.Template(body),
            from_email=header["from"],
            subject=header["subject"],
            talk=talk,
        )

    if response.status_code > 299:
        raise RuntimeError(response)

    issue.create_comment("I sent the email 🎉!")
    issue.edit(state="closed")