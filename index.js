const MAILGUN_API_URL = "https://api.eu.mailgun.net/v3"
const USER = 'api';
const LIST = 'temporary_test_list'
const DOMAIN = 'mail.virtualscienceforum.org'
const ADD_MEMBER_URL = MAILGUN_API_URL + '/lists/' + LIST + '@' + DOMAIN + '/members'
const GET_LISTS_URL = MAILGUN_API_URL + '/lists/pages'

const base64encodedData = Buffer.from(USER + ':' + MAILGUNAPIKEY).toString('base64');

// Method to convert a dictionary
const urlfy = obj =>
  Object.keys(obj)
    .map(k => encodeURIComponent(k) + "=" + encodeURIComponent(obj[k]))
    .join("&");

const testForm = `
  <!DOCTYPE html>
  <html>
  <body>
  <h1>Hello World</h1>
  <p>This is all generated using a Worker</p>
  <form action="/" method="post">
    <div>
      <label for="say">What is your email?</label>
      <input name="address" id="address" value="test@here.now">
    </div>
    <div>
      <label for="name">What should we call you?</label>
      <input name="name" id="name" value="Mom">
    </div>
    <div>
      <button>Sign me up!</button>
    </div>
  </form>
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

async function handleRequest(request) {
  const formData = await request.formData()
  const bodydata = {}
  for (const entry of formData.entries()) {
    bodydata[entry[0]] = entry[1]
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

  const response = await fetch(ADD_MEMBER_URL, bodyoptions)
  const results = await gatherResponse(response)

  let init = {
    headers: {
      "Content-Type": "text/html;charset=UTF-8",
    },
  }
  return new Response(results, init)
}

async function askForLists(request) {
  const init = {
    method: "GET",
    headers: {
      "content-type": "application/json;charset=UTF-8",
      'Authorization': 'Basic ' + base64encodedData
    },
  }

  const response = await fetch(GET_LISTS_URL, init)
  const results = await gatherResponse(response)
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
