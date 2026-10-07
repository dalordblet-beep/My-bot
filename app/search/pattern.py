"""Username masks and the aesthetic rating.

Mask syntax (deliberately tiny, so it can be explained in one line of UI):

    ?   exactly one letter
    #   exactly one digit
    *   any run of letters (zero or more)
    _   a literal underscore
    a-z literal letters

``??ged`` matches ``moged``, ``*dev`` matches ``mydev``, ``m#ged`` matches
``m7ged``.

The rating is **our own score, not a market price**. Every point comes from a
property that can be measured on the string and that a buyer on Fragment
actually pays for, so the number is auditable and reproducible:

    length     0-30   shorter handles are structurally scarcer
    word       0-25   a real English word beats any random string
    spelling   0-20   clean, pronounceable, no clusters or repeats
    digits     0-15   digits break a handle and rarely survive as a brand
    separators 0-10   underscores and other punctuation

Three calibration rules keep the five numbers honest:

* **The length curve is gentle, not a cliff.** The first version dropped from
  26 to 5 points across six characters, so a *perfect* 10-letter word scored
  below a random 5-letter string - which made the "meaning matters" claim
  false. Meaning must be able to lift a long name above a short nobody.
* **Every criterion is graded, never binary.** ``word`` used to be a flat
  25-or-0, so a sellable brand composite (``cranehq``, ``homeshop``) - exactly
  what the generator is built to produce - scored as meaninglessly as noise.
* **Position matters as much as count.** A single trailing digit (``shop7``) is
  a common, tolerable pattern; a leading one is not; four of them are a
  different thing entirely. The old flat ``15 - 8 * digits`` treated all three
  identically.

On top of the number the rubric exposes a **grade** (S/A/B/C/D), the share of
what a name of that length could possibly score, and the single criterion that
carries it and the single one that caps it. It is never presented as a
valuation.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field

MIN_LENGTH = 5
MAX_LENGTH = 32

VOWELS = set("aeiouy")
CONSONANTS = set("bcdfghjklmnpqrstvwxyz")
LETTERS = "abcdefghijklmnopqrstuvwxyz"
# Letters that read as rare/latinised noise in a transliterated handle.
UGLY_CLUSTERS = ("q", "x", "j", "w", "z")

# Digraphs that are not spelled the way they are said. They are perfectly good
# English, but a handle you cannot spell after hearing it is a handle people
# mistype - so they cost a little.
SILENT_DIGRAPHS = ("ph", "kn", "wr", "gh", "wh", "ps", "pn", "mb", "ough")

# Two letters, one sound. Collapsed before the consonant-run check so ordinary
# words ("technology", "bishop") are not read as unpronounceable noise.
CONSONANT_DIGRAPHS = (
    "ch", "sh", "th", "ph", "wh", "gh", "ck", "ng", "qu", "kn", "wr", "ps",
)

# ------------------------------------------------------------------ the rubric
# Each criterion's own maximum. The totals must stay 100: the score is shown to
# users as "x / 100" and every part is shown against its own ceiling, so a
# drifting total would make the breakdown stop adding up.
PART_MAX: dict[str, int] = {
    "length": 30,
    "word": 25,
    "spelling": 20,
    "digits": 15,
    "separators": 10,
}
TOTAL_MAX = sum(PART_MAX.values())

# Length is the dominant structural factor, but the curve has to stay gentle
# enough that meaning can still outrank it. 4 chars is the unreachable ideal
# (Telegram refuses anything shorter than five), 5 is the real prize, and the
# fall-off from there is ~4 points per character instead of a cliff.
_LENGTH_CURVE = {4: 30, 5: 27, 6: 23, 7: 19, 8: 15, 9: 12, 10: 10, 11: 8, 12: 7}
_LENGTH_FLOOR = 5

# Grade bands. A grade is the part a user actually acts on, so the names are
# deliberately plain: S is "claim it now", D is "forget it".
GRADES: tuple[tuple[str, int], ...] = (("S", 90), ("A", 80), ("B", 65), ("C", 45), ("D", 0))
GRADE_LETTERS = tuple(letter for letter, _ in GRADES)

MASK_TOKEN_RE = re.compile(r"[?#*]|[a-z_]")
ALLOWED_MASK_RE = re.compile(r"^[a-z_?#*]+$")

# Real, brandable English words. Short common words are the most expensive
# class of handle after the 3-4 character tier, because they read as a business
# name rather than as a random string. The list is deliberately small and
# hand-checked: inventing "words" would make the rating lie, which is exactly
# the complaint this rubric exists to fix.
_WORD_SET: frozenset[str] = frozenset(
    (
        """
    about above actor adapt admin adopt adore adult after agent agile album
    alert alive alley allow alpha alter amber among ample angel anger angle
    anime ankle apple apply april arena argue arise armor aroma array arrow
    aside asset atlas audio audit avoid awake award aware badge baker balmy
    banjo basic basil basin batch beach beard beast begin being belly below
    bench berry bible bicep birch birth black blade blame blank blast blaze
    bleak blend bless blind bliss block bloom blues blunt blush board boast
    bonus boost booth bound brace brain brake brand brass brave bread break
    breed brick bride brief bring brisk broad broke bronze brook brown brush
    buddy build built bunch burnt burst cabin cable cache cadet camel candy
    canoe cargo carol carry carve catch cause cease cedar chain chair chalk
    charm chart chase cheap check cheer chess chest chief child chill china
    choir chord chose civic civil claim clamp clash clasp class clean clear
    clerk click cliff climb cling clock clone close cloth cloud clown coach
    coast cobra cocoa coral corny couch count court cover crack craft crane
    crash crate crawl crazy cream crest crime crisp cross crowd crown crude
    cruise crumb crush crust cubic curly curve cycle daily dairy daisy dance
    dared darts datum dealt debit debut decay decor decoy delay delta dense
    depot depth derby detox devil diary dicey digit diner dirty ditch diver
    dizzy dodge doing donor doubt dough dozen draft drain drama drank drawn
    dread dream dress drew drift drill drink drive droid drone drove drown
    drum dry dull dummy dunes dusky dusty dutch dwarf dwell eager eagle early
    earth easel eaten ebony edict eight elbow elder elect elite email ember
    empty enact ended endow enemy enjoy enter entry equal equip erase error
    essay ether ethic evade event every exact excel exile exist extra fable
    faced faint fairy faith false famed fancy fatal fault favor feast fence
    ferry fetch fever fiber field fiery fifth fight final finch finer fire
    first flame flash fleet flesh flint float flock flood floor flour flown
    fluid flush flute focal focus foggy force forge forth forty forum found
    frame frank fraud fresh friar fried front frost frown fruit fudge fully
    funny furry fuzzy gauge gecko genre ghost giant given giver glade gland
    glare glass gleam glide globe gloom glory gloss glove glued gnome going
    goods goose gorge grace grade grain grand grant grape graph grasp grass
    grave gravy graze great green greet grief grill grind groan groom gross
    group grove growl grown guard guess guest guide guild guilt gully gusto
    habit hairy handy happy harbor harsh haste hatch haunt haven havoc hazel
    heart heavy hedge hefty hello hence herbs heron hilly hinge hippo hobby
    hoist holly honey honor horde horse hotel hound house hover human humid
    humor hurry husky hydro hyena ideal image imply index inept infer inlet
    inner input irate irony issue ivory jaunt jelly jewel jiffy joint jolly
    joust judge juice juicy jumbo juror kayak kebab kempt khaki kinky kiosk
    kitty kneel knack knelt knife knock knoll known koala label labor laden
    ladle lager lance lapse large larva laser lasso latch later latex latte
    laugh layer leach leafy leaky learn lease leash least leave ledge legal
    lemon level lever light lilac limbo limit linen liner lingo lipid liter
    lithe liver llama loath lobby local lodge lofty logic loose lorry loser
    lotus lousy loyal lucid lucky lumpy lunar lunch lunge lurch lyric macaw
    macro madam magic magma maize major maker mango mania manor maple march
    marsh mason match maybe mayor meant medal media melon mercy merge merit
    merry messy metal meter metro might mimic mince miner minor minus mirth
    mixed model moist molar money month moody moral morph mossy motel motor
    mound mount mourn mouse mouth moved mover mucus muddy muffin mummy mural
    murky music musty naive naked named nanny nasal nasty naval navel needy
    neigh nerdy nerve never newer newly niche niece night ninja ninth noble
    nobly noise noisy nomad north notch noted novel nudge nurse nylon oasis
    occur ocean offer often olive omega onion onset opera opine optic orbit
    order organ other otter ought ounce outer owing owner oxide ozone paced
    paddy pagan paint panda panel panic paper parka parry party pasta paste
    patch patio pause paved peach pearl pedal peers penal penny perch peril
    petal petty phase phone photo piano picky piece piety piggy pilot pinch
    pitch pivot pixel pizza place plaid plain plane plank plant plate plaza
    plead pleat plied pluck plumb plume plush poach poems point poise poker
    polar polio polyp poppy porch pouch pound power prank prawn press price
    pride prime print prior prism privy prize probe prone proof props proud
    prove prowl proxy prune psalm pulse punch pupil puppy purge purse pushy
    quail quark queen query quest queue quick quiet quill quilt quota quote
    rabid radar radio rainy raise rally ramen ranch range rapid ratio raven
    razor reach react ready realm rebel rebus recap refer regal reign relax
    relay relic remit renal renew repay reply reset resin retry retro reuse
    revel rhino rhyme rider ridge rifle right rigid rinse ripen risky rival
    river roast robin robot rocky rogue roman roost rotor rouge rough round
    route rover royal ruddy rugby ruler rumor rural rusty saber sadly safer
    saint salad salon salsa salty salvo sandy santa satin sauce sauna saved
    savor savvy scald scale scalp scant scarf scare scary scene scent scoff
    scold scoop scope score scout scrap screw scrub scuba sedan seize sense
    serum serve seven sever shade shady shaft shake shaky shale shall shame
    shape share shark sharp shave shawl shear sheep sheet shelf shell shift
    shine shiny shire shirt shock shone shore short shout shove shown shrub
    shrug shush shyly siege sieve sight sigma silky silly since sinew siren
    sixty skate skiff skill skirt skull slack slain slang slant slash slate
    slave sleek sleep sleet slept slice slick slide slime sling slope sloth
    slump small smart smash smear smell smelt smile smirk smite smoke smoky
    snack snail snake snaky snare snarl sneak sneer snide sniff snipe snoop
    snore snort snout snowy snuck soapy sober solar solid solve sonic sorry
    sound south space spade spare spark spasm spawn speak spear speck speed
    spell spend spent sperm spice spicy spied spike spill spine spiny spire
    spite splat split spoil spoke spoof spook spool spoon sport spout spray
    spree sprig spurt squad squat squid stack staff stage staid stain stair
    stake stale stalk stall stamp stand stank stare stark start stash state
    stave stead steak steal steam steed steel steep steer stein stern stick
    stiff still stilt sting stink stint stock stoic stoke stole stomp stone
    stony stood stool stoop store stork storm story stout stove strap straw
    stray strip strut stuck study stuff stump stung stunk stunt style suave
    sugar suite sulky sunny super surge surly sushi swamp swarm swear sweat
    sweep sweet swell swept swift swing swirl swish swoop sword sworn syrup
    table taboo tacit tacky taffy tally talon tamer tango tangy taper tardy
    tarot taste tasty tatty taunt tawny teach tease teddy teeth tempo tenor
    tense tenth tepid terse testy thank theft their theme there these thick
    thief thigh thing think third thorn those three threw throb throw thrum
    thumb thump tiara tibia tidal tiger tight tiled timer timid tipsy tired
    titan title toast today token tonal tonic tooth topaz topic torch total
    totem touch tough tower toxic trace track tract trade trail train trait
    tramp trash tread treat trend trial tribe trick tried tries tripe trite
    troll troop trope trout truce truck truly trump trunk trust truth tulip
    tumor tunic turbo tutor twang tweak tweed tweet twice twine twirl twist
    typed ultra umbra uncle uncut under undue unfit union unite unity unlit
    unmet until upset urban urged usage usher usual utter vague valid valor
    value valve vapid vapor vault vegan venom venue verge verse verso vexed
    video vigil vigor villa vinyl viola viper viral virus visit visor vista
    vital vivid vixen vocal vodka vogue voice voter vouch vowel wafer wager
    wagon waist waive waltz waned wares waste watch water waver waxen weary
    weave wedge weedy weigh weird whale wharf wheat wheel where which while
    whine whirl whisk white whole whoop whose widen wider widow width wield
    wight wiggy wimpy wince windy wiper wired wiser wispy witch witty woken
    woman women woody wooed wooly woozy words world worry worse worst worth
    would wound woven wrath wreak wreck wrest wring wrist write wrong wrote
    wrung wryly yacht yearn yeast yield young yours youth yucky yummy zebra
    zesty zippy zonal zoned
    """
    # Five-letter words that break the block above only by omission. Every one
    # of them is a real, brandable handle, so missing them would make the
    # rating under-price exactly the tier it exists to reward.
    """
    abide actor acute admit adobe adopt adore after again agent agree ahead
    aisle alarm album alert alike alive alley allow alone along aloud alpha
    altar alter amber amend among ample angel anger angle angry ankle annoy
    apart apple apply arena argue arise armor aroma array arrow aside asset
    atlas audio audit avoid awake award aware badge baker basic basil basin
    batch beach beard beast began begin begun being belly below bench berry
    birth black blade blame blank blast blaze bleak blend bless blind bliss
    block bloom blown blues blunt blush board boast bonus boost booth bound
    brace brain brake brand brass brave bread break breed brick bride brief
    bring brisk broad broke bronze brook brown brush build built bunch burnt
    burst cabin cable cache cadet camel candy canal canoe cargo carol carry
    carve catch cause cease cedar chain chair chalk charm chart chase cheap
    check cheer chess chest chief child chill china choir chord chose civil
    claim clamp clash clasp class clean clear clerk click cliff climb cling
    clock clone close cloth cloud clown coach coast cobra cocoa coral couch
    could count court cover crack craft crane crash crate crawl crazy cream
    crest crime crisp cross crowd crown crude cruel crumb crush crust curly
    curve cycle daily dairy daisy dance dated dealt debit debut decay decor
    delay delta dense depth derby devil diary digit diner dirty ditch diver
    dizzy dodge doing donor doubt dough dozen draft drain drama drank drawn
    dread dream dress dried drift drill drink drive droid drone drove drown
    drunk dryer dwell eager eagle early earth easel eaten ebony edict eight
    elbow elder elect elite email ember empty ended enemy enjoy enter entry
    equal equip erase error essay ether ethic event every exact excel exile
    exist extra fable faced faint fairy faith false famed fancy fatal fault
    favor feast fence ferry fetch fever fiber field fiery fifth fight final
    finch finer fired first flame flash fleet flesh flint float flock flood
    floor flour flown fluid flush flute focal focus foggy force forge forth
    forty forum found frame frank fraud fresh fried front frost frown fruit
    fudge fully funny furry fuzzy gauge gecko genre ghost giant given giver
    glade gland glare glass gleam glide globe gloom glory gloss glove gnome
    going goods goose gorge grace grade grain grand grant grape graph grasp
    grass grave gravy graze great green greet grief grill grind groan groom
    gross group grove growl grown guard guess guest guide guild guilt gully
    gusto habit hairy handy happy harsh haste hatch haunt haven havoc hazel
    heart heavy hedge hefty hello hence herbs heron hilly hinge hippo hobby
    hoist holly honey honor horde horse hotel hound house hover human humid
    humor hurry husky hydro hyena ideal image imply index inept infer inlet
    inner input irate irony issue ivory jaunt jelly jewel jiffy joint jolly
    joust judge juice juicy jumbo juror kayak kebab khaki kinky kiosk kitty
    kneel knack knelt knife knock knoll known koala label labor laden ladle
    lager lance lapse large larva laser lasso latch later latex latte laugh
    layer leach leafy leaky learn lease leash least leave ledge legal lemon
    level lever light lilac limbo limit linen liner lingo lipid liter lithe
    liver llama loath lobby local lodge lofty logic loose lorry loser lotus
    lousy loyal lucid lucky lumpy lunar lunch lunge lurch lyric macaw macro
    madam magic magma maize major maker mango mania manor maple march marsh
    mason match maybe mayor meant medal media melon mercy merge merit merry
    messy metal meter metro might mimic mince miner minor minus mirth mixed
    model moist molar money month moody moral morph mossy motel motor mound
    mount mourn mouse mouth moved mover mucus muddy muffin mummy mural murky
    music musty naive naked named nanny nasal nasty naval navel needy neigh
    nerdy nerve never newer newly niche niece night ninja ninth noble nobly
    noise noisy nomad north notch noted novel nudge nurse nylon oasis occur
    ocean offer often olive omega onion onset opera opine optic orbit order
    organ other otter ought ounce outer owing owner oxide ozone paced paddy
    pagan paint panda panel panic paper parka parry party pasta paste patch
    patio pause paved peach pearl pedal peers penal penny perch peril petal
    petty phase phone photo piano picky piece piety piggy pilot pinch pitch
    pivot pixel pizza place plaid plain plane plank plant plate plaza plead
    pleat plied pluck plumb plume plush poach poems point poise poker polar
    polio polyp poppy porch pouch pound power prank prawn press price pride
    prime print prior prism privy prize probe prone proof props proud prove
    prowl proxy prune psalm pulse punch pupil puppy purge purse pushy quail
    quark queen query quest queue quick quiet quill quilt quota quote rabid
    radar radio rainy raise rally ramen ranch range rapid ratio raven razor
    reach react ready realm rebel rebus recap refer regal reign relax relay
    relic remit renal renew repay reply reset resin retry retro reuse revel
    rhino rhyme rider ridge rifle right rigid rinse ripen risky rival river
    roast robin robot rocky rogue roman roost rotor rouge rough round route
    rover royal ruddy rugby ruler rumor rural rusty saber sadly safer saint
    salad salon salsa salty salvo sandy santa satin sauce sauna saved savor
    savvy scald scale scalp scant scarf scare scary scene scent scoff scold
    scoop scope score scout scrap screw scrub scuba sedan seize sense serum
    serve seven sever shade shady shaft shake shaky shale shall shame shape
    share shark sharp shave shawl shear sheep sheet shelf shell shift shine
    shiny shire shirt shock shone shore short shout shove shown shrub shrug
    shush shyly siege sieve sight sigma silky silly since sinew siren sixty
    skate skiff skill skirt skull slack slain slang slant slash slate slave
    sleek sleep sleet slept slice slick slide slime sling slope sloth slump
    small smart smash smear smell smelt smile smirk smite smoke smoky snack
    snail snake snaky snare snarl sneak sneer snide sniff snipe snoop snore
    snort snout snowy snuck soapy sober solar solid solve sonic sorry sound
    south space spade spare spark spasm spawn speak spear speck speed spell
    spend spent sperm spice spicy spied spike spill spine spiny spire spite
    splat split spoil spoke spoof spook spool spoon sport spout spray spree
    sprig spurt squad squat squid stack staff stage staid stain stair stake
    stale stalk stall stamp stand stank stare stark start stash state stave
    stead steak steal steam steed steel steep stein stern stick stiff still
    stilt sting stink stint stock stoic stoke stole stomp stone stony stood
    stool stoop store stork storm story stout stove strap straw stray strip
    strut stuck study stuff stump stung stunk stunt style suave sugar suite
    sulky sunny super surge surly sushi swamp swarm swear sweat sweep sweet
    swell swept swift swing swirl swish swoop sword sworn syrup table taboo
    tacit tacky taffy tally talon tamer tango tangy taper tardy tarot taste
    tasty taunt tawny teach tease teddy teeth tempo tenor tense tenth tepid
    terse testy thank theft their theme there these thick thief thigh thing
    think third thorn those three threw throb throw thrum thumb thump tiara
    tibia tidal tiger tight tiled timer timid tipsy tired titan title toast
    today token tonal tonic tooth topaz topic torch total totem touch tough
    tower toxic trace track tract trade trail train trait tramp trash tread
    treat trend trial tribe trick tried tries tripe trite troll troop trope
    trout truce truck truly trump trunk trust truth tulip tumor tunic turbo
    tutor twang tweak tweed tweet twice twine twirl twist typed ultra umbra
    uncle uncut under undue unfit union unite unity unlit unmet until upset
    urban urged usage usher usual utter vague valid valor value valve vapid
    vapor vault vegan venom venue verge verse verso vexed video vigil vigor
    villa vinyl viola viper viral virus visit visor vista vital vivid vixen
    vocal vodka vogue voice voter vouch vowel wafer wager wagon waist waive
    waltz waned wares waste watch water waver waxen weary weave wedge weedy
    weigh weird whale wharf wheat wheel where which while whine whirl whisk
    white whole whoop whose widen wider widow width wield wiggy wimpy wince
    windy wiper wired wiser wispy witch witty woken woman women woody wooed
    wooly woozy words world worry worse worst worth would wound woven wrath
    wreak wreck wrest wring wrist write wrong wrote wrung wryly yacht yearn
    yeast yield young yours youth yucky yummy zebra zesty zippy zonal zoned
    """ + """
    love shop free call live plus gold star game play tech bank cash gate
    host link mail name page pass safe sale team time wear wish word work
    zone best blue city club cool deal deep easy fast food good help home
    king life like lite make mark mine mode move must near next nice note
    only open park pick plan post pure real rent rich ride ring rose rule
    save seek sell send show sign site size soft some soon sort stay step
    stop sure talk task test text than that them then they this trip turn
    type unit user vast very view wait walk wall warm wave week well west
    wide wife wild will wind wine wise with wood yard year your zero
    """
    ).split()
)

# Deeper tiers for the lengths the wizard actually offers. The original list was
# almost entirely five-letter words (1429 of 1563), so a search at length 6 had
# FOUR candidates to try and gave up immediately with "checked 1 name - taken".
# These blocks are real, brandable English words too, and they make every offered
# length deep enough to actually search.
_WORD_SET = frozenset(
    set(_WORD_SET)
    | set(
        (
            """
    able acid aged also area army away baby back ball band bank base bath beam bean bear beat
    been beer bell belt best bird bite blue boat body bold bolt bomb bond bone book boot born
    boss both bowl bulk burn bush busy cake call calm came camp card care case cash cast cell
    chat chef chip city club coal coat code cold come cook cool copy core cost crew crop cure
    dark data date dawn days dead deaf deal dean dear debt deck deep deer demo deny desk dial
    diet disc disk dock does done door dose dove down draw drew drop drug drum dual dues dust
    duty each earn ease east easy echo edge edit eggs else ends epic even ever exam exit face
    fact fade fail fair fall fame farm fast fate fear feed feel feet fell felt file fill film
    find fine fire firm fish five flag flat flee flew flex flip flow foam fold folk font food
    foot ford form fort foul four free frog from fuel full fund gain game gate gave gear gene
    gift girl give glad glow goal goes gold golf gone good gulf hair half hall hand hang hard
    harm hash hate have head heal heap hear heat held hell help herb hero high hill hint hire
    hold hole holy home hood hook hope horn host hour huge hunt hurt icon idea inch into iron
    item jack jazz join july jump june jury just keen keep kept kick kill kind king kiss knee
    knew know lace lack lady laid lake lamb lamp land lane last late lawn lead leaf lean leap
    left lend lens less life lift like limb lime line link lion list live load loan lock logo
    long look loop lord lose loss lots loud love luck lump lung made mail main make male mall
    many maps mark mask mass mate math meat meet mega melt menu mere mesh mild mile milk mill
    mind mine mint miss mode mood moon more moss most move much must myth nail name navy near
    neat neck need nest news next nice nine node none noon norm nose note noun oath obey odds
    okay omit once ones only onto open oral oven over pace pack page paid pain pair pale palm
    park part pass past path peak pear peer pens pick pier pile pine pink pipe plan play plot
    plug plus poem poet pole poll pond pool poor pope port pose post pour pray prep prey prom
    prop pull pump punt pure push quit quiz race rack rail rain rank rare rate read real ream
    rear reed reef rent rest rice rich ride ring rise risk road roam roar robe rock role roll
    roof room root rope rose rows rule rush rust sack safe said sail sale salt same sand save
    scan scar seal seat seed seek seem seen self sell send sent sets shed ship shoe shop shot
    show shut sick side sift sign silk sing sink site size skin skip slam slim slip slot slow
    snap snow soap sock soft soil sold sole solo some song soon sort soul soup spot spun star
    stay stem step stir stop stub such suit sure swim take tale talk tall tank tape task team
    tear tech tell tend tent term test text than that them then they thin this thus tide tidy
    tier tile till tilt time tiny tips tire toll tone took tool tops tore torn tour town trap
    tray tree trim trip true tube tune turn twin type unit upon urge used user uses vast very
    vest view void vote wait wake walk wall want ward warm warn wash wave ways weak wear week
    well went were west what when whom wide wife wild will wind wine wing wire wise wish with
    wolf wood wool word wore work worm worn wrap yard yarn yeah year yell yoga your zero zinc
    zone zoom
            """
            + """
    absorb accent accept access accord across adjust admire advent affair afford agenda agreed
    almost always amount anchor animal annual answer anyone appeal appear arcade arctic around
    arrive artist ascend aspect assign assist assume assure atomic attack attend august author
    autumn avatar avenue backed ballot bamboo banner barrel basket batter beacon beauty became
    become before behalf behind belief belong better beyond bidder binary bishop bitter blazer
    bodily boldly bolted bonnet border boring borrow bother bottle bottom bounce bounty breeze
    bridge bright broken broker bubble bucket budget buffet bundle bunker burden bureau burger
    burial bushel butler butter button buyout camera campus cancel candle cannon canopy canvas
    canyon carbon career carpet cartel casino castle casual caught caveat celery cellar cement
    census center chance change chapel charge cherry chorus chosen chunky cinema circle circus
    clever client climax closed closet coffee cogent collar colony column combat comedy coming
    commit common cotton couple course cousin covert cowboy cradle create credit crisis critic
    custom damage danger dealer debate decade decent decide defeat defend define degree delete
    demand denial depend depict deploy desert design desire detail detect device devote dialog
    diesel differ dinner direct disarm divide divine doctor domain donate double dragon drawer
    driver during earned easter eating editor effect effort either eleven embark emblem embody
    emerge employ enable ending energy engage engine enough enrich ensure entire entity equity
    escape estate ethnic evolve exceed except excess excite excuse exempt exhale exotic expand
    expect expert expire expose extend extent fabric facade facing factor falcon family famous
    farmer fathom fellow female fierce figure filter finale finder finish firmly fiscal flavor
    flight florid flower follow forbid forest forget formal format former foster fought fourth
    france freeze french frozen fulfil galaxy gallon gamble garage garden gather gender genius
    gentle gifted ginger giving glance global glossy golden gospel gotten govern graces grades
    grains grange grants grated gravel greasy greedy grocer growth guilty gutter hamlet handle
    happen harbor hardly hassle hatter hazard headed health hearty hectic helium helmet herbal
    hidden highly hiring holder hollow honest horror hostel hourly humble hunger hunter hurdle
    hustle hybrid ignite ignore immune impact import impose income indeed indoor induce infant
    inform inject injure injury inland insect inside insist insult intact intend intent invent
    invest invite island itself jacket jargon jersey jockey joyous judged junior jurist keeper
    kernel kettle kidney killer kindly knight lively living locate locker logged longer looked
    lowest lucent luxury mainly making manage manner mantle mapper marble margin marine marker
    market marvel master matrix matter mature meadow medium member memory mental mentor merger
    method middle mildly mining minute mirror misery modify moment monkey mostly mother motion
    motive murmur museum mutual myself namely native nature nearby nearly needle nephew nickel
    nimble nobody nodded normal notice notion novice number object oblige obtain occupy office
    offset online option oracle orange orchid origin outfit outing output outset owning oxygen
    packer paddle palace pantry parade parcel parent parish parked parser partly pastel pastor
    patent patrol patron pebble pencil people pepper period permit person phrase picnic pierce
    pillar pillow pirate pistol piston planet plasma player please plenty plunge poetry policy
    polish poorly portal porter posted potato powder praise prayer prefer pretty prince prison
    profit prompt proper proven public puppet purple pursue puzzle python quarry rabbit racial
    racing radius raffle raider random ranger rarely rather rating ration reader really reason
    recall recent record reduce reform refund refuse regard regime region regret reject relate
    relief remain remark remedy remind remote remove repair repeat report rescue resign resist
    resort result retain retire reveal review revive reward rhythm ribbon richer ripple rising
    ritual rivals robust rocket roster router rubber rubble rugged runner runoff runway rustic
    safely safety salmon sample sanity satire saving saying scaler scarce scared scenic scheme
    school scorer script scruff search season second secret sector secure seldom select seller
    senate senior sensor sentry sequel series sermon server settle severe sewing shield signal
    silent silver simple simply singer single sister sketch skinny slight slogan smooth soccer
    social socket softly solely solved sonata sooner sorrow sorted sought source soviet spaced
    speaks spider spiral spirit spoken sponge spouse sprint sprout square squash squeak stable
    staple starch statue status steady stench stereo sticky stitch stocks stolen strain streak
    stream street stress strict stride strike string strive strong studio sturdy submit subtle
    suburb sudden suffer suited summer summit sunset superb supper supply surely survey switch
    symbol syntax system tackle tailor talent tandem tangle tanker target tariff tavern temple
    tenant tender tennis tenure terror theory thirst thirty though thread threat thrive throat
    throne thrown ticket tidbit timber timely tinker tissue toffee toilet tomato tongue toward
    tragic trails trance travel treaty tremor trench trendy tribal tricky trifle triple trophy
    trough truant tumble tunnel turret twelve twenty typing umpire unable unfair unfold unique
    united unless unlock unpaid unrest unsafe unseen unsure upbeat update uphill uphold upload
    upward urgent usable useful vacant vacuum valley valued vandal vanity varied vassal vector
    vendor veneer verbal verify versus vessel viable victim victor viewer violet virtue vision
    visual voodoo votive voyage waffle wander warmth warned wealth weapon weekly weight willow
    window winner winter wisdom wonder wooden worker worthy writer yellow zombie zoning
            """
            + """
    abandon ability absence academy account achieve acquire address advance adverse advised
    aerosol against airline airport alcohol algebra allergy already amateur amazing amended
    analyse ancient another anxiety apparel applied approve archive arrange arrival arsenal
    article artisan ashamed asphalt assault attempt auction augment authors average aviator
    awkward balance balcony balloon banking baptism bargain barrier bashful battery bearing
    beating because bedroom beloved benefit besides bicycle billion biology bizarre blanket
    blogger blossom bolster bonding bonfire booklet boolean borough boulder bounded browser
    buckled builder cabinet calcium caliber calling capable capital captain caption captive
    caramel cardiac careers careful cargoes carrier cascade casting catalog catcher caterer
    caution cavalry ceiling central century ceramic certain chamber channel chapter charity
    charmer charter chassis checked chicken chiefly chimney chronic circuit clarity classic
    cleaner cleared clearly climate clipart closure clothes cluster coating coconut collect
    college combine comfort command comment commute compact company compare compass compete
    compile complex compute concept concern concert conduct confirm connect consent console
    contact contain content contest context control convert cordial cornell correct corrupt
    costume cottage council counsel counter country couplet courage courtly covered cracked
    crafted cranium creator credits cricket crimson crinkle crooner crossed cruiser crumble
    cryptic crystal cuisine culprit culture cunning curious current curtain cushion custody
    customs cyclone cynical darkest dealing debated declare decline decorum default defeats
    defence deficit defined delayed delight deliver deluded demands density deposit deprive
    descent deserve designs desktop despite destiny details develop deviate devoted diagram
    dialect diamond digital dignity dilated dilemma diploma dipping directs discern discuss
    disease disgust dismiss display dispute distant distort disturb diverse divided divorce
    dockers dodging dolphin domaine domains donated doorway dossier drafted dragons drained
    drastic drawing dreaded dreamer dressed drifted drivers drought drummer durable dynamic
    eagerly earlier earnest eastern economy edition editors educate effects efforts elderly
    elegant element elevate embrace eminent emotion emperor empires enabled enacted endless
    endorse enemies engaged enhance enlarge ensures entered entitle entries episode equator
    erected errands escapes essence eternal ethical evasion evening evident evolved exactly
    examine example exceeds excerpt excited exclude exhaust exhibit exotics expands expense
    experts expires explore exports exposed extreme facades faction factory faculty failure
    falsely fantasy fashion fatally fathers fatigue faulted favours feature federal feeding
    feeling ferrous fertile festive fiction fifteen fighter figures filling filters finally
    finance finding finland firearm fitness fixture fleeing floated florist flowers flushed
    focused folding footage forbade forcing foreign forever forfeit forgive formula fortune
    forward fossils founder fragile framing frankly freedom freight friends funnels furnace
    further gadgets gallery gallows gambler garment gateway gazette general generic genetic
    genuine geology getters glances glasses glimpse glorify glowing goggles grammar graphic
    gravity greater greatly grilled grocery groomed grouped growing grownup guarded guitars
    habitat halting hamster handful hanging happens happily harbour harmony harness harvest
    hastily hatched healthy hearing heavens heavily hectare herself hexagon highest highway
    himself holiday hollows homered honesty honored hormone hostage hosting however hundred
    hunters hurried hurting husband hygiene illegal illness imagery imagine immense imports
    imposed imprint improve impulse inbound incline include indices induced indulge infancy
    initial injects injured inmates inquiry insects insider insight inspire install instant
    instead insulin insured integer intends interim invalid invents inverse invests involve
    isolate issuing iterate jackets jamming january jealous joining journey judging juggler
    jumpers justice justify keeping kennels kernels keyhole keyword kingdom kitchen knowing
    lantern laptops largely lasting lateral laughed lawsuit lawyers layered leading leaflet
    leagues leakage learned leather leaving lecture legally legions leisure lessons letters
    liberal liberty library licence lighter limited lineage linkage liquids listing literal
    lithium loading loathed located logical longest lottery loudest loyalty machine magenta
    magical magnets mailbox mailing malaria mandate manhood mansion manuals margins markets
    married massive masters matched matters maximum meaning measure medical mediums meeting
    members mention message methods metrics migrant mileage million mineral minimal minimum
    minutes mirrors missile mission mistake mixture mobiles modular modules moments monitor
    monthly morally morning mothers mounted mundane murders mutated mystery nations natives
    natural nearest neglect neither nervous network neutral newborn nigeria nominal notable
    notably nothing noticed notions nourish novelty nuclear nucleus numbers nursing nurture
    obscure observe obtains obvious offered officer offline offsets ongoing opening operate
    opinion optical optimal options ordered organic origins outcome outdoor outlets outline
    outlook outputs overall oversee oxidise package packets padding palaces paradox parcels
    parents parking partial parties partner passage passing passion passive pathway payload
    payment peptide percent perfect perhaps periods permits persons phantom phoenix phoneme
    physics pigeons pilgrim pillars pioneer pitched pivotal placebo planets planned planted
    plastic plateau playing pledged plotted pockets podcast pointed pointer poisons polling
    polygon popular portals portion portray posture pottery poverty powered prairie prayers
    precede precise predict preface premier premise premium prepare pretend prevail prevent
    preview pricing primary printer privacy private problem proceed process produce product
    profile profits program project promise promote pronoun propose protect protein protest
    proudly proverb provide provoke prudent publish puppies pursued puzzles pyramid qualify
    quantum quarrel quarter queries quietly quoting radiant radical railway rainbow raising
    rampant ranking rapidly rapport ratings reached reactor readers readily reality realize
    reasons rebuilt recalls receipt receive recover recruit rectify reddish reduced reflect
    reforms refresh regions regular related relaxed release remains remarks removal renamed
    replace replied reports request require rescued reserve resided resolve resorts respect
    restore results resumed retired revenue reverse revived rewrite rhubarb richest rightly
    ringing rivalry roadmap roasted robotic rockets romance roughly rounded routine royalty
    rubbing rubbish running runtime rushing sadness salvage sandbox savings scandal scanner
    scenery sceptic scholar science scooter scoping scoring scraped scratch screams screens
    scripts seafood sealing seasons seconds secrecy secrets section sectors secured seeking
    segment seismic senator sending seniors sensing serials serious sermons serving setting
    settled seventh several shadows sharply shelter sheriff shields shifted shining shipped
    shortly showers shrines sibling signals silence similar simpler sincere sitting sixteen
    skilled skipped slammed slavery sleeves slender smoking society sockets softest solidly
    solving soonest sorrows sources sparked speaker special species specify spectra spelled
    spheres spiders spinach spirits sponsor spotted sprayed springs squeeze stacked staging
    stained stamina stamped standby staring started station statues staying stellar stomach
    stopped storage stories stormed streams streets stretch strikes strings studies studios
    stylish subject submits subsidy succeed success suppose supreme surface surgeon surplus
    surveys survive suspect suspend sustain sweater symbols symptom synergy systems tactics
    talents talking tangent targets tariffs teacher tearing teenage telecom telling tempest
    tenants tending tenfold tension terrain testify textile thanked theatre therapy thereby
    thicker thieves thinker thirsty thought threads threats through thunder thyroid tickets
    tighten tissues tobacco tonight toolbox topping torches torrent torture totally touched
    touring tourism tourist towards tracker traders tragedy trailer trained trainee trainer
    transit travels treason treated tremble tribute trickle trimmed triumph trolley trumpet
    trustee tuition tunnels turbine turmoil turnout twelfth typings unaware unclear uncover
    undergo unequal unhappy unified uniform unnamed unusual updated upgrade uploads upright
    upwards urgency ushered utility vacancy vaccine vaguely valiant valleys vampire various
    varnish vectors vendors ventral venture verdict vessels veteran victims victory viewers
    vintage violent virtual viruses visible visions visitor vitamin voltage volumes waiting
    walking wallets wanting warfare warming washing watched wealthy weapons wearing weather
    weaving wedding weekend welfare western whereas whereby whether widgets willing windows
    winners winning winters witness wonders workers working worried worries writers writing
    written yielded younger zealous
            """
        ).split()
    )
)

# Suffixes that turn a base word into a real, sellable handle ("shop", "app").
BRAND_SUFFIXES = ("hq", "app", "pro", "lab", "hub", "shop", "store", "team", "x", "io")
# Prefixes that do the same at the front ("getshop", "mydev").
BRAND_PREFIXES = ("the", "get", "use", "my", "go", "hey", "mr")


@dataclass
class Rating:
    """A score plus the breakdown that produced it.

    ``parts`` keys are exactly the keys of :data:`PART_MAX`, so a breakdown can
    never be rendered against the wrong ceiling. ``name_length`` is kept so the
    score can be read *relative* to what a name of that length can possibly
    reach - the honest way to say "this is as good as a 10-character name gets".
    """

    total: int
    parts: dict[str, int] = field(default_factory=dict)
    name_length: int = 0

    def explain(self) -> str:
        return " ".join(f"{key}={value}" for key, value in self.parts.items())

    @property
    def grade(self) -> str:
        """The band a user acts on: S, A, B, C or D."""
        return grade_for(self.total)

    @property
    def ceiling(self) -> int:
        """The highest score any name of this length could reach."""
        return best_possible(self.name_length)

    @property
    def fill(self) -> int:
        """Share of the length's ceiling this name actually reached, 0-100."""
        ceiling = self.ceiling
        return max(0, min(100, round(self.total / ceiling * 100))) if ceiling else 0

    @property
    def strength(self) -> str | None:
        """The criterion that carries the name - its highest-scoring one.

        Only criteria that reached three quarters of their own maximum are
        eligible, so a mediocre name is never given invented praise; ``None``
        means nothing stands out, and the UI says that instead of flattering.
        Ties are broken in favour of the more valuable criterion (meaning over
        length over sound), which is also the order they are shown in.
        """
        order = ("word", "length", "spelling", "digits", "separators")
        best: tuple[str, int] | None = None
        for key in order:
            value = self.parts.get(key)
            if value is None or not PART_MAX.get(key):
                continue
            if value / PART_MAX[key] < 0.75:
                continue
            if best is None or value > best[1]:
                best = (key, value)
        return best[0] if best else None

    @property
    def weakness(self) -> str | None:
        """The criterion that cost the most points - what actually caps the score."""
        lost = [
            (key, PART_MAX[key] - value)
            for key, value in self.parts.items()
            if key in PART_MAX
        ]
        if not lost:
            return None
        key, loss = max(lost, key=lambda pair: pair[1])
        return key if loss >= 5 else None


