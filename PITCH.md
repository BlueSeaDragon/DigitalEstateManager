# Digital Estate Manager (DEM): Pitch

## Introduction

Digital services permeate every aspect of our lives, from entertainment (Netflix, Crunchyroll, Spotify) and productivity (Microsoft, Google, Slack) to AI subscriptions (OpenAI, Claude, Gemini). Many of us manage these accounts with tools like password managers, but what happens to them after we die? Keeping track of one's own subscriptions is hard enough; mourning relatives must scramble through loose bank statements and emails to back up data and cancel unwanted services before further charges arise. Our Digital Estate Manager (DEM) closes this gap in legal digital-legacy handling in a private, simple and legally informative way.

## Feature 1: Privacy and safety

DEM is a two-key system that keeps the user's data fully private and shares it only with heirs, legal advisors or other authorised persons. DEM is hosted by VZ VermögensZentrum, an independent financial and estate-planning consultancy [1], so the tool complements consultancies: digital asset overview and estate-planning advice during life, and will/execution assistance after death, for both the consultancy and the client.

When an account is created, two private keys are generated. One is held only by the owner. The other is safely stored in VZ's safe or vault and becomes accessible only once the owner has died, as authorised beforehand by binding contract during asset planning with their consultant. The executor can then act on the client's behalf, for example by passing certain information to heirs.

This way, privacy-concerned clients who do not want their consultants to track their data over the years can use the app in a fully private environment until they choose to release information. This should encourage regular digital asset monitoring, which reduces the hassle for relatives searching through digital footprints after the owner has died.

DEM also lets users enter subscriptions and accounts manually, if the agent misreads something, entries are missed, or the client is unwilling to link their email or provide bank statements. DEM respects the level of exposure each client is comfortable with.

## Feature 2: Easy extraction of accounts and subscriptions from email and bank statements

Extraction is authorised by clients, or by the legal representatives of deceased persons.

Various tools on the market already extract accounts and subscriptions by going through email or bank statements, looking for regular transactions or emails that suggest account sign-ups. We demonstrate this feature by integrating pre-existing apps into DEM. The user obtains a clean list of their accounts and subscriptions, so they can make better-informed financial decisions in the future.

This feature is also useful for relatives of deceased persons. As long as they have access to email or statements, DEM can extract meaningful information about the person's digital footprint, sparing families and legal teams the hassle of going through records manually.

## Feature 3: Legacy policy gathering

DEM gives clients and legal consultants information on what happens to an account after death, based on each provider's policy crawled from its official website. For each provider (e.g. Google), DEM shows a short summary and a link to the page that explains how the account is handled after death. Every summary links to its source page and carries a "checked" date, so advisors can verify it. The summaries are machine-generated information, not legal advice, and should be verified at the source.

The feature helps the user, who can compile their wishes for their digital accounts and data based on this information. It also helps the legal representative after death: the executor can more easily confirm which documents and steps a provider requires and carry them out, with AI-generated summaries that link back to the source.

## Feature 4: Cancellation guidance

DEM does not interact with the user's accounts directly. Instead, it informs the user of their options, such as how to delete an account or cancel an unwanted subscription. This is especially helpful for an executor who is instructed to mass-delete accounts. As companies handle subscription and account termination differently, collecting this information in one place would greatly improve efficiency.

## Feature 5: Ethical and privacy-aware agentic AI

The legacy-policy crawler is an agent powered by Apertus 1.5, the fully open Swiss language model built by EPFL, ETH Zurich and CSCS [2][3]. We access it through Swisscom, whose Swiss AI Platform keeps customer data in Switzerland [4]. Apertus was developed with due consideration to Swiss data protection and copyright laws and the transparency obligations of the EU AI Act [3].

The crawler only ever reads public company web pages, so DEM keeps potentially sensitive client data away from big AI companies, which some clients may feel apprehensive about. It uses official pages only, respects `robots.txt` [5] and never logs in to accounts. Because Apertus is multilingual [3], it also handles Swiss providers' non-English pages: for example, a German Swisscom help page.

## References

1. VZ VermögensZentrum: independent financial consulting incl. estate planning. <https://www.vermoegenszentrum.ch/en> and <https://www.vermoegenszentrum.ch/en/estate-planning>
2. Apertus 1.5 release (24 July 2026): "fully open: open weights, open data, open values, and full training details"; 8B and 70B models, 262,144-token context, improved tool use. <https://apertus-ai.org/articles/2026-07-apertus-1-5/>. Model card (Apache 2.0): <https://huggingface.co/swiss-ai/Apertus-v1.5-70B>
3. Swisscom, "Apertus: Switzerland launches an open-source AI model": built by EPFL, ETH Zurich and CSCS; multilingual; "developed with due consideration to Swiss data protection laws, Swiss copyright laws, and the transparency obligations under the EU AI Act". <https://www.swisscom.ch/en/about/news/2025/09/02-apertus.html>
4. Swisscom Swiss AI Platform: "Your data and information remain in Switzerland at all times and cannot be used for development by international tech companies"; offers Apertus. <https://www.swisscom.ch/en/business/enterprise/offer/platforms-applications/data-driven-business/swiss-ai-platform.html>. Apertus 1.5 70B API documentation: <https://docs.cloud.swisscom.ch/guide/cloud-services/aip/models/apertus-1_5_70B>
5. Robots Exclusion Protocol (RFC 9309). <https://www.rfc-editor.org/rfc/rfc9309>
