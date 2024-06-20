# -*- coding: utf-8 -*-
# ---
# jupyter:
#   jupytext:
#     text_representation:
#       extension: .py
#       format_name: light
#       format_version: '1.5'
#       jupytext_version: 1.6.0
#   kernelspec:
#     display_name: Python 3
#     language: python
#     name: python3
# ---

# +
import base64
from pathlib import Path
import json
from subprocess import check_output
from email import utils
from datetime import datetime, timedelta
from time import time

import jwt
import requests
from requests import get, post, put
import pandas
import markdown

import icalendar
from icalendar import vCalAddress, vText
import pytz
from pathlib import Path


mailgun_base_url = "https://api.eu.mailgun.net/v3/"
domain = "mail.virtualscienceforum.org/"


def decode(response):
    if response.status_code != 200:
        raise RuntimeError(response.content.decode())
    return json.loads(response.content.decode())


def api_query(method, endpoint, **params):
    return decode(method(
        mailgun_base_url + endpoint,
        auth=("api", mailgun_api_key),
        **params
    ))


def markdown_to_email(text):
    html = markdown.markdown(text)
    return (
        '<table cellspacing="0" cellpadding="0" border="0"><tr>'
        '<td style="word-break:normal;border-collapse:collapse!important;max-width:600px">'
        f'{html}</td></tr></table>'
    )


def markdown_to_plain(text):
    return text.replace('[', '').replace(']', ' ').replace('  \n', '\n').replace('*', '')


def registrants(meeting_id, headers):
    # TODO: properly support paging
    registrants = requests.get(
        f"https://api.zoom.us/v2/meetings/{meeting_id}/registrants?page_size=500",
        headers=headers
    ).json()
    
    registrants2 = [
        {**i, **{q["title"]: q["value"] for q in i.pop("custom_questions")}}
        for i in registrants['registrants']
    ]

    data = pandas.DataFrame(registrants2)

    # Drop empty columns
    return data.loc[:, data.any(axis=0)]

def send_to_registrants(
    message,
    subject,
    registrants,
    from_email="Long Range Colloquium <no-reply@mail.virtualscienceforum.org>",
    when=None
):
    data = {
        "from": from_email,
        "to": list({f"{i.first_name} {i.last_name} <{i.email}>" for i in registrants.itertuples()}),
        "subject": subject,
        "text": markdown_to_plain(message),
        "html": markdown_to_email(message),
        "recipient-variables": json.dumps({i.email: {'join_url': i.join_url} for i in registrants.itertuples()}),
    }
    if when is not None:
        if when < datetime.now(tz=pytz.timezone('Europe/Amsterdam')):
            raise ValueError('Cannot schedule in the past')
        data['o:deliverytime'] = utils.format_datetime(when)
    return api_query(
        post,
        f"{domain}messages",
        data=data
    )


def calendar_event(title, start, duration, uid, description=None):

    duration = duration
    start = start

    cal = icalendar.Calendar()
    cal.add('prodid', '-//VSF announcements//virtualscienceforum.org//')
    cal.add('version', '2.0')


    event = icalendar.Event()
    event.add('summary', title)
    if description is not None:
        event.add('description', description)
    event.add('dtstart', start)
    event.add('dtend', start + duration)
    event.add('dtstamp', datetime.now(tz=pytz.UTC))
    event['uid'] = uid + '@virtualscienceforum.org'

    organizer = vCalAddress('MAILTO:vsf@virtualscienceforum.org')
    organizer.params['cn'] = vText('Virtual Science Forum')
    event['organizer'] = organizer

    cal.add_component(event)
    
    return cal.to_ical()


def lrc_calendar_event(**event_data):
    duration = timedelta(hours=1, minutes=30)
    return calendar_event(
        title=f"Long Range Colloquium by {event_data['speaker_name']}",
        start=event_data['date'],
        duration=duration,
        uid=event['dtstart'].to_ical().decode(),
        description=f"Title: {event_data['title']}\n\nAbstract:{event_data['abstract']}"
    )

## This mailing list is read-only (can only be used from API), and therefore not a secret

announce_list = 'vsf-announce@mail.virtualscienceforum.org'
# +
# Secrets

def zoom_headers():
    zoom_api_secret, zoom_api_key = check_output(["pass", "vsf_zoom/api"]).decode().strip().split('\n')
    token = jwt.encode(
        # Create a payload of the token containing API Key & expiration time
        {"iss": zoom_api_key, "exp": time() + 5000},
        zoom_api_secret,
        algorithm='HS256'
    ).decode('utf-8')

    return {'authorization': f'Bearer {token}', 'content-type': 'application/json'}


