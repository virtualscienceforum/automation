const MAILGUN_API_URL = "https://api.eu.mailgun.net/v3"
const USER = 'api';
const LIST = 'temporary_test_list'
const DOMAIN = 'mail.virtualscienceforum.org'
const ADD_MEMBER_URL = MAILGUN_API_URL + '/lists/' + LIST + '@' + DOMAIN + '/members'
const GET_LISTS_URL = MAILGUN_API_URL + '/lists/pages'
const SEND_MAIL_URL = MAILGUN_API_URL + '/' + DOMAIN + '/messages'

const base64encodedData = Buffer.from(USER + ':' + MAILGUNAPIKEY).toString('base64');

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, HEAD, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
}

// Method to convert a dictionary
const urlfy = obj =>
  Object.keys(obj)
    .map(k => encodeURIComponent(k) + "=" + encodeURIComponent(obj[k]))
    .join("&");

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
function validateFormData(bodydata)
{
  if (!bodydata) return false
  if (!bodydata.name) return false

  // Taken from http://emailregex.com/
  const emailRegex = /^(([^<>()\[\]\\.,;:\s@"]+(\.[^<>()\[\]\\.,;:\s@"]+)*)|(".+"))@((\[[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}])|(([a-zA-Z\-0-9]+\.)+[a-zA-Z]{2,}))$/
  if (!bodydata.address || !emailRegex.test(bodydata.address)) return false

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
      const formData = await request.formData()
      const bodydata = {}
      for (const entry of formData.entries()) {
        bodydata[entry[0]] = entry[1]
      }

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
        status: 204,
        headers: {
          "Content-Type": "text/html;charset=UTF-8",
          "Access-Control-Allow-Origin": "*",
          "Access-Control-Allow-Methods": "GET, HEAD, POST, OPTIONS",
          "Access-Control-Allow-Headers": "Content-Type",
        },
      }
      return new Response("results", init)
    }
  }
  catch (err)
  {
    console.error(err)
    return new Response(err.stack, { status: 500, headers:corsHeaders })
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

addEventListener("fetch", event => {
  // Extract the request from the event
  const { request } = event
  // Extract the url from the request
  const { url } = request

  if (request.method === "OPTIONS") {
      // Handle CORS preflight requests
      event.respondWith(handleOptions(request))
  }
  else if (request.method === "POST") {
    return event.respondWith(handleRequest(request))
  }
  else {
    return event.respondWith(new Response(`Expecting a POST request`))
  }
})
