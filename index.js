const MAILGUN_API_URL = "https://api.eu.mailgun.net/v3"
const USER = 'api';
const LIST = 'temporary_test_list'
const DOMAIN = 'mail.virtualscienceforum.org'
const ADD_MEMBER_URL = MAILGUN_API_URL + '/lists/' + LIST + '@' + DOMAIN + '/members'
const GET_LISTS_URL = MAILGUN_API_URL + '/lists/pages'
const SEND_MAIL_URL = MAILGUN_API_URL + '/' + DOMAIN + '/messages'

const base64encodedData = Buffer.from(USER + ':' + MAILGUNAPIKEY).toString('base64');

const corsHeaders = {
  "Access-Control-Allow-Origin": "https://virtualscienceforum.org",
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
  <p>Dear NAME,</p>
  <p>THANKYOUMSG</p>
  <p>Kind regards,</p>
  <p>VSF</p>
  </body>
  </html>
  `

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
          'Authorization': 'Basic ' + base64encodedData,
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
        
        // If we get here, we managed to sign up for the lists
        const sendmailresponse = await sendConfirmationEmail(bodydata.address, bodydata.name, listsToSubscribeTo)
        return new Response(null, {status:204, headers:corsHeaders})
      }
    }
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
      return "Speaker\'s corner mailing list"
  }
}

async function sendConfirmationEmail(address, name, lists) {

  // Update the template
  var thankYouMsg = "Thank you for signing up for ";
  for( var i = 0; i < lists.length; i++ ) {
    thankYouMsg += "the " + getListName(lists[i]);

    if( i == lists.length - 2 ) {
      thankYouMsg += " and "
    } else if ( i != 0 ) {
      thankYouMsg += ", "
    }
  }

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
      'Authorization': 'Basic ' + base64encodedData,
    },
    body: urlfy(bodydata),
  }

  const response = await fetch(SEND_MAIL_URL, bodyoptions)
  return response
}

addEventListener("fetch", event => {
  // Extract the request from the event
  const { request } = event
  // Extract the url from the request
  const { url } = request

  if (request.method === "POST") {
    return event.respondWith(handleRequest(request))
  }
  else {
    return event.respondWith(new Response(`Expecting a POST request`))
  }
})
