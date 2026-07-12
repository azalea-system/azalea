# Why?
Why use Azalea? I'll tell you why.

## List of advantages of the azalea server over other music streaming platforms:
- Open-source, free software - azalea's source code is available for anyone to view, modify, and redistribute. No mainstream music streaming platform seriously open-sources the code that powers their services, why would they not if it is more ethical? That's for you to figure out.
- Instant loading times for music - tracks instantly start playing and scrubbing through is super smooth.
- Higher quality - higher quality supported than all mainstream free music services, as lossless quality is supported by azalea.
- No ads, tracking, or data collection whatsoever.
- No subscription fees - azalea is completely free to use, with no hidden costs or premium tiers.
- No DRM - azalea does not use any form of digital rights management, allowing users to freely enjoy their music without restrictions. Azalea will never lock you out, it's here to serve you, not be served by you.
- Metadata fetching attemps for any of your music. Platforms like Spotify allow uploading music not on their service, but they don't fetch metadata for it or make an attempt to integrate it with the rest of the application. Azalea tries its very best to make everything as seamless as possible, as it has no hidden incentives and is not a commerical product.
- Allows you to use any compatible client which includes not only azalea-compatible but subsonic/opensubsonic/navidrome-compatible clients which is a huge number of apps to choose from. Jellyfin client support is planned.
- Azalea cares about you and will always put the user first. Feel free to suggest features and of course, report bugs :)

## Advantages when you're using azalea-web (the recommended but not required UI for azalea) as your client over other streaming service UIs:
- Also open-source, also has no ads, also has no tracking, also has no data collection, also has no fee, and also has no DRM. How hard was that? Pretty easy, actually.
- Album covers are fully zoomable, pannable. Great for finding tiny, hidden details in artwork designed for big vinyl covers.
- Lyrics panel is a drawer, meaning that the app can still be used while lyrics are being displayed, but the lyrics drawerr can also be resized and maximised to give the same feel as other services.
- Keybinds - azalea lets you wrangle your collection with only keyboard easily.
- You can copy album titles, artist names & song names to your clipboard via context menus.
- Fully customisable appearance - azalea-web has a plethora of options to fine tune the appearance. If you still feel limited by the options built in, you can inject your own CSS to make it yours. No need for plugins or extensions.
- Option to autoplay on page load
- Option to proxy requests through the azalea-web backend so that only azalea-web needs to be accessible to you, and the azalea server accessible to azalea-web for everything to work. Good for port forwarding security, though this is NOT recommended at all, neither azalea or azalea-web are ready to be on the public internet, there may be security vulnerabilities.
- Three-queue system: first queue is the currently playing song plus any songs which were chosen to be played next or added to the queue. The second queue is songs queued up from the current album, playlist, or wherever else the song was played from. The third queue is made up of random songs. In the future a recommendation algorithm will be implemented.
