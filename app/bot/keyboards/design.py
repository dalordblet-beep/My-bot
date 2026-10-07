"""Design tokens.

Telegram gives an inline button exactly three colours. That is the hard limit,
so colour cannot be the thing that makes a menu expressive - if every row gets a
different colour it reads as noise, and if every row gets the same one it reads
as flat. The system below fixes both problems by giving colour exactly one job
(consequence) and letting the icon carry identity.

Colour = consequence
--------------------
``success``  green   the action gives the user something good, or confirms.
                     Run search, verify, unblock, save, claim.
``primary``  blue    navigation and neutral actions. Menu entries, lists,
                     pagination, opening a section.
``danger``   red     destructive or restricted. Block, restrict, remove, and
                     the admin area. Never used for "fun".
``None``     plain   secondary and meta. Back, main menu, page counters.

A screen should have **one** dominant colour. One green call to action reads as
a hierarchy; four different colours read as a rainbow.

Icons = identity
----------------
Every icon comes from :data:`app.services.emoji.PLAIN`, which is backed by real
Telegram custom emoji, so the whole interface renders in one visual family.

Layout rules, enforced by tests
-------------------------------
1. **A row is either fully iconed or fully plain.** Mixing inside a row is the
   single biggest source of "this looks unfinished".
2. **Value pickers are plain.** A row of numbers (lengths, ratings, page
   numbers) is data, not an action, so it carries no icons - and because the
   whole row follows the rule, it looks deliberate.
3. **Action rows are fully iconed.** Every button that does something has an
   icon.
4. **Icons do not repeat within a row** unless the buttons are the same action
   with a different parameter (the four restriction durations, the four
   privilege levels).
"""

from __future__ import annotations

from enum import Enum

from aiogram.enums import ButtonStyle


class Role(str, Enum):
    """What a button does - the only thing colour is allowed to encode."""

    POSITIVE = "positive"      # gives the user something good, or confirms
    NAVIGATE = "navigate"      # moves between screens, opens a section
    DESTRUCTIVE = "destructive"  # removes, blocks, restricts, is irreversible
    SECONDARY = "secondary"    # back, main menu, meta


#: Role -> button style. The whole point of the module.
STYLE_FOR_ROLE: dict[Role, str | None] = {
    Role.POSITIVE: ButtonStyle.SUCCESS,
    Role.NAVIGATE: ButtonStyle.PRIMARY,
    Role.DESTRUCTIVE: ButtonStyle.DANGER,
    Role.SECONDARY: None,
}

#: Icons that belong to a role by default, so the same kind of action always
#: looks the same across every screen.
ROLE_ICON = {
    Role.POSITIVE: "check",
    Role.NAVIGATE: "arrow_right",
    Role.DESTRUCTIVE: "cross",
    Role.SECONDARY: "back",
}


def style(role: Role) -> str | None:
    return STYLE_FOR_ROLE[role]


# Convenience aliases - the three styles, spelled the way keyboards read best.
POSITIVE = STYLE_FOR_ROLE[Role.POSITIVE]
NAVIGATE = STYLE_FOR_ROLE[Role.NAVIGATE]
DESTRUCTIVE = STYLE_FOR_ROLE[Role.DESTRUCTIVE]
SECONDARY = STYLE_FOR_ROLE[Role.SECONDARY]
