"""Utilities for manipulating and publishing videos"""
from typing import List
from subprocess import check_call
import os
from pathlib import Path
import json
import logging
import re
from io import StringIO

import requests
from ruamel.yaml import YAML
import jinja2
from dateutil.parser import parse
from  google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
import googleapiclient.discovery
import googleapiclient.errors
from googleapiclient.http import MediaFileUpload

import common


doi_regex = re.compile(r"10.\d{4,9}/[-._;()/:A-Z0-9]+")

def download_video(zoom_meeting_id):
    files = requests.get(
        f"https://api.zoom.us/v2/meetings/{zoom_meeting_id}/recordings",
        headers=common.zoom_headers()
    ).json()["recording_files"]
    try:
        video_recording, = (
            file for file in files
            if file.get("recording_type") == "shared_screen_with_speaker_view"
        )
    except ValueError as e:
        raise RuntimeError("Could not find a single recording file.") from e

    mp4_response = requests.get(
        video_recording["download_url"],
        params=[(
                "access_token",
                common.zoom_headers()["authorization"][len("Bearer "):]
        )],
        stream=True,
    )
    with open(Path(f'{zoom_meeting_id}.mp4'), "wb") as f:
        for chunk in mp4_response.iter_content(chunk_size=1024*1024):
            f.write(chunk)


convert_command = jinja2.Template("""ffmpeg -y -i {{input}} \
-vf "select='{% for i in intervals %}\
between(t,{{i[0].seconds}},{{i[1].seconds}})\
{{ "+" if not loop.last }}{% endfor %}', setpts=N/FRAME_RATE/TB" \
-af "aselect='{% for i in intervals %}\
between(t,{{i[0].seconds}},{{i[1].seconds}})\
{{ "+" if not loop.last }}{% endfor %}', asetpts=N/SR/TB" \
{{output}}
""")

def trim(input: str, intervals: List, output: str):
    """Trim a video.

    input : str
        input filename
    intervals : list((start, end))
        list of start and end timestamps of segments to include, with
        each timestamp a ``timedelta`` object
    output : str
        output filename
    """
    check_call(
        convert_command.render(
            input=input, intervals=intervals, output=output
        ),
        shell=True,
    )


### Youtube helper functions

def load_credentials():
    actual_credentials = None

    def credentials():
        nonlocal actual_credentials

        if actual_credentials is None:
            # Running for the first time.
            actual_credentials = Credentials.from_authorized_user_info(
                json.loads(os.environ["YOUTUBE_CREDENTIALS"])
            )

        if actual_credentials.expired:
            actual_credentials.refresh(Request())
            # Update the stored value
            gh = common.github.Github(os.getenv("VSF_BOT_TOKEN"))
            repo = gh.get_repo("virtualscienceforum/automation")
            repo.create_secret(
                "YOUTUBE_CREDENTIALS",
                actual_credentials.to_json()
            )

        return actual_credentials

    return credentials


credentials = load_credentials()


def ping_youtube():
    """A cheap check to see if we are authorized."""
    # TODO: once youtube implements checking quota, check remaining quota
    googleapiclient.discovery.build(
        "youtube", "v3", credentials=credentials()
    ).channels().list(
        part="snippet,contentDetails,statistics",
        mine=True
    ).execute()


def upload(file, title, description, playlist_id):
    youtube = googleapiclient.discovery.build(
        "youtube", "v3", credentials=credentials()
    )

    request = youtube.videos().insert(
        part="snippet,status",
        notifySubscribers=True,
        body={
            "snippet": {
                "title": title,
                "description": description,
                "categoryId": "28"
            },
            "status": {
                "privacyStatus": "public"
            },
        },

        media_body=MediaFileUpload(file)
    )
    logging.info(f"Uploading {file} to youtube.")
    result = request.execute()
    logging.info(f"Finished uploading.")
    video_id = result["id"]

    try:
        youtube.playlistItems().insert(
            part="snippet",
            body={
            "snippet": {
                "playlistId": playlist_id,
                "position": 0,
                "resourceId": {
                "kind": "youtube#video",
                "videoId": video_id,
                },
            },
            }
        ).execute()
        logging.info("Added video to the playlist")
    except Exception:
        logging.error("Failed to add the video to the playlist")

    return video_id


def sanitize_for_youtube(text):
    """Youtube bans < and >, so we replace these characters with larger versions."""
    return text.replace("<", "＜").replace(">", "＞")


def parse_duration(time_string):
    return parse(time_string) - parse("00:00")


def intervals_from_issue(issue):
    approval_regex = re.compile(
        r".*(?:i|speaker) approves? publishing(?: of)? the recording.*start(?: is)?\s+"
        r"(?P<start>\d\d:\d\d:\d\d).*end(?: is)?\s+(?P<end>\d\d:\d\d:\d\d).*",
        flags=(re.MULTILINE | re.DOTALL)
    )
    return next(
        [[parse_duration(match["start"]), parse_duration(match["end"])]]
        for comment in issue.get_comments().reversed
        if (
            match := approval_regex.match(comment.body.lower())
        ) and (
            issue.user == comment.user
            or issue.repository.has_in_collaborators(comment.user)
        )
    )


playlists = {
    "speakers_corner": "PLqJ4D_Db7W_qBCNdmJ2QaoenrXWCs82v0",
    "lrc": "PLqJ4D_Db7W_p5KNu8yDhoGyY36g75z3p2",
}


if __name__ == "__main__":
    ping_youtube()
    yaml = common.yaml
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    repo = common.vsf_repo()
    issue = repo.get_issue(int(os.environ["ISSUE_NUMBER"]))
    logger.info(f"Parsing issue {issue.number}")
    intervals = intervals_from_issue(issue)
    talks, _ = common.talks_data(repo=repo)
    talk = next(
        talk for talk in talks if talk["workflow_issue"] == issue.number
    )
    logger.info(f"Downloading the video.")
    meeting_id = talk["zoom_meeting_id"]
    download_video(talk["zoom_meeting_id"])

    logger.info(f"Trimming.")
    trim(f"{meeting_id}.mp4", intervals, f"{meeting_id}_trimmed.mp4")

    logger.info(f"Uploading the video.")
    title = f"“{talk['title']}” by {talk['speaker_name']}"[:100]
    abstract = (
        (
            ('https://arxiv.org/abs/' + talk['preprint'] + '\n\n')
            if not doi_regex.match(talk.get('preprint', ''))
            else ''
        )
        + f"Authors: {talk['authors']}\n\n{talk['abstract']}"
    )[:1000]

    talk["youtube_id"] = upload(
        f"{meeting_id}_trimmed.mp4",
        sanitize_for_youtube(title),
        sanitize_for_youtube(abstract),
        playlist_id=playlists[talk["event_type"]],
    )
    logger.info(f"Uploaded {talk['youtube_id']}")
    talk = {
        k: v for k, v in talk.items()
        if k not in 'zoom_meeting_id email registration_url'.split()
    }

    # Get the data again because someone might have pushed in the meantime.
    talks, sha = common.talks_data()
    talks = [
        t if t["workflow_issue"] != issue.number else talk
        for t in talks
    ]

    commit_message = f"add a youtube id to the talk from {issue.number}"
    serialized = StringIO()
    yaml.dump(talks, serialized)

    repo.update_file(
        common.TALKS_FILE,
        commit_message,
        serialized.getvalue(),
        sha=sha,
        branch="master",
    )
    issue.create_comment(f"I uploaded the video to https://youtu.be/{talk['youtube_id']} 🎉!")
    issue.edit(state="closed")