def grade_for(total: int) -> str:
    """Map a 0-100 score onto its grade letter."""
    for letter, floor in GRADES:
        if total >= floor:
            return letter
    return GRADE_LETTERS[-1]


def best_possible(length: int) -> int:
    """Highest score a name of this length can reach.

    Length is fixed by the name itself, so the theoretical best is this length's
    scarcity points plus a perfect score on the four criteria that are still
    free to be perfect. Used to express a rating as a share of what the user's
    own length filter allows.
    """
    if length <= 0:
        return TOTAL_MAX
    return _length_points(length) + (TOTAL_MAX - PART_MAX["length"])


def _length_points(length: int) -> int:
    if length <= 4:
        return _LENGTH_CURVE[4]
    return _LENGTH_CURVE.get(length, _LENGTH_FLOOR)


def _letters_only(name: str) -> str:
    return "".join(ch for ch in name if ch.isalpha())


def vowel_ratio(name: str) -> float:
    """Share of vowels among the letters. Zero when there are none."""
    letters = _letters_only(name)
    if not letters:
        return 0.0
    return sum(1 for ch in letters if ch in VOWELS) / len(letters)


def is_real_word(name: str) -> bool:
    """True when the name (a-z only) is a real, brandable English word."""
    return name.isalpha() and name.lower() in _WORD_SET