mailgun_api_key = check_output(["pass", "mailgun_api_key"]).decode().strip()
headers = zoom_headers()
# -

meetings = requests.get(f"https://api.zoom.us/v2/users/me/meetings", headers=headers).json()

long_range_meeting = sorted(
    [
        meeting for meeting in meetings['meetings']
        if ("Long Range" in meeting['topic']
            and pandas.to_datetime(meeting['start_time']) > datetime.now(tz=pytz.UTC)
           )
    ],
    key=(lambda meeting: pandas.to_datetime(meeting['start_time'])),
)[0]

long_range_id = long_range_meeting['id']

long_range_date = pandas.to_datetime(long_range_meeting['start_time'])
print(long_range_date)

# ## Add subscribers to list
#
# Mailgun doesn't re-add unsubscribed participants, so we don't need to be too thorough here.

# +
past_lrc = [
        meeting for meeting in meetings['meetings']
        if ("Long Range" in meeting['topic']
            and pandas.to_datetime(meeting['start_time']) < datetime.now(tz=pytz.UTC)
           )
]

for lrc in past_lrc:
    lrc_registrants = registrants(lrc['id'], headers=headers)
    api_query(
        post, f'lists/{announce_list}/members.json',
        data=dict(members=json.dumps([
            dict(address=i.email, name=f"{i.first_name} {i.last_name}")
            for i in lrc_registrants[
                lrc_registrants["May we contact you about future Virtual Science Forum events?"] == "Yes"
            ].itertuples()
        ]))
    )
# -

api_query(get, f'lists/{announce_list}/members')['total_count']

meeting_details = requests.get(f"https://api.zoom.us/v2/meetings/{long_range_meeting['id']}", headers=headers).json()

# +
long_range_registrants = registrants(long_range_id, headers)

len(long_range_registrants)
# -

lrcs = [meeting for meeting in meetings['meetings'] if 'colloquium' in meeting['topic'].lower()]

all_registrations = {
    (colloquium['start_time'], colloquium['created_at']):
        registrants(colloquium['id'], headers)['create_time']
    for colloquium in lrcs[1:]
}

# +
all_registration_timings = []
for (start, creation), registrations in all_registrations.items():
    column = pandas.to_datetime(registrations) - pandas.to_datetime(start)
    column.name = start[:10]
    all_registration_timings.append(
        column
    )

all_registration_timings = pandas.DataFrame(all_registration_timings).T
# -

import seaborn
seaborn.catplot(data=all_registration_timings.astype('timedelta64[m]') / 60 / 24)

# ## Mailgun stuff

reminder_template = """Dear %recipient_name%,

Thank you for registering for today's Long Range Colloquium by {speaker_name}! The talk will begin in four hours (19:30 CEST / 1:30 PM ET).
We will, however, have an informal chat about research with {speaker_name} starting a bit earlier—15 minutes before the talk. You are very welcome to join!

Your can join using your [registration link](%recipient.join_url%).

Today's speaker is {speaker_name} ({speaker_affiliation}). See the title and the abstract of the talk below.

**Title:** {title}

**Abstract:** {abstract}

See you soon,  
The Virtual Science Forum team"""

send_to_registrants(
    reminder_template.format(**event_data), 'Long Range Colloquium starting soon', long_range_registrants,
    when=(event_data['date'] - timedelta(hours=4))
)

# ## Extra post-colloquium invitation

extra_invitation_template = """Dear %recipient_name%,

We are looking forward to seeing you at the Long Range Colloquium by {speaker_name}!
In your registration you indicated that you would like to join a post-colloquium informal discussion with the speaker.

This discussion will take place after the in a [separate zoom meeting]({room_url}),
join it after the talk concludes.

See you soon,  
The Virtual Science Forum team
"""

send_to_registrants(extra_invitation_template.format(**event_data, room_url=XXX), f"Post-colloquium discussion with {event_data['speaker_name']}", post_colloquium.sort_values(by='create_time').iloc[-3:])

# ## Announce

