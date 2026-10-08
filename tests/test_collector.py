"""Collector features: comparables, valuation, portfolio and listing watch."""

from __future__ import annotations

from app.collectible.fragment import FragmentClient, FragmentListing, _ton_value
from app.collectible.valuation import estimate_price
from app.database import repository as repo
from app.search.traps import TrapWatcher
from app.utils.value import estimate_value, is_brand


# --------------------------------------------------------------------- comparables
def test_ton_value_parsing():
    assert _ton_value("23,665") == 23665
    assert _ton_value("1 234") == 1234
    assert _ton_value(None) is None
    assert _ton_value("n/a") is None


async def test_market_stats_aggregate_by_length(monkeypatch):
    client = FragmentClient(enabled=True)

    async def fake_browse(query, limit=0):
        return [
            FragmentListing("aaaaa", "100", None, "u"),
            FragmentListing("bbbbb", "300", None, "u"),
            FragmentListing("ccccc", "200", None, "u"),
            FragmentListing("dddd", "9999", None, "u"),  # different length
        ]

    monkeypatch.setattr(client, "browse", fake_browse)
    stats = await client.market_stats(length=5)
    assert stats is not None
    assert stats.count == 3
    assert stats.low == 100
    assert stats.high == 300
    assert stats.median == 200


async def test_market_stats_none_when_empty(monkeypatch):
    client = FragmentClient(enabled=True)

    async def empty(query, limit=0):
        return []

    monkeypatch.setattr(client, "browse", empty)
    assert await client.market_stats(length=5) is None


async def test_sold_highlights_picks_most_expensive(monkeypatch):
    client = FragmentClient(enabled=True)

    async def fake_browse(query, limit=0):
        return [
            FragmentListing("aaaaa", "100", None, "u"),
            FragmentListing("bbbbb", "3000", None, "u"),
            FragmentListing("ccccc", "200", None, "u"),
        ]

    monkeypatch.setattr(client, "browse", fake_browse)
    top = await client.sold_highlights(length=5, limit=2)
    assert [item.name for item in top] == ["bbbbb", "ccccc"]


# ------------------------------------------------- "unowned" != "not a collectible"
async def test_collectible_checker_does_not_shortcircuit_on_unowned(monkeypatch):
    """An unassigned collectible resolves as not_occupied yet is really listed.

    The old shortcut trusted resolveUsername and reported such a name as "not
    listed" - which is how ``roundup`` (556 TON on Fragment) showed as empty.
    Fragment must get the final word.
    """
    from app.collectible.checker import CollectibleChecker
    from app.collectible.fragment import FragmentClient, FragmentLookup
    from app.telegram import mtproto as mtproto_module
    from app.telegram.mtproto import MtprotoResult
    from app.utils.enums import CollectibleStatus

    async def fake_resolve(name):
        return MtprotoResult("not_occupied")

    async def fake_lookup(self, name):
        return FragmentLookup(
            status=CollectibleStatus.AVAILABLE_FOR_PURCHASE,
            is_collectible=True,
            price="556 TON",
            source="fragment_web",
        )

    monkeypatch.setattr(mtproto_module.mtproto_client, "_ready", True, raising=False)
    monkeypatch.setattr(
        mtproto_module.mtproto_client, "resolve_username", fake_resolve, raising=False
    )
    monkeypatch.setattr(FragmentClient, "lookup", fake_lookup)

    result = await CollectibleChecker().check_collectible_username("roundup")
    assert result.is_collectible is True
    assert result.price == "556 TON"


# --------------------------------------------------------------------- value
def test_brand_detection():
    assert is_brand("@nike")
    assert is_brand("Google")
    assert not is_brand("bapug")


def test_estimate_value_shorter_scores_higher():
    assert estimate_value("abc")["score"] > estimate_value("abcdefghij")["score"]


# -------------------------------------------------------- estimate_price (single number)
def _five_char_premium_listings():
    # Clean, premium-sounding 5-char collectibles like Fragment actually lists.
    return [
        FragmentListing("pizza", "3000", None, "u"),
        FragmentListing("music", "5000", None, "u"),
        FragmentListing("angel", "4000", None, "u"),
        FragmentListing("tiger", "2000", None, "u"),
        FragmentListing("queen", "7000", None, "u"),
    ]


def test_estimate_price_ordinary_digit_name_has_no_price():
    """A random digit-bearing name has no comparable, so it has **no price**.

    It used to get an invented floor from a hard-coded table - a number that was
    not market data at all, printed next to a real listing count and read as a
    valuation. The honest answer is "nothing comparable on the market".
    """
    listings = _five_char_premium_listings()
    assert estimate_price("iduc9", listings) is None