def _sounds_clean(name: str) -> bool:
    """Could a human say this out loud without stumbling?

    Deliberately independent of Telegram's minimum length: the question is about
    the string, not about whether Telegram would accept it. A vowel desert and a
    run of three *real* consonants are the two things that break a handle in
    speech. Digraphs are collapsed first, because ``ch``, ``sh`` and ``th`` are
    one sound each - counting ``chn`` in "technology" as three consonants would
    punish the most ordinary English words in the dictionary.
    """
    letters = _letters_only(name)
    if not letters:
        return False
    if not any(ch in VOWELS for ch in letters):
        return False
    for digraph in CONSONANT_DIGRAPHS:
        letters = letters.replace(digraph, "#")
    return not re.search(r"[^aeiouy#]{3,}", letters)


def is_pronounceable(name: str) -> bool:
    """True when the name is both sayable and long enough for Telegram."""
    return len(_letters_only(name)) >= MIN_LENGTH and _sounds_clean(name)


def meaning_score(name: str) -> int:
    """How much the name *means*, in three honest tiers.

    ``25`` a real dictionary word - the only tier that can serve as a brand
    outright. ``20`` two real words joined (``homeshop``). ``17`` a real word
    plus a brand affix (``cranehq``, ``getshop``). ``0`` anything else: a
    coinage can be pretty, but it does not mean anything, and saying otherwise
    would be the exact dishonesty this rubric exists to avoid.
    """
    if not name.isalpha():
        return 0
    if name in _WORD_SET:
        return PART_MAX["word"]

    for cut in range(3, len(name) - 2):
        if name[:cut] in _WORD_SET and name[cut:] in _WORD_SET:
            return 20

    for suffix in BRAND_SUFFIXES:
        stem = name[: -len(suffix)] if name.endswith(suffix) else ""
        if len(stem) >= 3 and stem in _WORD_SET:
            return 17

    for prefix in BRAND_PREFIXES:
        stem = name[len(prefix):] if name.startswith(prefix) else ""
        if len(stem) >= 3 and stem in _WORD_SET:
            return 17

    return 0


