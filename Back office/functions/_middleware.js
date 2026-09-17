export async function onRequest({ request, next }) {
  const url = new URL(request.url);
  if (url.hostname === "equalspa-admin.pages.dev") {
    const target = new URL(url.pathname + url.search, "https://admin.equalspa.tw");
    return Response.redirect(target.toString(), 301);
  }
  return next();
}
