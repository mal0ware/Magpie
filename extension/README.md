# Magpie Bridge (browser extension)

`magpie sync` cannot log in to Instagram and does not try to. This extension
sits in your own browser, where you are already logged in, and asks Instagram
for your Saved posts the same way the site does. It works in any Chromium
browser (Chrome, Edge, Brave, Vivaldi, Opera GX): it uses no debugger and no
tab groups.

## Load it

`magpie setup` shows these steps and waits for you.

1. Open your browser and log in to instagram.com.
2. Go to `chrome://extensions` (in Opera, `opera://extensions`).
3. Switch on **Developer mode** (top right).
4. Click **Load unpacked** and pick this `extension` folder.
5. "Magpie Bridge" appears in the list. Leave the browser open.

To check it by hand, in a terminal:

```
magpie bridge --status     # starts the local daemon, says whether the extension connected
magpie sync                # lists your saves into the library
```

The extension looks for the daemon every 30 seconds, so give it half a minute
after the first `magpie bridge --status`.

If you move or delete the folder, the browser drops the extension; load it
again from the new place. After pulling a new version, press the reload arrow
on its card on the extensions page.

## What it does

- Keeps a WebSocket open to `ws://127.0.0.1:19877`, the daemon that
  `magpie` starts on this machine. It talks to nothing else.
- When the daemon asks, it finds an instagram.com tab (or opens one in the
  background) and makes one `GET /api/v1/feed/saved/posts/` request from inside
  it, then hands the answer back. One request per ask, no retries.
- A tab it opened itself, it closes again: when Magpie says the sync is done,
  or after the tab has gone two minutes unused. A tab you opened, or one of
  its own that you switch to, is left alone.
- It reads your saved feed. The one change it can make is unsaving a post, and
  only when you pick the post in Magpie and press Unsave (one
  `POST /api/v1/web/save/<id>/unsave/` per post). It never saves, likes, posts
  or follows.

Permissions: `scripting` and `tabs` to run that request in an instagram.com
tab, `alarms` to reconnect to the daemon, `storage` to remember which tab it
opened (session only, nothing is written to disk), and host access to
`https://www.instagram.com/*` only.

## If something stops

`magpie sync` stops at the first sign of trouble and tells you which it was:

| It says | Do this |
|---|---|
| extension is not connected | Check the steps above; the browser must be open. |
| Instagram wants a login | Log in to instagram.com in the browser, then sync again. |
| rate limiting (HTTP 429) | Leave it for a few hours. Do not keep trying. |
| checkpoint or challenge | Open instagram.com and clear the prompt yourself first. |

To see what the extension is doing, click **Service worker** on its card on
the extensions page and read the console. The daemon's log is
`~/.magpie/bridge.log`. `magpie sync --raw-dir some/folder` writes each raw
reply to disk, which is the thing to look at if posts come through with fields
missing.