def sound_score(name: str) -> int:
    """Phonetics: sayability, spelling, and absence of visual noise."""
    score = PART_MAX["spelling"]
    if not _sounds_clean(name):
        score -= 9
    if re.search(r"(.)\1\1", name):
        score -= 4
    if re.search(r"(.)\1", name):
        score -= 2
    if any(ch in UGLY_CLUSTERS for ch in name):
        score -= 3
    if _letters_only(name):
        ratio = vowel_ratio(name)
        if ratio < 0.2 or ratio > 0.7:
            score -= 3
    if any(digraph in name for digraph in SILENT_DIGRAPHS):
        score -= 2
    return max(0, score)


def digits_score(name: str) -> int:
    """Digits by count *and* position.

    A single trailing digit (``shop7``) is a common, tolerated pattern and keeps
    most of the points; a leading one is a different, worse thing; a run of them
    destroys the handle. The old flat ``15 - 8 * count`` could not tell those
    apart and sent both ``shop2`` and ``shop7777`` to zero.
    """
    positions = [index for index, ch in enumerate(name) if ch.isdigit()]
    if not positions:
        return PART_MAX["digits"]
    if len(positions) == 1:
        return 11 if positions[0] == len(name) - 1 else 7
    if len(positions) == 2:
        return 4
    return 0


