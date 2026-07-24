# Copyright (C) 2026 Ethan Martin
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3 of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
def library_song_to_subsonic(library_song):
    album_name = library_song.get("album_name")
    if not album_name and library_song.get("album"):
        album_name = library_song["album"].get("name")
    song = {
        "id": library_song["song_id"],
        "title": library_song["name"],
        "track": library_song.get("track", 1),
        "duration": library_song.get("duration") or 0,
        "artist": library_song.get("artist_name", "Unknown Artist"),
        "artistId": library_song["artist_id"],
        "album": album_name or "Unknown Album",
        "coverArt": library_song.get("album_id") or library_song["song_id"],
        "bitRate": library_song.get("bitrate") or 0,
        "path": library_song.get("path") or "",
        "discNumber": library_song.get("disc", 1),
    }
    if library_song.get("album_id"):
        song["album_id"] = library_song["album_id"]
    if library_song.get("starred"):
        song["starred"] = library_song["starred"]
    if library_song.get("year"):
        song["year"] = library_song["year"]
    return song


def library_songs_to_subsonic(library_songs):
    return [library_song_to_subsonic(song) for song in library_songs]


def library_album_to_subsonic(library_album, include_songs=True):
    songs = []
    if include_songs and library_album.get("songs"):
        songs = library_songs_to_subsonic(library_album["songs"])
    album = {
        "id": library_album["album_id"],
        "album": library_album["name"],
        "title": library_album["name"],
        "name": library_album["name"],
        "coverArt": library_album["album_id"],
        "songCount": library_album.get("song_count", 0),
        "duration": 0,
        "playCount": 0,
        "artistId": library_album["artist_id"],
        "artist": library_album.get("artist_name", "Unknown Artist"),
        "year": library_album.get("release_date", "")[:4] if library_album.get("release_date") else None,
    }
    if songs:
        album["duration"] = sum((song.get("duration") or 0) / 1000 for song in songs)
    if include_songs and songs:
        album["song"] = songs
    extra_images = library_album.get("extra_images")
    if extra_images:
        album["extraCoverArt"] = [
            {"id": img["image_id"], "type": img["image_type"]}
            for img in extra_images
        ]
    return album


def library_albums_to_subsonic(library_albums, include_songs=False):
    return [library_album_to_subsonic(album, include_songs) for album in library_albums]


def library_artist_to_subsonic(library_artist):
	cover_art = library_artist.get("cover_art") or library_artist["artist_id"]
	result = {
		"id": library_artist["artist_id"],
		"name": library_artist["name"],
		"coverArt": cover_art,
		"albumCount": library_artist.get("album_count", 0),
		"userRating": 0,
		"sortName": library_artist["name"],
		"album": library_albums_to_subsonic(library_artist.get("albums", []), include_songs=False),
	}
	if library_artist.get("inception_year"):
		result["inceptionYear"] = library_artist["inception_year"]
	if library_artist.get("biography"):
		result["biography"] = library_artist["biography"]
	return result


def library_playlist_to_subsonic(playlist, entries: list | None = None):
    result = {
        "id": playlist["playlist_id"],
        "name": playlist["name"],
        "comment": playlist.get("comment", "") or "",
        "owner": playlist.get("owner", "admin"),
        "public": bool(playlist.get("public", False)),
        "songCount": playlist.get("song_count", 0),
        "duration": playlist.get("duration", 0),
        "created": playlist.get("created", ""),
        "changed": playlist.get("changed", ""),
    }
    if entries:
        result["entry"] = library_songs_to_subsonic(entries)
    return result


def library_playlists_to_subsonic(playlists):
    return [library_playlist_to_subsonic(p) for p in playlists]


def library_artists_to_subsonic(library_artists):
    return [library_artist_to_subsonic(artist) for artist in library_artists]
