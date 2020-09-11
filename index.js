const MAILGUN_API_URL = "https://api.eu.mailgun.net/v3"
const USER = 'api';
const LIST = 'temporary_test_list'
const DOMAIN = 'mail.virtualscienceforum.org'
const ADD_MEMBER_URL = MAILGUN_API_URL + '/lists/' + LIST + '@' + DOMAIN + '/members'
const GET_LISTS_URL = MAILGUN_API_URL + '/lists/pages'
const SEND_MAIL_URL = MAILGUN_API_URL + '/' + DOMAIN + '/messages'

const MAILGUN_API_KEY = "..."
const RECAPTCHASITEKEY = "..."
const RECAPTCHASECRET = "..."

const base64encodedData = Buffer.from(USER + ':' + MAILGUN_API_KEY).toString('base64');

// Method to convert a dictionary
const urlfy = obj =>
  Object.keys(obj)
    .map(k => encodeURIComponent(k) + "=" + encodeURIComponent(obj[k]))
    .join("&");

const testForm = `
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

/* Float signup button and add an equal width */
.signupbtn {
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

<form action="/" method="post", style="border:1px solid #ccc">
  <div class="container">
    <h1>Sign Up</h1>
    <p>Please fill in this form to sign up for the mailing list.</p>
    <hr>

    <label for="name"><b>Name</b></label>
    <input type="text" placeholder="Enter your name" name="name" id="name" required>

    <label for="address"><b>Email</b></label>
    <input type="text" placeholder="Enter your Email" name="address" id="address" required>

    <label>
      <input type="checkbox" checked="unchecked" name="consent" style="margin-bottom:15px"> I agree to the <a href="#" style="color:dodgerblue">terms</a>
    </label>

    <div class="clearfix">
      <button type="submit" class="signupbtn">Sign Up</button>
    </div>
  </div>
  <div class="g-recaptcha" data-sitekey="${RECAPTCHASITEKEY}"></div>
</form>

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

function respondWithRawHTML(html) {
  const init = {
    headers: {
      "content-type": "text/html;charset=UTF-8",
    },
  }
  return new Response(html, init)
}

async function gatherResponse(response) {
  const { headers } = response
  const contentType = headers.get("content-type") || ""

  if (contentType.includes("application/json")) {
    return JSON.stringify(await response.json())
  }
  else if (contentType.includes("application/text")) {
    return await response.text()
  }
  else if (contentType.includes("text/html")) {
    return await response.text()
  }
  else {
    return await response.text()
  }
}

// Validate the entries in the form
function validateFormData(body)
{
  if (!body) return false
  if (!body.name) return false

  // Taken from http://emailregex.com/
  const emailRegex = /^(([^<>()\[\]\\.,;:\s@"]+(\.[^<>()\[\]\\.,;:\s@"]+)*)|(".+"))@((\[[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}])|(([a-zA-Z\-0-9]+\.)+[a-zA-Z]{2,}))$/
  if (!body.address || !emailRegex.test(body.address)) return false

  return true
}

async function handleRequest(request) {

  try
  {
    //
    // \TODO !! Uncomment the origin checking for the live version !!
    //
    // Validate the origin of the request
    if( request.method === 'POST' ) // && request.url.hostname === '...' && request.url.pathname === '/add')
    {
      // Validate the submitted data
      if (!validateFormData(request.body)) {
        return new Response('Invalid submission', { status: 400 })
      }

      // Extract the recaptcha token
      const recaptchaToken = event.request.headers.get('g-recaptcha')
      if (!recaptchaToken) {
        return new Response('Invalid reCAPTCHA', { status: 400 })
      }

      const recaptchaResponse = await fetch(
        `https://www.google.com/recaptcha/api/siteverify?secret=${RECAPTCHASECRET}&response=${recaptchaToken}`, {
          method: 'POST'
        })

      const recaptchaBody = await recaptchaResponse.json()
      if (recaptchaBody.success == false) {
        return new Response('reCAPTCHA failed', { status: 400 })
      }

      // At this point, we passed the captcha and we have valid entries
      const formData = await request.formData()
      const bodydata = {}
      for (const entry of formData.entries()) {
        bodydata[entry[0]] = entry[1]
      }

      // Toggle subscribed
      bodydata['subscribed'] = true

      let bodyoptions = {
        method: "POST",
        headers: {
          "Content-Type": "application/x-www-form-urlencoded",
          "Content-Length": bodydata.length,
          'Authorization': 'Basic ' + base64encodedData,
        },
        body: urlfy(bodydata),
      }

      const response = await fetch(ADD_MEMBER_URL, bodyoptions)
      var jsonresponse = await response.json()

      if( response.status === 200 ) {
        console.log("Sending confirmation email")
        await sendConfirmationEmail(bodydata.address, bodydata.name)
      } else {
        console.log(jsonresponse.message)
      }

      let init = {
        headers: {
          "Content-Type": "text/html;charset=UTF-8",
        },
      }
      return new Response("results", init)
    }
  }
  catch (err)
  {
    console.error(err)
    return new Response(err.stack, { status: 500 })
  }
}

async function sendConfirmationEmail(address, name) {

  let bodydata = {
    from: "mail@virtualscienceforum.org",
    to: address,
    subject: "Welcome to the mailing list " + name,
    html: welcomeEmail,
  }

  let bodyoptions = {
    method: "POST",
    headers: {
      "Content-Type": "application/x-www-form-urlencoded",
      "Content-Length": bodydata.length,
      'Authorization': 'Basic ' + base64encodedData,
    },
    body: urlfy(bodydata),
  }

  const response = await fetch(SEND_MAIL_URL, bodyoptions)

  console.log(response)

  if( response.status === 200 ) {
    console.log("Confirmation email sent!")
  } else {
    console.log("Respond w/ returned error message")
  }

  let init = {
    headers: {
      "Content-Type": "text/html;charset=UTF-8",
    },
  }
  return new Response("results", init)
}

async function askForLists(request) {
  const bodydata = {
    method: "GET",
    headers: {
      "content-type": "application/json;charset=UTF-8",
      'Authorization': 'Basic ' + base64encodedData
    },
  }

  const response = await fetch(GET_LISTS_URL, bodydata)
  const results = await gatherResponse(response)

  let init = {
    headers: {
      "Content-Type": "text/html;charset=UTF-8",
    },
  }
  return new Response(results, init)
}

addEventListener("fetch", event => {
  // Extract the request from the event
  const { request } = event
  // Extract the url from the request
  const { url } = request

  if (url.includes("add")) {
      return event.respondWith(respondWithRawHTML(testForm))
  }

  if (url.includes("lists")) {
      return event.respondWith(askForLists(request))
  }

  if (request.method === "POST") {
    return event.respondWith(handleRequest(request))
  }
  else {
    return event.respondWith(new Response(`Expecting a POST request, or visit /add or /lists`))
  }
})