def symbols_score(name: str) -> int:
    """Underscores and other punctuation, again by position."""
    positions = [index for index, ch in enumerate(name) if not ch.isalnum()]
    if not positions:
        return PART_MAX["separators"]
    if len(positions) == 1:
        interior = 0 < positions[0] < len(name) - 1
        return 6 if interior else 4
    if len(positions) == 2:
        return 2
    return 0


def rate(username: str) -> Rating:
    """Score a username from 0 to 100 on our own published rubric.

    Deterministic and purely string-based: the same name always scores the
    same, and the breakdown is shown to the user so the number is auditable
    rather than mysterious.
    """
    name = username.strip().lower()
    if not name:
        return Rating(0, dict.fromkeys(PART_MAX, 0), 0)

    parts = {
        "length": _length_points(len(name)),
        "word": meaning_score(name),
        "spelling": sound_score(name),
        "digits": digits_score(name),
        "separators": symbols_score(name),
    }
    return Rating(sum(parts.values()), parts, len(name))


# --------------------------------------------------------------------- premium
# Five boolean criteria, each one a property a buyer on Fragment pays for.
# Shown as N/5 with a tick or a cross per row - not a 0-100 average, because a
# free-name "score 67/100" hides which property the user is paying for. With five
# flags the verdict is auditable: 5/5 means the name clears every quality gate,
# 0/5 means it cannot be sold on those five grounds no matter how "average" it is.
@dataclass
class Premium:
    """Five boolean flags. :attr:`total` is N/5, not a percentage."""

    no_digits: bool
    no_separators: bool
    collectible: bool
    readable: bool
    dictionary: bool

    @property
    def total(self) -> int:
        return sum(
            int(getattr(self, key))
            for key in (
                "no_digits",
                "no_separators",
                "collectible",
                "readable",
                "dictionary",
            )
        )


