# Custom API Routes Documentation

The following routes are custom extensions unique to this server instance. They are **not** part of the Subsonic or OpenSubsonic API protocols and will only be recognized by subsonic clients explicitly compatible with Azalea.

NOTE: This documentation was partially written by a large language model, but has of course been checked by a human.

---

## ── Authentication & Configuration ──

### 1. Web UI Authentication Configuration
* **Endpoint:** `/auth-config`
* **Methods:** `GET`, `POST`
* **Description:** Manages the server's global HTTP Basic authentication settings.
* **Request (POST):**
  Expects a JSON payload to modify authentication states and credentials:
```
  {
    "auth": true,
    "auth_username": "admin",
    "auth_password": "new_secure_password"
  }
```
* **Response (GET):**
```
  {
    "auth": true,
    "auth_username": "admin",
    "has_password": true
  }
```
* **Response (POST):**
```
  { "status": "ok" }
```

---

## ── Third-Party Integration (Discord) ──

### 2. Discord OAuth Callback
* **Endpoint:** `/discord/callback`
* **Methods:** `GET`, `OPTIONS`
* **Description:** Handles the OAuth2 redirect flow from Discord. Exchanges the temporary authorization code for access and refresh tokens used to authenticate server-side Discord interactions (e.g., Rich Presence or activity sync).
* **Query Parameters:**
  * `state` *(string, required)*: The frontend origin URL where the user should be redirected back to.
  * `code` *(string)*: The temporary authorization code granted by Discord.
  * `error` *(string)*: Optional error string provided by Discord if authorization was denied.
* **Response:** A `302 Redirect` back to the frontend origin provided in the `state` parameter with either a `discord=success` or `discord=error&message=...` query string.

### 3. Get Discord Connection Status
* **Endpoint:** `/rest/getDiscordStatus`
* **Methods:** `GET`
* **Description:** Checks if the server currently possesses a saved Discord access token.
* **Response:**

  {
    "subsonic-response": {
      "status": "ok",
      "version": "1.16.1",
      "type": "Azalea",
      "serverVersion": "1.0.0",
      "openSubsonic": true,
      "discordStatus": {
        "connected": true
      }
    }
  }


### 4. Disconnect Discord Integration
* **Endpoint:** `/rest/disconnectDiscord`
* **Methods:** `POST`, `OPTIONS`
* **Description:** Revokes and removes the saved Discord tokens from the server configuration.
* **Response:**

  {
    "subsonic-response": {
      "status": "ok",
      "version": "1.16.1",
      "type": "Azalea",
      "discordStatus": {
        "connected": false
      }
    }
  }


---

## ── Server Management & Task Automation ──

### 5. Remote Server Download (Single Song)
* **Endpoint:** `/rest/downloadOnServer`
* **Methods:** `GET`
* **Description:** Triggers or polls a server-side background task (yt-dlp or internal download system) to download a missing track or placeholder song directly into the local server library.
* **Query Parameters:**
  * `id` *(string, required)*: The internal database unique identifier for the song.
* **Response (Started):**

  {
    "subsonic-response": {
      "status": "ok",
      "downloadStatus": {
        "songId": "song-123",
        "status": "started"
      }
    }
  }


### 6. Remote Server Download (Entire Album)
* **Endpoint:** `/rest/downloadAlbumOnServer`
* **Methods:** `GET`
* **Description:** Identifies all missing/placeholder songs associated with the provided album ID and spins up background tasks to download them sequentially.
* **Query Parameters:**
  * `id` *(string, required)*: The unique internal identifier for the album.
* **Response:**

  {
    "subsonic-response": {
      "status": "ok",
      "downloadStatus": {
        "albumId": "album-456",
        "status": "started",
        "started": 3,
        "total": 12
      }
    }
  }


### 7. Download Event Updates (WebSocket)
* **Endpoint:** `/rest/downloadEvents`
* **Methods:** `WEBSOCKET`
* **Description:** Establishes a persistent full-duplex connection allowing the server to push real-time download status, speeds, and job progress down to web application frontends.

### 8. Graceful Server Restart
* **Endpoint:** `/rest/restart`
* **Methods:** `GET`
* **Description:** Instructs the application backend to gracefully terminate the running event loop and trigger a system process restart after a 1-second delay.
* **Response:** A standard Subsonic wrapper payload with status `ok`.

---

## ── Protocol Behaviors & Dynamic Fallbacks ──

### 9. Dynamic On-Demand Streaming Fallback
* **Endpoint Extensions inside:** `/rest/stream`
* **Description:** While /rest/stream is a mandatory Subsonic endpoint, your implementation features a custom fallback logic hook. If the track database matches an entry that has no active filesystem path (filepath), the route automatically invokes yt-dlp to query external streaming sites, extracts an active source URL, and responds with a 302 Redirect directly to the live audio stream instead of throwing a standard 404 Not Found error.
