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
    "vsf-announce": "updates from VSF",
    "speakers_corner": "Speakers' Corner news"
}

MAILING_LIST_FOOTER = """
---
You are receiving this email because you indicated that you are interested in {}.  
To unsubscribe, use [this link](%mailing_list_unsubscribe_url%)
""".format

MEETING_MESSAGE_FOOTER = """
---
You are receiving this email because you registered for a VSF Zoom meeting with ID {}.
""".format

def main():
    yaml = YAML()
    repo = common.vsf_repo()
    issue = repo.get_issue(int(os.getenv("ISSUE_NUMBER")))
    data = issue.body.replace('\r', '')
    header, body = data.split('---', maxsplit=1)
    header = yaml.load(header)
    if (to := header["to"]) in MAILING_LIST_DESCRIPTIONS:
        body += MAILING_LIST_FOOTER(MAILING_LIST_DESCRIPTIONS[to])
        response = common.api_query(
            requests.post,
            common.MAILGUN_DOMAIN + "messages",
            data={
                "from": header["from"],
                "to": to + "@mail.virtualscienceforum.org",
                "subject": header["subject"],
                "text": common.markdown_to_plain(body),
                "html": common.markdown_to_email(body),
            }
        )
    else:
        try:
            key, value = "zoom_meeting_id", int(to)
        except ValueError:
            if not to.startswith("#"):
                issue.create_comment("I couldn't parse to whom to send the email :(")
                return
            key, value = "workflow_issue", int(to[1:])
        # We are sending an email to zoom meeting participants
        talks, _ = common.talks_data(repo=repo)
        try:
            talk = next(talk for talk in talks if talk.get(key) == value)
        except StopIteration:
            if key == "workflow_issue":
                issue.create_comment("I couldn't parse to whom to send the email :(")
                return

            # Not a tracked talk, no extra data associated.
            talk = {"zoom_meeting_id": value}

        body += MEETING_MESSAGE_FOOTER(talk["zoom_meeting_id"])

        response = common.send_to_participants(
            template=jinja2.Template(body),
            from_email=header["from"],
            subject=header["subject"],
            talk=talk,
        )

    issue.create_comment("I sent the email 🎉!")
    issue.edit(state="closed")


if __name__ == "__main__":
    main()