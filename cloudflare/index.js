const Router = require('./router')

const MAILGUN_API_URL = "https://api.eu.mailgun.net/v3"
const USER = 'api';
const DOMAIN = 'mail.virtualscienceforum.org'
const SEND_MAIL_URL = MAILGUN_API_URL + '/' + DOMAIN + '/messages'

const mailGunAuthorization = Buffer.from(USER + ':' + MAILGUNAPIKEY).toString('base64');

const corsHeaders = {
  "Access-Control-Allow-Origin": "https://www.virtualscienceforum.org",
  "Access-Control-Allow-Methods": "GET, HEAD, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
}

const registrationForm = `
<!DOCTYPE html>
<head>
<script src='https://www.google.com/recaptcha/api.js'></script>
</head>
<html>
<style>
body {font-family: Arial, Helvetica, sans-serif;}
* {box-sizing: border-box}
/* Full-width input fields */
input[type=text] {
  width: 100%;
  padding: 15px;
  margin: 5px 0 22px 0;
  display: inline-block;
  border: none;
  background: #f1f1f1;
}
input[type=text]:focus {
  background-color: #ddd;
  outline: none;
}
hr {
  border: 1px solid #f1f1f1;
  margin-bottom: 25px;
}
/* Set a style for all buttons */
button {
  background-color: #4CAF50;
  color: white;
  padding: 14px 20px;
  margin: 8px 0;
  border: none;
  cursor: pointer;
  width: 100%;
  opacity: 0.9;
}
button:hover {
  opacity:1;
}
/* Float registration button and add an equal width */
.registerbtn {
  float: left;
  width: 50%;
}
/* Add padding to container elements */
.container {
  padding: 16px;
}
/* Clear floats */
.clearfix::after {
  content: "";
  clear: both;
  display: table;
}
/* Change styles for cancel button and signup button on extra small screens */
@media screen and (max-width: 300px) {
  .cancelbtn, .signupbtn {
     width: 100%;
  }
}
</style>
<body>
<form id="registrationForm" method="post" action="/zoom" style="border:1px solid #ccc">
  <div class="container">
    <h1>Sign Up</h1>
    <p>Please fill in this form to register for $TALK$.</p>
    <hr>
    <label for="firstname"><b>First Name</b></label>
    <input type="text" placeholder="Enter your first name" name="firstname" id="name" required>
    <label for="lastname"><b>Last Name</b></label>
    <input type="text" placeholder="Enter your last name" name="lastname" id="name" required>

    <label for="address"><b>Email</b></label>
    <input type="text" placeholder="Enter your Email" name="address" id="address" required>
    <label for="addressconfirm"><b>Confirm Email</b></label>
    <input type="text" placeholder="Confirm your Email" name="addressconfirm" id="address" required>

    <div id="checkboxes">
        <ul id="checkboxes" style='list-style:none'>
          <li> <input type="checkbox" name="instructions-checkbox" value="confirm-instructions" required> Please confirm you have read the <a href=http://virtualscienceforum.org/#/attendeeguide>participant instructions*</a> </li>
          <li> <input type="checkbox" name="contact-checkbox" value="confirm-contact" checked> Please check this box if we may contact you about future VSF events </li>
        </ul>
    </div>

    <div id="recaptcha" name="recaptcha" class="g-recaptcha" data-sitekey="6Lf37MoZAAAAAF19QdljioXkLIw23w94QWpy9c5E"></div>
    <div class="clearfix">
      <button type="submit" class="registerbtn">Register</button>
    </div>
  </div>
</form>
</body>
</html>
`

const registrationConfirmationEmail = `
  <!DOCTYPE html>
  <html>
  <body>
  <h1>Thank you for registering</h1>
  <p>Dear NAME,</p>
  <p>THANKYOUMSG</p>
  <p>Kind regards,</p>
  <p>VSF</p>
  </body>
  </html>
  `

