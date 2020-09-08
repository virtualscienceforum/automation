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


def authorize_at_zoom(client_id, client_secret):
    port = 8878
    redirect_url = f"http://lvh.me:{port}/redirect"
    webbrowser.open(
        f"https://zoom.us/oauth/authorize?response_type=code&client_id={client_id}&redirect_uri={redirect_url}"
    )
    server = HTTPServer(('', port), ClassAttributeStorageHandler)
    server.handle_request()
    server.socket.close()
    auth_code = ClassAttributeStorageHandler.request_path[len('/redirect?code='):]

    response = requests.post(
        f"https://zoom.us/oauth/token?grant_type=authorization_code&code={auth_code}&redirect_uri={redirect_url}",
        headers={
            "Authorization": f"Basic {base64.b64encode(':'.join([client_id, client_secret]).encode()).decode()}"
        },
    )

    oauth_token = response.json()['access_token']
    return {"Authorization": f"Bearer {oauth_token}"}


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
        data['o:deliverytime'] = utils.format_datetime(when)
    return api_query(
        post,
        f"{domain}messages",
        data=data
    )


def lrc_calendar_event(**event_data):

    duration = timedelta(hours=1, minutes=30)
    start = event_data['date'] + timedelta(hours=19, minutes=30)

    cal = icalendar.Calendar()
    cal.add('prodid', '-//VSF announcements//virtualscienceforum.org//')
    cal.add('version', '2.0')


    event = icalendar.Event()
    event.add('summary', f"Long Range Colloquium by {event_data['speaker_name']}")
    event.add('description', f"Title: {event_data['title']}\n\nAbstract:{event_data['abstract']}")
    event.add('dtstart', start)
    event.add('dtend', start + duration)
    event.add('dtstamp', datetime.now(tz=pytz.timezone('Europe/Amsterdam')))
    event['uid'] = event['dtstart'].to_ical().decode() + '@virtualscienceforum.org'

    organizer = vCalAddress('MAILTO:vsf@virtualscienceforum.org')
    organizer.params['cn'] = vText('Virtual Science Forum')
    event['organizer'] = organizer

    cal.add_component(event)
    
    return cal.to_ical()

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

# +
headers = zoom_headers()

r = requests.get('https://api.zoom.us/v2/users/', headers=headers)
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

Thank you for registering for today's Long Range Colloquium! The talk will begin in four hours (19:30 CEST / 1:30 PM ET).
We will, however, have an informal chat about research with {speaker_name} starting a bit earlier—15 minutes before the talk. You are very welcome to join!

Your can join using your [registration link](%recipient.join_url%).

Today's speaker is {speaker_name} ({speaker_affiliation}). See the title and the abstract of the talk below.

**Title:** {title}

**Abstract:** {abstract}

See you soon,  
The Virtual Science Forum team"""

send_to_registrants(
    reminder_template.format(**event_data), 'Long Range Colloquium starting soon', long_range_registrants,
    when=datetime(2020, 8, 19, 15, 0, tzinfo=pytz.UTC)
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
    speaker_name="Mohammad Hafezi",
    speaker_affiliation="University of Maryland and JQI",
    date=datetime(2020, 8, 19, tzinfo=pytz.timezone('Europe/Amsterdam')),
    speaker_pronoun="he",
    title="Quantum optics meets correlated electrons",
    abstract="""One of the key challenges in the development of quantum technologies is the control of light-matter interaction at the quantum level where individual excitations matter. During the past couple of decades, there has been tremendous progress in controlling individual photons and other excitations such as spin, excitonic, phononic in solid-state systems. Such efforts have been motivated to develop quantum technologies such as quantum memories, quantum transducers, quantum networks, and quantum sensing. While these efforts have been mainly focused on control and manipulation of individual excitations (i.e., single-particle physics), both desired and undesired many-body effects have become important. Therefore, it is intriguing to explore whether these quantum optical control techniques could pave a radically new avenue to prepare, manipulate, and detect non-local and correlated electronic states, such as topological ones.

We present several examples of such ideas: (1) Optically driven fractional quantum Hall states: While in Floquet band engineering, the focus is on the control of the single-particle Hamiltonian, here the optical drive can effectively engineer the interaction terms, which could lead to the preparation of model Hamiltonians and exotic topological states. (2) Enhancing superconductivity with an optical drive: we propose a new approach for the enhancement of superconductivity by the targeted destruction of the competing charge/bond density waves (BDW) order. By investigating the optical coupling of gapless, collective fluctuations of the BDWs, we argue that the resonant excitation of these modes can melt the underlying BDW order parameter. We propose an experimental setup to implement such an optical coupling using 2D plasmon-polariton hybrid systems. (3) We also discuss how the coupling of an empty cavity can enhance the superconducting transition temperature, in a quantum analogy to the Eliasberg effect. In the end, we discuss how by driving a semi-conductor and creating a population inversion, one could achieve s-wave and p-wave superconducting pairing.

References:

* Fractional Quantum Hall States:
  * Physical Review Letters, 119, 247403 (2017)
  * Physical Review B, 98, 155124 (2018)
  * arXiv:2005.13569 (2020)
* Superconductivity:
  * Phys. Rev. Lett., 122 , 167002 (2019)
  * Phys. Rev. B, 101, 224506 (2020)"""
)

announcement_template = """Dear %recipient_name%,

We would like to invite you to the upcoming VSF Long Range Colloquium that is going to take place {date:%A %B %-d} at 1:30 PM ET (19:30 CEST).

The speaker is {speaker_name} ({speaker_affiliation}), and the talk title is "{title}".

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
