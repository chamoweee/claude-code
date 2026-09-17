/* Netlify wrapper around the shared handler in api/. */
const handler = require("../../api/create-checkout-session.js");

exports.handler = async (event) => {
  let status = 200;
  const headers = {};
  let body = "";

  const res = {
    set statusCode(v) { status = v; },
    get statusCode() { return status; },
    setHeader: (k, v) => { headers[k] = v; },
    end: (chunk) => { body = chunk || ""; },
  };

  const req = {
    method: event.httpMethod,
    headers: event.headers || {},
    body: event.body,
  };

  await handler(req, res);
  return { statusCode: status, headers, body };
};
