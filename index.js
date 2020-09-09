const MAILGUN = "https://api.eu.mailgun.net/v3"
const USER = 'api';
const LIST = 'temporary_test_list'
const DOMAIN = 'mail.virtualscienceforum.org'
const KEY = "???"

const URL = MAILGUN + '/lists/' + LIST + '@' + DOMAIN + '/members.json'
const base64encodedData = Buffer.from(USER + ':' + KEY).toString('base64');

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

function rawHtmlResponse(html) {
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
  const body = {}
  for (const entry of formData.entries()) {
    body[entry[0]] = entry[1]
  }

  console.log(body)

  var members = []
  members.push(body)

  const init = {
    // body: {
    //   'subscribed':true,
    //   'address':body.address,
    //   'name':body.name
    // },
    body: JSON.stringify(members),
    method: "POST",
    headers: {
      //"content-type": "text/html;charset=UTF-8",
      "content-type": "application/json;charset=UTF-8",
      'Authorization': 'Basic ' + base64encodedData,
    },
  }

  console.log(init)

  const response = await fetch(URL, init)
  const results = await gatherResponse(response)
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

  const p = MAILGUN + '/lists/pages'
  const response = await fetch(p, init)
  const results = await gatherResponse(response)
  return new Response(results, init)
}

addEventListener("fetch", event => {
  const { request } = event
  const { url } = request

  if (url.includes("add")) {
      return event.respondWith(rawHtmlResponse(testForm))
  }

  if (url.includes("lists")) {
      return event.respondWith(askForLists(request))
  }

  if (request.method === "POST") {
    return event.respondWith(handleRequest(request))
  }
  else {
    return event.respondWith(new Response(`Expecting a POST request`))
  }
})
