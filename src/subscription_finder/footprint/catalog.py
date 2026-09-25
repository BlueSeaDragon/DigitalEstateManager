"""Account types, known services and keyword rules for the digital-footprint detector.

Everything here is deterministic. A service is identified by its email sender domain
(longest matching domain suffix wins, so `aws.amazon.com` beats `amazon.com`) or, in bank
transactions, by an unambiguous brand keyword. Unknown services are typed by keyword rules;
only what stays ambiguous goes to the LLM.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..detect.paid_subscription import registrable_domain

# account_type -> what heirs may find there
ACCOUNT_TYPES: dict[str, tuple[str, ...]] = {
    "bank": ("money",),
    "investment": ("money",),
    "crypto": ("money",),
    "payment": ("money",),
    "insurance": ("money", "contract"),
    "email": ("identity", "data"),
    "password_manager": ("identity", "data"),
    "social_media": ("identity", "data"),
    "cloud_storage": ("data",),
    "developer_cloud": ("data", "contract"),
    "utility_telecom": ("contract",),
    "membership": ("contract",),
    "software": ("data",),
    "entertainment": ("data",),
    "shopping": ("data",),
    "travel": ("data",),
    "other": (),
}
# display order: money first, then identity keys, then the rest
TYPE_ORDER = {t: i for i, t in enumerate(ACCOUNT_TYPES)}

TYPE_LABELS = {
    "bank": "bank account", "investment": "investment account", "crypto": "crypto account",
    "payment": "payment account", "insurance": "insurance", "email": "email account",
    "password_manager": "password manager", "social_media": "social media account",
    "cloud_storage": "cloud storage account", "developer_cloud": "developer / cloud service account",
    "utility_telecom": "utility or telecom contract", "membership": "membership",
    "software": "software account", "entertainment": "entertainment account",
    "shopping": "shopping account", "travel": "travel account", "other": "online account",
}

# subscription service_type -> account_type (subscriptions become footprint evidence)
SERVICE_TYPE_TO_ACCOUNT = {
    "streaming": "entertainment", "music": "entertainment", "software": "software",
    "cloud": "cloud_storage", "mobile": "utility_telecom", "gym": "membership",
    "insurance": "insurance", "other": "other",
}


@dataclass(frozen=True)
class Service:
    key: str
    name: str
    account_type: str
    domains: tuple[str, ...]
    keywords: tuple[str, ...] = field(default=())  # brand words safe to match in bank descriptions


def _s(key: str, name: str, account_type: str, *domains: str, keywords: tuple[str, ...] = ()) -> Service:
    return Service(key, name, account_type, domains, keywords)


SERVICES: tuple[Service, ...] = (
    # email / identity providers (freemail domains only count for system senders, see is_personal_sender)
    _s("google", "Google Account", "email", "google.com", "gmail.com", "googlemail.com", keywords=("google",)),
    _s("microsoft", "Microsoft Account", "email", "microsoft.com", "microsoftonline.com", "live.com", "outlook.com", "hotmail.com", keywords=("microsoft",)),
    _s("apple", "Apple ID / iCloud", "cloud_storage", "apple.com", "icloud.com", "me.com", keywords=("apple.com", "itunes")),
    _s("yahoo", "Yahoo", "email", "yahoo.com", "yahoo-inc.com"),
    _s("proton", "Proton", "email", "proton.me", "protonmail.com", "protonmail.ch"),
    _s("gmx", "GMX", "email", "gmx.ch", "gmx.net", "gmx.de"),
    _s("tuta", "Tuta", "email", "tuta.com", "tutanota.com"),
    _s("fastmail", "Fastmail", "email", "fastmail.com"),
    # social media
    _s("facebook", "Facebook", "social_media", "facebook.com", "facebookmail.com", "meta.com", keywords=("facebook",)),
    _s("instagram", "Instagram", "social_media", "instagram.com"),
    _s("x", "X (Twitter)", "social_media", "x.com", "twitter.com"),
    _s("linkedin", "LinkedIn", "social_media", "linkedin.com", keywords=("linkedin",)),
    _s("tiktok", "TikTok", "social_media", "tiktok.com"),
    _s("snapchat", "Snapchat", "social_media", "snapchat.com"),
    _s("reddit", "Reddit", "social_media", "reddit.com", "redditmail.com"),
    _s("pinterest", "Pinterest", "social_media", "pinterest.com"),
    _s("youtube", "YouTube", "social_media", "youtube.com"),
    _s("discord", "Discord", "social_media", "discord.com", "discordapp.com"),
    _s("telegram", "Telegram", "social_media", "telegram.org"),
    _s("whatsapp", "WhatsApp", "social_media", "whatsapp.com"),
    _s("xing", "XING", "social_media", "xing.com"),
    # banks
    _s("ubs", "UBS", "bank", "ubs.com", "ubs.ch"),
    _s("credit-suisse", "Credit Suisse", "bank", "credit-suisse.com"),
    _s("postfinance", "PostFinance", "bank", "postfinance.ch", keywords=("postfinance",)),
    _s("raiffeisen", "Raiffeisen", "bank", "raiffeisen.ch", keywords=("raiffeisen",)),
    _s("zkb", "Zürcher Kantonalbank", "bank", "zkb.ch"),
    _s("bcv", "BCV", "bank", "bcv.ch"),
    _s("migrosbank", "Migros Bank", "bank", "migrosbank.ch"),
    _s("cler", "Bank Cler", "bank", "cler.ch"),
    _s("valiant", "Valiant", "bank", "valiant.ch"),
    _s("neon", "neon", "bank", "neon-free.ch"),
    _s("yuh", "Yuh", "bank", "yuh.com"),
    _s("revolut", "Revolut", "bank", "revolut.com", keywords=("revolut",)),
    _s("n26", "N26", "bank", "n26.com"),
    _s("hsbc", "HSBC", "bank", "hsbc.com", "hsbc.co.uk"),
    _s("barclays", "Barclays", "bank", "barclays.com", "barclays.co.uk"),
    _s("chase", "Chase", "bank", "chase.com"),
    _s("bofa", "Bank of America", "bank", "bankofamerica.com"),
    _s("wellsfargo", "Wells Fargo", "bank", "wellsfargo.com"),
    _s("ing", "ING", "bank", "ing.com", "ing.de"),
    _s("deutsche-bank", "Deutsche Bank", "bank", "deutsche-bank.de", "db.com"),
    _s("sparkasse", "Sparkasse", "bank", "sparkasse.de"),
    _s("cembra", "Cembra", "bank", "cembra.ch"),
    _s("viseca", "Viseca", "bank", "viseca.ch"),
    _s("swisscard", "Swisscard", "bank", "swisscard.ch"),
    # investment / pension
    _s("swissquote", "Swissquote", "investment", "swissquote.ch", "swissquote.com", keywords=("swissquote",)),
    _s("ibkr", "Interactive Brokers", "investment", "interactivebrokers.com", "interactivebrokers.co.uk"),
    _s("degiro", "DEGIRO", "investment", "degiro.com", "degiro.ch", keywords=("degiro",)),
    _s("traderepublic", "Trade Republic", "investment", "traderepublic.com", keywords=("trade republic",)),
    _s("etoro", "eToro", "investment", "etoro.com"),
    _s("robinhood", "Robinhood", "investment", "robinhood.com", keywords=("robinhood",)),
    _s("vanguard", "Vanguard", "investment", "vanguard.com"),
    _s("fidelity", "Fidelity", "investment", "fidelity.com"),
    _s("schwab", "Charles Schwab", "investment", "schwab.com"),
    _s("viac", "VIAC", "investment", "viac.ch"),
    _s("frankly", "frankly", "investment", "frankly.ch"),
    _s("finpension", "finpension", "investment", "finpension.ch", keywords=("finpension",)),
    _s("truewealth", "True Wealth", "investment", "truewealth.ch"),
    _s("scalable", "Scalable Capital", "investment", "scalable.capital"),
    # crypto
    _s("coinbase", "Coinbase", "crypto", "coinbase.com", keywords=("coinbase",)),
    _s("binance", "Binance", "crypto", "binance.com", keywords=("binance",)),
    _s("kraken", "Kraken", "crypto", "kraken.com", keywords=("kraken",)),
    _s("bitstamp", "Bitstamp", "crypto", "bitstamp.net", keywords=("bitstamp",)),
    _s("bitpanda", "Bitpanda", "crypto", "bitpanda.com", keywords=("bitpanda",)),
    _s("cryptocom", "Crypto.com", "crypto", "crypto.com", keywords=("crypto.com",)),
    _s("ledger", "Ledger", "crypto", "ledger.com"),
    _s("metamask", "MetaMask", "crypto", "metamask.io"),
    _s("gemini", "Gemini", "crypto", "gemini.com"),
    _s("bitcoinsuisse", "Bitcoin Suisse", "crypto", "bitcoinsuisse.com"),
    _s("relai", "Relai", "crypto", "relai.app"),
    # payment
    _s("paypal", "PayPal", "payment", "paypal.com", "paypal.ch", "paypal.de", keywords=("paypal",)),
    _s("twint", "TWINT", "payment", "twint.ch", keywords=("twint",)),
    _s("klarna", "Klarna", "payment", "klarna.com", keywords=("klarna",)),
    _s("wise", "Wise", "payment", "wise.com", "transferwise.com", keywords=("transferwise",)),
    # cloud storage
    _s("dropbox", "Dropbox", "cloud_storage", "dropbox.com", "dropboxmail.com", keywords=("dropbox",)),
    _s("box", "Box", "cloud_storage", "box.com"),
    _s("pcloud", "pCloud", "cloud_storage", "pcloud.com"),
    _s("mega", "MEGA", "cloud_storage", "mega.nz", "mega.io"),
    _s("tresorit", "Tresorit", "cloud_storage", "tresorit.com"),
    _s("backblaze", "Backblaze", "cloud_storage", "backblaze.com"),
    # developer / cloud services (incl. domains and hosting)
    _s("github", "GitHub", "developer_cloud", "github.com", keywords=("github",)),
    _s("gitlab", "GitLab", "developer_cloud", "gitlab.com"),
    _s("bitbucket", "Bitbucket", "developer_cloud", "bitbucket.org"),
    _s("aws", "Amazon Web Services", "developer_cloud", "aws.amazon.com", "amazonaws.com", "aws.com", keywords=("amazon web services", "aws emea")),
    _s("gcp", "Google Cloud", "developer_cloud", "cloud.google.com"),
    _s("azure", "Microsoft Azure", "developer_cloud", "azure.com"),
    _s("digitalocean", "DigitalOcean", "developer_cloud", "digitalocean.com", keywords=("digitalocean",)),
    _s("heroku", "Heroku", "developer_cloud", "heroku.com"),
    _s("vercel", "Vercel", "developer_cloud", "vercel.com"),
    _s("netlify", "Netlify", "developer_cloud", "netlify.com"),
    _s("cloudflare", "Cloudflare", "developer_cloud", "cloudflare.com", keywords=("cloudflare",)),
    _s("hetzner", "Hetzner", "developer_cloud", "hetzner.com", keywords=("hetzner",)),
    _s("openai", "OpenAI", "developer_cloud", "openai.com", keywords=("openai",)),
    _s("anthropic", "Anthropic", "developer_cloud", "anthropic.com", keywords=("anthropic",)),
    _s("godaddy", "GoDaddy", "developer_cloud", "godaddy.com", keywords=("godaddy",)),
    _s("namecheap", "Namecheap", "developer_cloud", "namecheap.com", keywords=("namecheap",)),
    _s("hostpoint", "Hostpoint", "developer_cloud", "hostpoint.ch", keywords=("hostpoint",)),
    _s("infomaniak", "Infomaniak", "developer_cloud", "infomaniak.com", "infomaniak.ch", keywords=("infomaniak",)),
    _s("docker", "Docker", "developer_cloud", "docker.com"),
    _s("npm", "npm", "developer_cloud", "npmjs.com"),
    # password managers
    _s("1password", "1Password", "password_manager", "1password.com", keywords=("1password",)),
    _s("lastpass", "LastPass", "password_manager", "lastpass.com", keywords=("lastpass",)),
    _s("bitwarden", "Bitwarden", "password_manager", "bitwarden.com", keywords=("bitwarden",)),
    _s("dashlane", "Dashlane", "password_manager", "dashlane.com", keywords=("dashlane",)),
    _s("keeper", "Keeper", "password_manager", "keepersecurity.com"),
    _s("nordpass", "NordPass", "password_manager", "nordpass.com"),
    # utilities and telecom
    _s("swisscom", "Swisscom", "utility_telecom", "swisscom.ch", "swisscom.com", "bluewin.ch", keywords=("swisscom",)),
    _s("sunrise", "Sunrise", "utility_telecom", "sunrise.ch", "upc.ch"),
    _s("salt", "Salt", "utility_telecom", "salt.ch"),
    _s("wingo", "Wingo", "utility_telecom", "wingo.ch"),
    _s("yallo", "yallo", "utility_telecom", "yallo.ch"),
    _s("ewz", "ewz", "utility_telecom", "ewz.ch"),
    _s("ekz", "EKZ", "utility_telecom", "ekz.ch"),
    _s("bkw", "BKW", "utility_telecom", "bkw.ch"),
    _s("iwb", "IWB", "utility_telecom", "iwb.ch"),
    _s("vodafone", "Vodafone", "utility_telecom", "vodafone.com", "vodafone.de", "vodafone.co.uk", keywords=("vodafone",)),
    _s("telekom", "Telekom", "utility_telecom", "telekom.de"),
    _s("talktalk", "TalkTalk", "utility_telecom", "talktalk.co.uk", keywords=("talktalk",)),
    _s("bt", "BT", "utility_telecom", "bt.com"),
    _s("verizon", "Verizon", "utility_telecom", "verizon.com", keywords=("verizon",)),
    _s("att", "AT&T", "utility_telecom", "att.com"),
    _s("tmobile", "T-Mobile", "utility_telecom", "t-mobile.com"),
    # insurance
    _s("axa", "AXA", "insurance", "axa.ch", "axa.com", "axa.de"),
    _s("zurich", "Zurich Insurance", "insurance", "zurich.ch", "zurich.com"),
    _s("helvetia", "Helvetia", "insurance", "helvetia.ch", "helvetia.com", keywords=("helvetia",)),
    _s("mobiliar", "Die Mobiliar", "insurance", "mobiliar.ch", keywords=("mobiliar",)),
    _s("allianz", "Allianz", "insurance", "allianz.ch", "allianz.com", "allianz.de", keywords=("allianz",)),
    _s("generali", "Generali", "insurance", "generali.ch", "generali.com", keywords=("generali",)),
    _s("baloise", "Baloise", "insurance", "baloise.ch", "baloise.com", keywords=("baloise",)),
    _s("swisslife", "Swiss Life", "insurance", "swisslife.ch", "swisslife.com", keywords=("swiss life",)),
    _s("vaudoise", "Vaudoise", "insurance", "vaudoise.ch", keywords=("vaudoise",)),
    _s("swica", "SWICA", "insurance", "swica.ch", keywords=("swica",)),
    _s("css", "CSS", "insurance", "css.ch"),
    _s("helsana", "Helsana", "insurance", "helsana.ch", keywords=("helsana",)),
    _s("sanitas", "Sanitas", "insurance", "sanitas.com", keywords=("sanitas",)),
    _s("concordia", "Concordia", "insurance", "concordia.ch"),
    _s("visana", "Visana", "insurance", "visana.ch", keywords=("visana",)),
    _s("groupemutuel", "Groupe Mutuel", "insurance", "groupemutuel.ch", keywords=("groupe mutuel",)),
    # memberships
    _s("tcs", "TCS", "membership", "tcs.ch"),
    _s("adac", "ADAC", "membership", "adac.de"),
    _s("rega", "Rega", "membership", "rega.ch"),
    _s("activfitness", "Activ Fitness", "membership", "activfitness.ch", keywords=("activ fitness",)),
    _s("fitnessparks", "Migros Fitnessparks", "membership", "fitnessparks.ch"),
    _s("updatefitness", "Update Fitness", "membership", "updatefitness.ch"),
    _s("classpass", "ClassPass", "membership", "classpass.com", keywords=("classpass",)),
    _s("strava", "Strava", "membership", "strava.com", keywords=("strava",)),
    _s("costco", "Costco", "membership", "costco.com"),
    # shopping
    _s("amazon", "Amazon", "shopping", "amazon.com", "amazon.de", "amazon.co.uk", "amazon.fr", "amazon.it", "amazon.ch", keywords=("amazon",)),
    _s("ebay", "eBay", "shopping", "ebay.com", "ebay.ch", "ebay.de", "ebay.co.uk", keywords=("ebay",)),
    _s("galaxus", "Galaxus / Digitec", "shopping", "galaxus.ch", "digitec.ch", keywords=("galaxus", "digitec")),
    _s("zalando", "Zalando", "shopping", "zalando.ch", "zalando.de", keywords=("zalando",)),
    _s("ricardo", "Ricardo", "shopping", "ricardo.ch"),
    _s("tutti", "tutti.ch", "shopping", "tutti.ch"),
    _s("aliexpress", "AliExpress", "shopping", "aliexpress.com", keywords=("aliexpress",)),
    _s("temu", "Temu", "shopping", "temu.com"),
    _s("etsy", "Etsy", "shopping", "etsy.com"),
    _s("ikea", "IKEA", "shopping", "ikea.com", "ikea.ch"),
    _s("migros", "Migros", "shopping", "migros.ch"),
    _s("coop", "Coop", "shopping", "coop.ch"),
    _s("manor", "Manor", "shopping", "manor.ch"),
    _s("brack", "Brack", "shopping", "brack.ch"),
    _s("interdiscount", "Interdiscount", "shopping", "interdiscount.ch"),
    _s("shein", "SHEIN", "shopping", "shein.com"),
    # travel
    _s("booking", "Booking.com", "travel", "booking.com", keywords=("booking.com",)),
    _s("airbnb", "Airbnb", "travel", "airbnb.com", "airbnb.ch", keywords=("airbnb",)),
    _s("expedia", "Expedia", "travel", "expedia.com", "expedia.ch"),
    _s("sbb", "SBB", "travel", "sbb.ch"),
    _s("swiss", "SWISS", "travel", "swiss.com"),
    _s("easyjet", "easyJet", "travel", "easyjet.com", keywords=("easyjet",)),
    _s("lufthansa", "Lufthansa / Miles & More", "travel", "lufthansa.com", "miles-and-more.com", keywords=("lufthansa",)),
    _s("ryanair", "Ryanair", "travel", "ryanair.com", keywords=("ryanair",)),
    _s("uber", "Uber", "travel", "uber.com"),
    _s("hotels", "Hotels.com", "travel", "hotels.com"),
    _s("tripadvisor", "Tripadvisor", "travel", "tripadvisor.com"),
    _s("airfrance-klm", "Air France / KLM", "travel", "airfrance.com", "klm.com"),
    _s("ba", "British Airways", "travel", "britishairways.com", "ba.com"),
    # entertainment (streaming, music, games)
    _s("netflix", "Netflix", "entertainment", "netflix.com", keywords=("netflix",)),
    _s("spotify", "Spotify", "entertainment", "spotify.com", keywords=("spotify",)),
    _s("disney", "Disney+", "entertainment", "disneyplus.com", keywords=("disney plus", "disneyplus")),
    _s("primevideo", "Prime Video", "entertainment", "primevideo.com"),
    _s("steam", "Steam", "entertainment", "steampowered.com", "steamcommunity.com", keywords=("steam games", "steampowered")),
    _s("epic", "Epic Games", "entertainment", "epicgames.com"),
    _s("playstation", "PlayStation", "entertainment", "playstation.com", "sony.com", keywords=("playstation",)),
    _s("xbox", "Xbox", "entertainment", "xbox.com"),
    _s("nintendo", "Nintendo", "entertainment", "nintendo.com", "nintendo.net", keywords=("nintendo",)),
    _s("deezer", "Deezer", "entertainment", "deezer.com", keywords=("deezer",)),
    _s("tidal", "TIDAL", "entertainment", "tidal.com"),
    _s("audible", "Audible", "entertainment", "audible.com", "audible.de", keywords=("audible",)),
    _s("twitch", "Twitch", "entertainment", "twitch.tv"),
    _s("zattoo", "Zattoo", "entertainment", "zattoo.com", keywords=("zattoo",)),
    # software
    _s("adobe", "Adobe", "software", "adobe.com", keywords=("adobe",)),
    _s("canva", "Canva", "software", "canva.com"),
    _s("notion", "Notion", "software", "notion.so", "makenotion.com"),
    _s("slack", "Slack", "software", "slack.com"),
    _s("zoom", "Zoom", "software", "zoom.us"),
    _s("atlassian", "Atlassian", "software", "atlassian.com", "atlassian.net"),
    _s("figma", "Figma", "software", "figma.com"),
    _s("grammarly", "Grammarly", "software", "grammarly.com"),
    _s("evernote", "Evernote", "software", "evernote.com"),
    _s("duolingo", "Duolingo", "software", "duolingo.com"),
)

SERVICES_BY_KEY = {s.key: s for s in SERVICES}
# domain suffix -> service; longest suffix wins
_BY_DOMAIN = {d: s for s in SERVICES for d in s.domains}
_KEYWORDS = [
    (re.compile(rf"(?<![a-z0-9]){re.escape(k)}(?![a-z0-9])", re.I), s) for s in SERVICES for k in s.keywords
]

# Addresses at these domains are usually people, not services (unless the local part is a system name).
FREEMAIL_DOMAINS = frozenset({
    "gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "live.com", "yahoo.com", "icloud.com",
    "me.com", "proton.me", "protonmail.com", "protonmail.ch", "gmx.ch", "gmx.net", "gmx.de", "bluewin.ch",
    "tuta.com", "tutanota.com", "fastmail.com", "web.de", "aol.com", "sunrise.ch",
})
SYSTEM_LOCAL_PART = re.compile(
    r"no-?reply|do-?not-?reply|notif|alert|security|account|support|service|billing|team|info|hello|mailer|verify|"
    r"welcome|news",
    re.I,
)


def lookup_domain(host: str) -> Service | None:
    """The catalog service for a sender host (e.g. `mail.instagram.com` -> Instagram)."""
    parts = host.lower().strip(".").split(".")
    for i in range(len(parts) - 1):
        service = _BY_DOMAIN.get(".".join(parts[i:]))
        if service:
            return service
    return None


def lookup_text(text: str) -> Service | None:
    """A catalog service named by a brand keyword in free text (bank descriptions)."""
    return next((s for rx, s in _KEYWORDS if rx.search(text or "")), None)


def is_personal_sender(address: str, host: str) -> bool:
    """A person writing from a freemail address (e.g. a friend at gmail.com), not a service."""
    local = address.rsplit("@", 1)[0] if "@" in address else ""
    return registrable_domain(host) in FREEMAIL_DOMAINS and not SYSTEM_LOCAL_PART.search(local)


# Keyword rules for services not in the catalog, most specific first.
TYPE_KEYWORDS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("password_manager", re.compile(r"password manager|master password|your vault|passwort-manager", re.I)),
    ("crypto", re.compile(r"bitcoin|ethereum|crypto|blockchain|wallet address|seed phrase|\bbtc\b|\beth\b|stablecoin", re.I)),
    ("investment", re.compile(
        r"brokerage|portfolio|securities|\bdepot\b|dividend|trade (confirmation|executed)|order executed|\betf\b|"
        r"pillar 3a|säule 3a|3a account|vested|wertschriften|pension fund|pensionskasse", re.I)),
    ("insurance", re.compile(
        r"insurance|versicherung|assurance|policy number|policennummer|your policy|ihre police|premium invoice|"
        r"krankenkasse|health insurer|claim number|schadenfall", re.I)),
    ("bank", re.compile(
        r"\bbank\b|banking|\biban\b|account statement|kontoauszug|relevé de compte|e-banking|debit card|"
        r"credit card|kreditkarte|carte de crédit|overdraft|standing order|dauerauftrag|überweisung", re.I)),
    ("payment", re.compile(r"payment account|wallet balance|you sent a payment|you received a payment|money request", re.I)),
    ("developer_cloud", re.compile(
        r"api key|repository|pull request|deploy(ment)?|\bserver\b|hosting|domain (renewal|registration|name)|"
        r"\bdns\b|ssh key|cloud console|access token|build (failed|succeeded)", re.I)),
    ("cloud_storage", re.compile(r"cloud storage|storage (is )?(almost )?full|storage plan|backup|shared a (file|folder)", re.I)),
    ("utility_telecom", re.compile(
        r"electricity|\bstrom\b|gas bill|water bill|energy bill|mobile plan|mobile subscription|broadband|"
        r"internet (plan|contract|subscription)|roaming|sim card|telecom|festnetz|natel", re.I)),
    ("social_media", re.compile(
        r"new follower|friend request|tagged you|mentioned you|liked your|commented on your|sent you a message|"
        r"your profile|connection request", re.I)),
    ("travel", re.compile(
        r"booking confirmation|itinerary|boarding pass|\bflight\b|check-in|hotel reservation|your trip|"
        r"buchungsbestätigung|reisebestätigung", re.I)),
    ("membership", re.compile(r"membership|mitgliedschaft|member number|mitgliedsnummer|loyalty|points balance|adhésion", re.I)),
    ("shopping", re.compile(
        r"order confirmation|your order|order number|has shipped|out for delivery|bestellbestätigung|"
        r"ihre bestellung|confirmation de commande|votre commande", re.I)),
    ("entertainment", re.compile(r"streaming|playlist|watchlist|\bgame\b|gaming|episode|\bseries\b", re.I)),
)


def type_from_keywords(text: str) -> str | None:
    return next((t for t, rx in TYPE_KEYWORDS if rx.search(text or "")), None)
