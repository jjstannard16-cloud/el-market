#!/usr/bin/env python3
"""
probe.py - scratch space for looking at a source before building on it.

This sandbox cannot reach the Eternal Lands sites, so anything that
needs looking at gets written here and run through the Probe workflow.
Replace the body with whatever the current question is.

Already checked, so nobody checks it twice:

  Where does a player's guild come from?  Nowhere, as of 23 November
  2026. Every candidate was tried and every one of them failed:

    game.eternal-lands.com/view_user.php   attributes and skills only
    game.eternal-lands.com/online_players  players and bots, no guilds
    mercator /api/v1/players/online        in the docs, but 404
    mercator /onlineplayer                 needs a login, and a member
                                           confirmed it shows no guild
                                           tags once you are in
    eternal-lands.com/page/guild_list.php  navigation chrome, no guilds
    top.el-db.com                          only a menu link
    el.other-life.com/top/guild50.php      the Top Guilds page the
                                           official menu points at. The
                                           site is gone

  So guild membership is hand-kept in guild.txt, which now takes a
  roster pasted in whatever shape it arrives. The only real fix is the
  developers publishing it.

  Does the quest guide have the god rank items?  No - it says only
  "a batch of a specific item". The wiki has the full table including
  whether items go in inventory or storage, and el_gods.py reads it.
"""

print(__doc__)