# Length window that overlaps Telegram's "collectible-class" tier. Telegram
# allows collectible handles of 4-5 chars; we extend to 7 because six/seven-
# letter premium handles are still priced well on Fragment, while anything
# past seven is too easy to find free to be worth paying for.
_COLLECTIBLE_MIN = 4
_COLLECTIBLE_MAX = 7


def premium_rating(username: str) -> Premium:
    """Run the five booleans once, on the normalised lowercase name."""
    name = (username or "").strip().lower()
    return Premium(
        no_digits=not any(ch.isdigit() for ch in name),
        no_separators=not any(ch in "-_" for ch in name),
        collectible=_COLLECTIBLE_MIN <= len(name) <= _COLLECTIBLE_MAX,
        readable=sound_score(name) >= PART_MAX["spelling"],
        dictionary=is_real_word(name),
    )


# The best score a purely cosmetic name can reach at each length, i.e. the
# ceiling when the name is NOT a real word (which is the case for almost every
# long handle - no 10-letter dictionary word is available). Used to make the
# user's rating filter length-aware, so "70+" means "the best that length can
# do" rather than "impossible, show nothing".
def max_score_for_length(length: int) -> int:
    """Highest overall score a clean, non-word name of this length can reach."""
    probe = "b" * max(1, length)
    return rate(probe).total


