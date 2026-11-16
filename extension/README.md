# Magpie Bridge (browser extension)

`magpie sync` cannot log in to Instagram and does not try to. This extension
sits in your own browser, where you are already logged in, and asks Instagram
for your Saved posts the same way the site does. It works in Opera GX because
it uses no debugger and no tab groups.

## Load it in Opera GX

1. Open Opera GX and log in to instagram.com.
2. Go to `opera://extensions`.
3. Switch on **Developer mode** (top right).
4. Click **Load unpacked** and pick this `extension` folder.
5. "Magpie Bridge" appears in the list. Leave the browser open.

Then, in a terminal:

```
magpie bridge --status     # starts the local daemon, says whether the extension connected
magpie sync --limit 30     # lists your 30 most recent saves into the library
```

The extension looks for the daemon every 30 seconds, so give it half a minute
after the first `magpie bridge --status`. Chrome, Edge and Brave work the same
way through their own extensions page.

If you move or delete the folder, the browser drops the extension; load it
again from the new place. After pulling a new version, press the reload arrow
on its card in `opera://extensions`.

## What it does

- Keeps a WebSocket open to `ws://127.0.0.1:19877`, the daemon that
  `magpie` starts on this machine. It talks to nothing else.
- When the daemon asks, it finds an instagram.com tab (or opens one in the
  background) and makes one `GET /api/v1/feed/saved/posts/` request from inside
  it, then hands the answer back. One request per ask, no retries.
- It reads your saved feed. The one change it can make is unsaving a post, and
  only when you pick the post in Magpie and press Unsave (one
  `POST /api/v1/web/save/<id>/unsave/` per post). It never saves, likes, posts
  or follows.

Permissions: `scripting` and `tabs` to run that request in an instagram.com
tab, `alarms` to reconnect to the daemon, and host access to
`https://www.instagram.com/*` only.

## If something stops

`magpie sync` stops at the first sign of trouble and tells you which it was:

| It says | Do this |
|---|---|
| extension is not connected | Check the steps above; the browser must be open. |
| Instagram wants a login | Log in to instagram.com in the browser, then sync again. |
| rate limiting (HTTP 429) | Leave it for a few hours. Do not keep trying. |
| checkpoint or challenge | Open instagram.com and clear the prompt yourself first. |

To see what the extension is doing, click **Service worker** on its card in
`opera://extensions` and read the console. The daemon's log is
`~/.magpie/bridge.log`. `magpie sync --raw-dir some/folder` writes each raw
reply to disk, which is the thing to look at if posts come through with fields
missing.
