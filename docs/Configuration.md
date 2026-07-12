# Azalea Configuration Guide

This document provides a comprehensive reference guide for creating and customizing the `config.toml` configuration file for Azalea.

NOTE: This documentation was partially written by a large language model, but has of course been checked by a human.

> [!WARNING]  
> **DO NOT MODIFY THE DEFAULT CONFIGURATION FILE DIRECTLY!** > To configure Azalea, create a new custom file named `config.toml` in the same directory as the default config file, or specify an alternative path using the `AZALEA_CONFIG_PATH` environment variable.

---

## Table of Contents
1. [General Settings](#1-general-settings)
2. [Management UI & Authentication](#2-management-ui--authentication)
3. [Music Configuration & Metadata](#3-music-configuration--metadata)
4. [Networking & Downloads](#4-networking--downloads)
5. [Diagnostics & System Integration](#5-diagnostics--system-integration)
6. [Media Collections](#6-media-collections)

---

## 1. General Settings
These configurations define the core directories and base database options used by Azalea.

| Configuration Key | Default Value | Description |
| :--- | :--- | :--- |
| `library_path` | `"~/Azalea Library"` | Root directory used for application caching and the default storage target for newly initialized collections. |
| `database_path` | `"~/Azalea Library/azalea.db"` | Path to the local database file when using the default SQLite architecture. |
| `custom_database_uri` | `""` | A connection URI (e.g., `postgresql+psycopg2://user:pass@host:port/dbname`) for external databases. If provided, SQLite settings are ignored. |

---

## 2. Management UI & Authentication
Controls features for the integrated web dashboard interface and controls connection access limitations.

| Configuration Key | Default Value | Description |
| :--- | :--- | :--- |
| `management_ui` | `true` | Toggle switch to enable (`true`) or disable (`false`) the web-based management UI completely. |
| `item_limit_on_multi_table_pages` | `15` | The maximum row items displayed on composite dashboards (e.g., track listings under an Artist page) before a "Show More" option is required. |
| `auth` | `false` | Enables system-wide challenge authentication filters when set to `true`. |
| `auth_username` | `""` | Dedicated username value required when `auth = true`. |
| `auth_password` | `""` | Dedicated password string value required when `auth = true`. |
| `auth_token` | `""` | Alternative structural token pattern string used for machine or API header authentication frameworks. |

---

## 3. Music Configuration & Metadata
Alters how tracks are cataloged, parsed, and enriched through online indexing nodes.

| Configuration Key | Default Value | Description |
| :--- | :--- | :--- |
| `hide_track_number` | `true` | Automatically strips sequence indices out of display fields (e.g., `"01 Hey Jude"` normalizes to `"Hey Jude"`). |
| `hide_mix_year` | `true` | Strips out year markings or mix contexts from titles (e.g., `"Hey Jude (Remastered 2009)"` scales down to `"Hey Jude"`). |
| `ignored_articles` | `"The An A Die..."` | A space-separated list of localized articles excluded from alphabetical sort weights for sorting groups. |
| `musicbrainz_metadata` | `true` | Pulls advanced rich metadata objects (such as HD album artwork and precise release years) dynamically from MusicBrainz endpoints. |
| `cache_musicbrainz_responses` | `true` | Caches third-party response headers locally to limit network overhead and optimize retrieval response speeds. |

---

## 4. Networking & Downloads
Handles network port bindings, structural TLS requirements, and file delivery pathways.

| Configuration Key | Default Value | Description |
| :--- | :--- | :--- |
| `port` | `3443` | The core host TCP networking port mapped to the management interface and core application layer. |
| `host` | `"0.0.0.0"` | IP address boundary binding target. Setting this parameter to `"0.0.0.0"` forces Azalea to listen across all network interfaces. |
| `verify_ssl` | `true` | Enforces strong handshake certificate checks during external lookup calls to eliminate routing security vulnerabilities. |
| `download_path` | `"~/Azalea Library/Downloads"` | Standard landing area for background processes pulling media downstream (e.g., via `yt-dlp` integration modules). |

---

## 5. Diagnostics & System Integration
System flags utilized for tracking internal runtime execution paths and application bridges.

| Configuration Key | Default Value | Description |
| :--- | :--- | :--- |
| `quart_debug` | `true` | Turns on deep debugging capabilities across the underlying Quart asynchronous application layout. |
| `rescan_library_on_startup` | `false` | When disabled (`false`), commands Azalea to completely rebuild index catalogs across all active structures on boot. |
| `verbose_logging` | `true` | Activates granular low-level tracing logs inside stdout frameworks for testing procedures. |
| `discord_rpc` | `true` | Automatically provisions Discord Rich Presence integration nodes to broadcast real-time player metadata. |

---

## 6. Media Collections
Collections tell Azalea where your content files live and how they are structured. Supported collection types include: `music`, `podcasts`, `audiobooks`, `videos`, `movies`, and `shows`.

### Collection Block Attributes
Every customized collection array requires the block attributes defined below:
* **`name`** *(String)*: Custom user-facing display string.
* **`type`** *(String)*: Media category engine discriminator type mapping.
* **`paths`** *(Array of Strings)*: Local absolute/relative system paths targeted for tracking updates.
* **`browsable_file_index`** *(Boolean)*: Allows directory tree traversals directly through the client user interfaces.
* **`assume_structure`** *(String)*: Path ordering hint paradigm pattern blueprint used for parsing folder schemas (e.g., `"Artist/Album/Song"`).
* **`enabled`** *(Boolean)*: Master execution switch for including or excluding the target folder block from scanning jobs.

### Configuration Template Example
To activate a block structure, format your entries within your `config.toml` file exactly as illustrated below:

```toml
[collections.my-music]
name = "My Music"
type = "music"
paths = ["~/Azalea Library/My Music"]
browsable_file_index = false
assume_structure = "Artist/Album/Song"
enabled = true

[collections.my-audiobooks]
name = "My Audiobooks"
type = "audiobooks"
paths = ["~/Azalea Library/My Audiobooks"]
browsable_file_index = false
assume_structure = "Artist/Album/Song"
enabled = true