def test_estimate_price_premium_word_uses_comparables():
    """A clean premium 5-char word is valued from its real same-length peers."""
    listings = _five_char_premium_listings()
    price = estimate_price("pizza", listings)
    # median of the pool is 4000; the name is a genuine comparable.
    assert price is not None
    assert 2000 <= price <= 7000


def test_estimate_price_monotonic_rarer_costs_more():
    """Cleaner/shorter -> higher than ordinary, when both have comparables."""
    listings = _five_char_premium_listings() + [
        # Enough digit peers to form a real comparable set.
        FragmentListing("gupo6", "40", None, "u"),
        FragmentListing("ve7ci", "60", None, "u"),
        FragmentListing("ge2vo", "80", None, "u"),
    ]
    premium = estimate_price("pizza", listings)   # clean 5-char word
    ordinary = estimate_price("iduc9", listings)  # random 5-char w/ digits
    assert premium is not None and ordinary is not None
    assert premium > ordinary


def test_estimate_price_no_market_data_is_none():
    assert estimate_price("pizza", []) is None


def test_estimate_price_digit_name_never_borrows_clean_prices():
    """A digit name only borrows from digit listings, never clean ones."""
    # A clean premium pool, plus a single modest digit peer: not enough digit
    # peers to form a comparable set, so there is no price at all - the name is
    # never priced like the thousands-of-TON clean names it shares a length with.
    listings = _five_char_premium_listings() + [
        FragmentListing("gupo6", "40", None, "u"),
    ]
    assert estimate_price("iduc9", listings) is None


def test_price_basis_reports_the_listings_it_rests_on():
    """The estimate must be auditable: spread and count, from real listings."""
    from app.collectible.valuation import price_basis

    basis = price_basis("pizza", _five_char_premium_listings())
    assert basis is not None
    assert basis.count == 5
    assert basis.low == 2000 and basis.high == 7000
    assert basis.median == 4000
    assert price_basis("iduc9", _five_char_premium_listings()) is None


# --------------------------------------------------------------------- portfolio
async def test_portfolio_crud(session):
    user, _ = await repo.get_or_create_user(session, 9001, "tester")

    item, created = await repo.add_portfolio(session, user, "@Love")
    assert created is True
    assert item.username == "love"

    again, created2 = await repo.add_portfolio(session, user, "love")
    assert created2 is False
    assert again.id == item.id

    await repo.update_portfolio_value(session, item, "5,050 TON", "OWNED")
    rows = list(await repo.list_portfolio(session, user))
    assert rows[0].last_price == "5,050 TON"
    assert await repo.count_portfolio(session, user.telegram_id) == 1

    assert await repo.remove_portfolio(session, user, item.id) is True
    assert await repo.count_portfolio(session, user.telegram_id) == 0


# --------------------------------------------------------------------- listing watch
class _FakeFragment:
    def __init__(self, listings):
        self._listings = listings

    async def browse(self, query, limit=0):
        return list(self._listings)


class _FakeCollectible:
    def __init__(self, listings):
        self.fragment = _FakeFragment(listings)


class _FakeTrap:
    kind = "listing"

    def __init__(self, keyword, last_status=None):
        self.id = 1
        self.username = keyword
        self.telegram_id = 42
        self.last_status = last_status


async def test_listing_watch_baselines_then_alerts(monkeypatch):
    notified: list = []
    state = {"status": None}

    async def fake_record(trap_id, status, freed=False):
        state["status"] = status
        return True

    async def fake_notify(self, telegram_id, name, price):
        notified.append((name, price))

    monkeypatch.setattr(TrapWatcher, "_record", staticmethod(fake_record))
    monkeypatch.setattr(TrapWatcher, "_notify_listing", fake_notify)

    listings = [FragmentListing("crypto1", "500", "Resale", "u")]
    watcher = TrapWatcher(
        bot=None, checker=None, collectible_checker=_FakeCollectible(listings)
    )
    trap = _FakeTrap("crypto")

    # First sweep: baseline only - the existing set must not fire.
    await watcher._sweep_listing(trap)
    assert notified == []
    assert state["status"].startswith("ls:")

    # A genuinely new matching lot appears: exactly one alert.
    trap.last_status = state["status"]
    listings.append(FragmentListing("cryptox", "700", "Resale", "u"))
    await watcher._sweep_listing(trap)
    assert notified == [("cryptox", "700")]

    # No change on the next sweep: no repeat alert.
    trap.last_status = state["status"]
    await watcher._sweep_listing(trap)
    assert notified == [("cryptox", "700")]