def quality_threshold(length: int | None, min_score: int) -> int:
    """Translate the user's 0-100 filter into a length-aware minimum.

    A score of 70 is excellent for a 5-letter name and literally unreachable for
    a 10-letter one, because the length component alone drops from 26 to 5. The
    filter is therefore applied as a *share of what is achievable*, so raising it
    always means "better candidates", never "no candidates".
    """
    if min_score <= 0:
        return 0
    reference = length or 6
    ceiling = max_score_for_length(reference)
    if ceiling <= 0:
        return min_score
    return int(ceiling * (min_score / 100.0))


def compile_mask(mask: str) -> re.Pattern[str] | None:
    """Turn a mask into an anchored regex, or None if the mask is unusable."""
    mask = (mask or "").strip().lower()
    if not mask or not ALLOWED_MASK_RE.match(mask):
        return None

    pieces: list[str] = []
    for token in MASK_TOKEN_RE.findall(mask):
        if token == "?":
            pieces.append("[a-z]")
        elif token == "#":
            pieces.append(r"\d")
        elif token == "*":
            pieces.append("[a-z]*")
        elif token == "_":
            pieces.append("_")
        else:
            pieces.append(re.escape(token))

    body = "".join(pieces)
    # A username must still satisfy Telegram's own length rules.
    pattern = rf"^(?=.{{{MIN_LENGTH},{MAX_LENGTH}}}$){body}$"
    try:
        return re.compile(pattern)
    except re.error:
        return None