const welcomeEmail = `
  <!DOCTYPE html>
  <html>
  <body>
  <h1>Welcome to the mailing list</h1>
  <p>Dear participant,</p>
  <p>Thank you for signing up</p>
  <p>Yours,</p>
  <p>VSF</p>
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

  // Taken from http://emailregex.com/
  const emailRegex = /^(([^<>()\[\]\\.,;:\s@"]+(\.[^<>()\[\]\\.,;:\s@"]+)*)|(".+"))@((\[[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}])|(([a-zA-Z\-0-9]+\.)+[a-zA-Z]{2,}))$/
  if (!bodydata.address || !emailRegex.test(bodydata.address)) return false
  if (!bodydata.addressconfirm || !emailRegex.test(bodydata.addressconfirm)) return false
  if (!(bodydata.address === bodydata.addressconfirm)) return false

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

      // Toggle subscribed
      bodydata['subscribed'] = true
      // Update user if present
      bodydata['upsert'] = true

      // Validate the submitted data
      if (!validateFormData(bodydata)) {
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
      let bodyoptions = {
        method: "POST",
        headers: {
          "Content-Type": "application/x-www-form-urlencoded",
          "Content-Length": bodydata.length,
          'Authorization': 'Basic ' + mailGunAuthorization,
        },
        body: urlfy(bodydata),
      }

      for( var i = 0; i < listsToSubscribeTo.length; i++ ) {
        var mailgunListName = "";
        switch( listsToSubscribeTo[i] ) {
          case "signup-general":
            mailgunListName = "vsf-announce"
            break;
          case "signup-speakerscorner":
            mailgunListName = "speakers_corner"
            break;
          default:
            return new Response(listsToSubscribeTo[i] + "cannot be subscribed to via this URL", {status:403, headers:corsHeaders})
        }

        var addMemberURL = MAILGUN_API_URL + '/lists/' + mailgunListName + '@' + DOMAIN + '/members'
        const response = await fetch(addMemberURL, bodyoptions)

        if( response.status != 200 ) {
          return new Response("Error while signing up for " + listsToSubscribeTo[i], {status:response.status, headers:corsHeaders})
        }
      }

      // If we get here, we managed to sign up for the lists
      const sendmailresponse = await sendConfirmationEmail(bodydata.address, bodydata.name, listsToSubscribeTo)
      if( sendmailresponse.status != 200 ) {
        return new Response("You were signed up, but sending a confirmation email failed.", {status:sendmailresponse.status, headers:corsHeaders})
      }
      return new Response("Succesfully subscribed. You will receive a confirmation email.", {status:200, headers:corsHeaders})
    }
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
    var registerURL = 'https://api.zoom.us/v2/meetings/' + meetingId + '/registrants'
    const response = await fetch(registerURL, requestbody)

    // If we get here, we managed to register
    const sendmailresponse = await sendRegistrationConfirmationEmail(bodydata.address, bodydata.name, "LRC")
    if( sendmailresponse.status != 200 ) {
      return new Response("You succesfully registered, but sending the confirmation email failed.", {status:sendmailresponse.status, headers:corsHeaders})
    }
    return new Response("Succesfully registered. You will receive a confirmation email.", {status:200, headers:corsHeaders})
  }
  catch (err)
  {
    console.error(err)
    return new Response(err.stack, { status: 500, headers:corsHeaders })
  }
}

async function sendRegistrationConfirmationEmail(address, name, talk) {

  // Update the template
  var thankYouMsg = "Thank you for registering for %s"%talk
  var mailBody = registrationConfirmationEmail.replace("NAME", name)
  var mailBody = mailBody.replace("THANKYOUMSG", thankYouMsg)

  let bodydata = {
    from: "mail@virtualscienceforum.org",
    to: address,
    subject: "Thank you for registering for the Virtual Sciende Forum LRC",
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
  if( response.status != 200 ) {
    return new Response("Error while sending the confirmation email", {status:response.status, headers:corsHeaders})
  }
  return new Response("results", {status:200, headers:corsHeaders})
}

function getListName(list)
{
  switch( list ) {
    case "signup-general":
      return "General announcement mailing list"
    case "signup-speakerscorner":
      return "Speaker\'s corner mailing list"
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

function respondWithRawHTML(html) {
  const init = {
    headers: {
      "content-type": "text/html;charset=UTF-8",
    },
  }
  return new Response(html, init)
}


addEventListener('fetch', event => {
    event.respondWith(handleRequest(event.request))
})

async function handleRequest(request) {
    // Replace with the appropriate paths and handlers
    const r = new Router()

    //r.get('.*/bar', () => new Response('responding for /bar'))
    r.get('/register', request => respondWithRawHTML(registrationForm))
    r.post('/mailinglist', request => handleMailingListSignupRequest(request) )
    r.post('/register', request => handleZoomRegistrationRequest(request))

    r.get('/', () => new Response('Hello VSF worker!')) // return a default message for the root route

    const resp = await r.route(request)
    return resp
}
