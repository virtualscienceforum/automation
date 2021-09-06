const Router = require('./router')

const MAILGUN_API_URL = "https://api.eu.mailgun.net/v3"
const USER = 'api';
const DOMAIN = 'mail.virtualscienceforum.org'
const SEND_MAIL_URL = MAILGUN_API_URL + '/' + DOMAIN + '/messages'
const mailGunAuthorization = Buffer.from(USER + ':' + MAILGUNAPIKEY).toString('base64');

const corsHeaders = {
  "Access-Control-Allow-Origin": "*", //https://www.virtualscienceforum.org",
  "Access-Control-Allow-Methods": "GET, HEAD, POST, OPTIONS, PUT",
  "Access-Control-Allow-Headers": "Origin, X-Requested-With, Content-Type, Accept, Authorization",
}

const welcomeEmail = `
  <!DOCTYPE html>
  <html>
  <body>
  <h1>Welcome to the mailing list</h1>
  <p>Dear NAME,</p>
  <p>THANKYOUMSG</p>
  <p>Kind regards,</p>
  <p>The VSF Team</p>
  </body>
  </html>
  `

// Method to convert a dictionary
const urlfy = obj =>
  Object.keys(obj)
    .map(k => encodeURIComponent(k) + "=" + encodeURIComponent(obj[k]))
    .join("&");

// Validate the entries in the form
function validateRegistrationFormData(bodydata)
{
  if (!bodydata) return false
  if (!bodydata.firstname) return false
  if (!bodydata.lastname) return false

  return true
}

function validateMailingListFormData(bodydata)
{
  if (!bodydata) return false
  if (!bodydata.name) return false

  // Taken from http://emailregex.com/
  const emailRegex = /^(([^<>()\[\]\\.,;:\s@"]+(\.[^<>()\[\]\\.,;:\s@"]+)*)|(".+"))@((\[[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}])|(([a-zA-Z\-0-9]+\.)+[a-zA-Z]{2,}))$/
  if (!bodydata.address || !emailRegex.test(bodydata.address)) return false

  return true
}

async function subscribeToMailingList(listName, username, useremail) {

  try {
    const userdata = {}
    userdata['name'] = username
    userdata['address'] = useremail
    // Toggle subscribed
    userdata['subscribed'] = true
    // Update user if present
    userdata['upsert'] = true

    // Define the payload
    let bodyoptions = {
      method: "POST",
      headers: {
        "Content-Type": "application/x-www-form-urlencoded",
        "Content-Length": userdata.length,
        'Authorization': 'Basic ' + mailGunAuthorization,
      },
      body: urlfy(userdata),
    }

    // Send the request
    var addMemberURL = MAILGUN_API_URL + '/lists/' + listName + '@' + DOMAIN + '/members'
    const response = await fetch(addMemberURL, bodyoptions);
    return response
  }
  catch (err)
  {
    console.error(err)
    return new Response(err.stack, { status: 500, headers:corsHeaders })
  }
}

async function handleMailingListSignupRequest(request) {

  try
  {
      const formData = await request.formData()
      const bodydata = {}
      const listsToSubscribeTo = [] // Empty array to hold all the email lists to sign up to
      for (const entry of formData.entries()) {
        bodydata[entry[0]] = entry[1]

        // Add the requested email lists to the array
        if( entry[0] === "signup-checkbox" ) {
          listsToSubscribeTo.push(entry[1]);
        }
      }

      // Validate the submitted data
      if (!validateMailingListFormData(bodydata)) {
        return new Response('Invalid submission', { status: 400, headers:corsHeaders })
      }

      // Extract the recaptcha token
      const recaptchaToken = bodydata['g-recaptcha-response']
      if (!recaptchaToken) {
        return new Response('Invalid reCAPTCHA', { status: 400, headers:corsHeaders })
      }

      const recaptchaResponse = await fetch(
        `https://www.google.com/recaptcha/api/siteverify?secret=${RECAPTCHASECRET}&response=${recaptchaToken}`, {
          method: 'POST'
      })

      const recaptchaBody = await recaptchaResponse.json()
      if (recaptchaBody.success == false) {
        return new Response('reCAPTCHA failed', { status: 400, headers:corsHeaders })
      }

      for( var i = 0; i < listsToSubscribeTo.length; i++ ) {
        // Identify the correct mailing list endpoint
        var mailgunListName = "";
        switch( listsToSubscribeTo[i] ) {
          case "signup-general":
            mailgunListName = "vsf-announce"
            break;
          case "signup-speakerscorner":
            mailgunListName = "speakers_corner"
            break;
          default:
            return new Response("The list " + listsToSubscribeTo[i] + " cannot be subscribed to.", {status:400, headers:corsHeaders})
        }

        const response = await subscribeToMailingList(mailgunListName, bodydata['name'], bodydata['address'])

        if( response.status != 200 ) {
          return new Response("Error while signing up for " + listsToSubscribeTo[i], {status:response.status, headers:corsHeaders})
        }
      }

      // If we get here, we managed to sign up for the lists
      const sendmailresponse = await sendMailingListSignupConfirmationEmail(bodydata.address, bodydata.name, listsToSubscribeTo)
      if( sendmailresponse.status != 200 ) {
        return new Response("You were signed up, but sending a confirmation email failed.", {status:sendmailresponse.status, headers:corsHeaders})
      }

      return new Response("Succesfully subscribed. You will receive a confirmation email.", {status:200, headers:corsHeaders})
  }
  catch (err)
  {
    console.error(err)
    return new Response(err.stack, { status: 500, headers:corsHeaders })
  }
}