event_data = dict(
    speaker_name="Pedram Roushan",
    speaker_affiliation="Google AI Quantum",
    date=long_range_date.to_pydatetime().astimezone(pytz.timezone('Europe/Amsterdam')),
    speaker_pronoun="he",
    title="Tuning quantum information scrambling in two-dimensional systems",
    abstract="""The promise of quantum computers is that certain computational tasks might be executed exponentially faster on a quantum processor than on a classical processor. In 2019, we reported the use of a processor with programmable superconducting qubits to create quantum states on 53 qubits, corresponding to a computational state space of dimension 253 (about 1016). Measurements from repeated experiments sample the resulting probability distribution, which we verify using classical simulations. Our Sycamore processor takes about 200 seconds to sample one instance of a quantum circuit a million times—our benchmarks indicate that the equivalent task for a classical supercomputer would take approximately 10,000 years. Established quantum supremacy, we now take a closer look at how quantum information scrambling takes place and computational complexity grows. We demonstrate that the complexity of quantum circuits is directly revealed through measurements of out-of-time-order correlators (OTOCs), which capture the spatial-temporal spread of local perturbations. We implement a variety of quantum circuits ranging from simple integrable circuits such as XY model in 1D to fully ergotic circuits such as 2D random circuits. Our protocol effectively separates scrambling from gate-error induced noise, allowing us to distinguish the complexity of these circuits. We image the dispersion of the scrambling wavefront as it changes from diffusive to ballistic propagation, resulting from changing the entangling gates. By tuning away from the Clifford gate set, we break integrability and dial-in ergodicity and distinguish these complexity classes from their fluctuation signatures. Our work establishes OTOC as a tool to visualize scrambling and diagnose complexity in time and size scales that are challenging to access classically."""
)

announcement_template = """Dear %recipient_name%,

We would like to invite you to the upcoming VSF Long Range Colloquium that is going to take place {date:%A %B %-d} at 1:30 PM ET (19:30 CEST).

We are happy to have {speaker_name} ({speaker_affiliation}) as the next speaker, who is goint to talk about "{title}".

To see the talk abstract and register, please go to [the colloquium page](https://virtualscienceforum.org/#/long_range_colloquium) or register directly at this [URL]({registration_url}).

Best regards,
The Virtual Science Forum team

---
You are receiving this email because you indicated that you are interested in updates from the Virtual Science Forum.  
To unsubscribe visit [this URL](%mailing_list_unsubscribe_url%).
"""

# +
if event_data['date'] < datetime.now(tz=pytz.timezone('Europe/Amsterdam')):
    raise ValueError('Cannot announce past event.')

api_query(
    post, f'{domain}messages',
    data={
        "from": "Long Range Colloquium <no-reply@mail.virtualscienceforum.org>",
        "to": announce_list,
        "subject": f"Long Range Colloquium by {event_data['speaker_name']}",
        "text": markdown_to_plain(announcement_template.format(**event_data, registration_url=meeting_details['registration_url'])),
        "html": markdown_to_email(announcement_template.format(**event_data, registration_url=meeting_details['registration_url'])),
    },
    files=[
        ("attachment", ("long_range_colloquium.ics", lrc_calendar_event(**event_data)))
    ],
)
# -
# ## Zoom recordings

recording_urls = requests.get(f"https://api.zoom.us/v2/meetings/{past_lrc[0]['id']}/recordings", headers=headers).json()

mp4_url = next(file["download_url"] for file in recording_urls['recording_files'] if file["file_type"].lower() == "mp4")

mp4_response = requests.get(
    mp4_url, params=[("access_token", headers["authorization"][len("Bearer "):])],
    stream=True
)
with open(Path('colloquium.mp4'), "wb") as f:
    for chunk in mp4_response.iter_content(chunk_size=1024*1024):
        f.write(chunk)

import ffmpeg

# +
timestamp_re = re.compile(r"(?:(?P<hours>\d{1,2}):)?(?P<minutes>\d{1,2}):(?P<seconds>\d{2})(?:\.(?P<milliseconds>\d+))?")

def time_from_timestamp(timestamp: str) -> timedelta:
    if (match := re.fullmatch(timestamp_re, timestamp)) is None:
        raise ValueError("Incorrect format")
    return timedelta(**{k: int(v) for k, v in match.groupdict(default=0).items()})


# -

in_file = ffmpeg.input('colloquium.mp4')

# !rm out.mp4

ffmpeg.concat(in_file.trim(start=5, end=40)).output("out.mp4").run()

ffmpeg.co

a.run()

from dateutil.parser import parse

import re

# +
# timedelta?
# -

from datetime import time