def mask_is_usable(mask: str) -> bool:
    return compile_mask(mask) is not None


def mask_to_length_hint(mask: str) -> tuple[int, int]:
    """Minimum and maximum length a mask can produce."""
    mask = (mask or "").lower()
    minimum = sum(1 for token in MASK_TOKEN_RE.findall(mask) if token in ("?", "#", "_") or token.isalpha())
    if "*" in mask:
        return minimum, MAX_LENGTH
    return minimum, minimum


def _pick_letter(rng: random.Random, previous: str | None, want_vowel: bool | None) -> str:
    pool = LETTERS
    if want_vowel is not None:
        subset = [ch for ch in LETTERS if (ch in VOWELS) == want_vowel]
        pool = "".join(subset)
    candidates = [ch for ch in pool if ch != previous]
    return rng.choice(candidates or list(pool))


def generate_from_mask(mask: str, rng: random.Random | None = None) -> str | None:
    """One random username matching the mask, biased towards readable output."""
    rng = rng or random.Random()
    mask = (mask or "").strip().lower()
    if not mask or not ALLOWED_MASK_RE.match(mask):
        return None

    out: list[str] = []
    want_vowel: bool | None = None

    for token in MASK_TOKEN_RE.findall(mask):
        if token == "_":
            out.append("_")
            want_vowel = None
        elif token == "#":
            out.append(rng.choice("0123456789"))
            want_vowel = None
        elif token == "?":
            letter = _pick_letter(rng, out[-1] if out else None, want_vowel)
            out.append(letter)
            want_vowel = letter not in VOWELS
        elif token == "*":
            # A short, readable filler run rather than a long random blob.
            count = rng.randint(1, 3)
            for _ in range(count):
                letter = _pick_letter(rng, out[-1] if out else None, want_vowel)
                out.append(letter)
                want_vowel = letter not in VOWELS
        else:
            out.append(token)
            want_vowel = token not in VOWELS

    name = "".join(out)
    if not (MIN_LENGTH <= len(name) <= MAX_LENGTH):
        return None
    if name.startswith("_") or name.endswith("_") or "__" in name:
        return None
    return name


def build_mask(
    length: int | None = None,
    allow_digits: bool = False,
    prefix: str | None = None,
    explicit: str | None = None,
) -> str:
    """Compose a mask from the wizard's knobs.

    ``prefix`` is a starting fragment the user wants to keep (e.g. ``moged``),
    the rest is filled with ``?`` and, when allowed, ``#``.
    """
    if explicit:
        return explicit.strip().lower()

    head = (prefix or "").strip().lower()
    head = "".join(ch for ch in head if ch.isalnum() or ch == "_")
    remaining = max(0, (length or 8) - len(head))
    tail = "?" * remaining
    if allow_digits and remaining:
        # Swap one slot for a digit, in a random-ish but stable position.
        position = remaining // 2
        tail = tail[:position] + "#" + tail[position + 1 :]
    return head + tail
