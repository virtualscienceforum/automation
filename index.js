addEventListener('fetch', event => {
  const request = event.request
  const url = "https://example.com"

  const modifiedRequest = new Request(url, {
    body: request.body,
    headers: request.headers,
    method: request.method,
    redirect: request.redirect
  })

  event.respondWith(handleRequest(modifiedRequest))
})

/**
 * Respond with hello worker text
 * @param {Request} request
 */
async function handleRequest(request) {
  const init = {
    headers: {'content-type':'text/plain'},  // 'application/json'
  }
  // const body = JSON.stringify({some:'json'})

  let response
  if( request.method === "GET") {
    response = new Response('Hello VSF participant!', init)
  } else {
    response = new Response("Expected POST", { status: 500 })
  }
  return response
}
