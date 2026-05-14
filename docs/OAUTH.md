# OAuth setup — Spotify Developer Dashboard

This server uses Spotify's **OAuth 2.0 Authorization Code flow with PKCE**
(RFC 7636). PKCE has two advantages over the older client-secret flow:

- **No client secret** to leak or rotate. The cryptographic challenge is
  generated fresh on each authorization.
- **Refresh tokens don't expire** unless the user manually revokes the app
  at <https://www.spotify.com/account/apps/>.

## 1. Create a Spotify Developer app

1. Sign in at <https://developer.spotify.com/dashboard> with the Spotify
   account that holds your Premium subscription.
2. Click **Create app**.
3. Fill in the form:

   | Field           | Value                                          |
   | --------------- | ---------------------------------------------- |
   | App name        | Anything — e.g. `spotify-wrapped-mcp`.         |
   | App description | "Personal Spotify analytics MCP server" works. |
   | Website         | Leave blank, or paste a link to your fork.     |
   | Redirect URI    | `http://127.0.0.1:8765/callback` — **exact match**. |
   | APIs/Services   | Check **Web API**.                             |

   > **Redirect URI gotcha.** Spotify is strict. It must be the
   > **loopback IP** `127.0.0.1`, **not** `localhost`. The port must be
   > `8765`. The path must be `/callback`. Any deviation produces
   > `INVALID_CLIENT: Invalid redirect URI` at consent time.

4. Accept the **Developer Terms of Service**, then **Save**.
5. Open the app → **Settings**. Copy the **Client ID**. There is no
   client secret to copy.

## 2. (Development Mode) Add yourself to user management

By default, new apps are in **Development Mode**, which has a hard cap of
**5 authorized users** and requires the app owner to maintain Premium.
The app owner's Spotify account is added automatically. If you see
`User not registered in the Developer Dashboard` during consent:

1. Open the app → **User Management**.
2. **Add new user**: enter the display name and email on your Spotify
   account.
3. Retry the auth flow.

You can stay in Development Mode forever for personal use. Switching to
Production Mode requires Spotify's review (not needed for this server).

## 3. Run the bootstrap

```bash
SPOTIFY_CLIENT_ID=<paste-client-id> spotify-wrapped-mcp-auth
```

The command:

1. Generates a PKCE verifier + S256 challenge + random `state`.
2. Spins up a one-shot HTTP server on `127.0.0.1:8765`.
3. Opens your browser to Spotify's consent page (`--no-browser` skips this
   and just prints the URL).
4. Captures the callback, validates the `state`, exchanges the code for
   tokens.
5. Writes `~/.config/spotify-wrapped-mcp/credentials.json` (mode `0600`).

Want shell exports instead of a file? `--output-env`:

```bash
spotify-wrapped-mcp-auth --client-id <…> --output-env > .env
```

## 4. Verify

```bash
spotify-wrapped-mcp test
```

Expected output (your details, not mine):

```
HTTP 200 OK
  display_name : alice_example
  id           : alice_example
  product      : premium
  country      : PL
  scopes       : user-read-recently-played user-top-read user-library-read \
                 playlist-read-private user-read-currently-playing \
                 user-read-playback-state
  credentials  : /home/you/.config/spotify-wrapped-mcp/credentials.json
```

If you get `product: free`, some tools (now-playing, playback state) won't
work. Everything else will.

## Troubleshooting

| Symptom                                                     | Likely cause                                                          | Fix                                                                                              |
| ----------------------------------------------------------- | --------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| `INVALID_CLIENT: Invalid redirect URI`                      | Redirect URI mismatch in the dashboard                                | Set it to **exactly** `http://127.0.0.1:8765/callback` (loopback IP, not `localhost`).           |
| `User not registered in the Developer Dashboard`            | App is in Development Mode and your account isn't on the user list    | Dashboard → User Management → add your Spotify email.                                            |
| `Address already in use` when starting the auth flow        | Port 8765 is occupied                                                 | Pick another port: `--redirect-uri http://127.0.0.1:NNNNN/callback` and update the dashboard.    |
| Browser opens to Spotify, then `error=access_denied`        | You clicked **Cancel** on the consent screen                          | Re-run; click **Agree**.                                                                          |
| `HTTPStatusError: 401` from `spotify-wrapped-mcp test`      | Refresh token revoked, or the dev app was deleted/regenerated         | Re-run `spotify-wrapped-mcp-auth`. If still failing, regenerate the dashboard app.               |
| Timeout waiting for callback                                | Browser didn't actually load the authorize URL                        | Re-run with `--no-browser` and paste the printed URL into a browser manually.                    |
| `429 Too Many Requests`                                     | Rate limited                                                          | Back off. Rate limits are per-app per-user and reset quickly.                                    |

## Revoking access

Visit <https://www.spotify.com/account/apps/> → find your app → **Remove
Access**. This invalidates the refresh token immediately; next call from
`SpotifyClient` will fail with `400 invalid_grant` and you'll need to
re-run `spotify-wrapped-mcp-auth`.