async function handleZoomRegistrationRequest(request) {
  try
  {
    const formData = await request.formData()
    const bodydata = {}
    for (const entry of formData.entries()) {
      bodydata[entry[0]] = entry[1]
    }

    // Validate the submitted data
    if (!validateRegistrationFormData(bodydata)) {
      return new Response('Invalid submission', { status: 400, headers:corsHeaders })
    }

    // Extract the recaptcha token
    const recaptchaToken = bodydata['g-recaptcha-response']
    if (!recaptchaToken) {
      return new Response('Invalid reCAPTCHA', { status: 400, headers:corsHeaders })
    }

    const recaptchaResponse = await fetch(
      `https://www.google.com/recaptcha/api/siteverify?secret=${RECAPTCHASECRET}&response=${recaptchaToken}`, {
        method: 'POST'
    })

    const recaptchaBody = await recaptchaResponse.json()
    if (recaptchaBody.success == false) {
      return new Response('reCAPTCHA failed', { status: 400, headers:corsHeaders })
    }

    // At this point, we passed the captcha and we have valid entries

    const payload = {}
    payload["first_name"] = bodydata["firstname"]
    payload["last_name"] = bodydata["lastname"]
    payload["email"] = bodydata["address"]
    payload["org"] = bodydata["affiliation"]
    payload["custom_questions"] = [{
      "title": "Please confirm you agree to follow the participant instructions: http://virtualscienceforum.org/#/attendeeguide",
      "value": "Yes",
      }]
    payload["auto_approve"] = 1

    var jwt = require('jsonwebtoken');
    var token = jwt.sign({ iss: ZOOMAPIKEY }, ZOOMAPISECRET, { algorithm: 'HS256', expiresIn: '1h' });

    let requestbody = {
      method: "POST",
      headers: {
        "Content-Type": "application/x-www-form-urlencoded",
        "Content-Length": payload.length,
        'Authorization': 'Bearer {' + token + '}'
      },
      body: urlfy(payload),
    }

    // Send to Zoom
    const meetingId = bodydata['meetingID']
    var registerURL = 'https://api.zoom.us/v2/meetings/' + meetingId + '/registrants'
    const response = await fetch(registerURL, requestbody)

    // If we get here, we managed to register

    // Add to mailing list!
    const username = bodydata["firstname"] + " " + bodydata["lastname"]
    const useremail = bodydata["address"]
    const eventtype = bodydate["eventType"]

    var mailgunListName = "";
    switch( eventtype ) {
      case "lrc":
        mailgunListName = "vsf-announce"
        break;
      case "speakers_corner":
        mailgunListName = "speakers_corner"
        break;
      default:
        return new Response("The list " + eventtype + " cannot be subscribed to.", {status:400, headers:corsHeaders})
    }
    const result = subscribeToMailingList(mailgunListName, username, useremail)

    return new Response("Succesfully registered. You will receive a confirmation email.", {status:200, headers:corsHeaders})
  }
  catch (err)
  {
    console.error(err)
    return new Response(err.stack, { status: 500, headers:corsHeaders })
  }
}

function getListName(list)
{
  switch( list ) {
    case "signup-general":
      return "General announcement mailing list"
    case "signup-speakerscorner":
      return "Speakers\' corner mailing list"
  }
}

async function sendMailingListSignupConfirmationEmail(address, name, lists) {
    // Update the template
    var thankYouMsg = "Thank you for signing up for ";
    for( var i = 0; i < lists.length; i++ ) {
      thankYouMsg += "the " + getListName(lists[i]);

      if( i == lists.length - 2 ) {
        thankYouMsg += " and "
      } else if ( i != 0 && i != lists.length - 1) {
        thankYouMsg += ", "
      }
    }
    thankYouMsg += ".";

    var mailBody = welcomeEmail.replace("NAME", name)
    var mailBody = mailBody.replace("THANKYOUMSG", thankYouMsg)

    let bodydata = {
      from: "VSF mailing lists <mail@virtualscienceforum.org>",
      to: address,
      subject: "You have signed up for a VSF mailing list",
      html: mailBody,
    }

    let bodyoptions = {
      method: "POST",
      headers: {
        "Content-Type": "application/x-www-form-urlencoded",
        "Content-Length": bodydata.length,
        'Authorization': 'Basic ' + mailGunAuthorization,
      },
      body: urlfy(bodydata),
    }

    const response = await fetch(SEND_MAIL_URL, bodyoptions)
    return response
}

function handleOptions(request) {
  // Make sure the necessary headers are present
  // for this to be a valid pre-flight request
  if(
    request.headers.get("Origin") !== null &&
    request.headers.get("Access-Control-Request-Method") !== null &&
    request.headers.get("Access-Control-Request-Headers") !== null
  ){
    // Handle CORS pre-flight request.
    // If you want to check the requested method + headers
    // you can do that here.
    return new Response(null, {
      headers: corsHeaders,
    })
  }
  else {
    // Handle standard OPTIONS request.
    // If you want to allow other HTTP Methods, you can do that here.
    return new Response(null, {
      headers: {
        Allow: "GET, HEAD, POST, OPTIONS",
      },
    })
  }
}

addEventListener('fetch', event => {
    if (event.request.method === "OPTIONS") {
        // Handle CORS preflight requests
        event.respondWith(handleOptions(request))
    } else {
      event.respondWith(handleRequest(event.request))
    }
})

async function handleRequest(request) {
    const r = new Router()

    r.post('/register', request => handleZoomRegistrationRequest(request))
    r.post('/mailinglist', request => handleMailingListSignupRequest(request) )

    // return a default message for the root route
    r.get('/', () => new Response('Hello from our VSF worker!'))

    const resp = await r.route(request)
    return resp
}
