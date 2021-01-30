import os

from common import talks_data
from schedulezoomtalks import notify_author

if __name__ == "__main__":
    talks, _ = talks_data()
    issue_number = int(os.getenv("ISSUE_NUMBER"))
    notify_author(
        next(talk for talk in talks if talk["workflow_issue"] == issue_number)
    )