# Digital Estate Manager (DEM): Pitch

## Introduction

Digital services permeate every aspect of our lives, from entertainment (Netflix, Crunchyroll, Spotify) and productivity (Microsoft, Google, Slack) to AI subscriptions (OpenAI, Claude, Gemini). Many of us manage these accounts with tools like password managers, but what happens to them after we die? Estate planning has long covered bank accounts, property and insurance; digital accounts are the missing piece. Keeping track of one's own subscriptions is hard enough; mourning relatives must scramble through loose bank statements and emails to back up data and cancel unwanted services before further charges arise. Our Digital Estate Manager (DEM) closes this gap in legal digital-legacy handling in a private, simple and legally informative way. It is built for VZ, its legal and estate-planning consultants, and their clients.

## Feature 1: Privacy and safety

DEM is a two-key system that keeps the client's data fully private and shares it only with heirs, legal advisors or other authorised persons. DEM is designed to be hosted by VZ VermögensZentrum, an independent financial and estate-planning consultancy [1], so the tool complements VZ's services: digital asset overview and estate-planning advice during life, and will/execution assistance after death, for both VZ's advisors and their clients.

When an account is created, two private keys are generated. One is held only by the owner. The other is safely stored in VZ's safe or vault and becomes accessible only once the owner has died, as authorised beforehand by binding contract during asset planning with their consultant. The executor can then act on the client's behalf, for example by passing certain data to heirs.

This way, privacy-concerned clients who do not want their consultants to track their data over the years can use the app in a fully private environment until they choose to release information. This should encourage regular digital asset monitoring, which reduces the post-mortem hassle of searching through documents for digital footprints.

DEM also allows users to enter subscriptions and accounts manually, if the agent misreads something, entries are missed, or the client is unwilling to link their email or provide bank statements. DEM respects the level of exposure each client is comfortable with.

## Feature 2: Easy extraction of accounts and subscriptions from email and bank statements

Extraction is authorised by clients, or by the legal representatives of deceased persons.

DEM uses Apertus as the AI brain for extraction of accounts and subscriptions from emails and bank statements, looking for regular transactions or emails that suggest account sign-ups. The client and their advisor obtain a clean list of accounts and subscriptions (called Assets), so they can make better-informed decisions for the future.

This feature is also useful for relatives of deceased persons. As long as they have access to email or statements, DEM can extract meaningful information about the person's digital footprint, sparing families and legal teams the time of going through records manually.

## Feature 3: Legacy policy gathering

DEM gives clients and legal consultants information on what happens to an account after death, based on each provider's policy crawled from its official website. For each provider (e.g. Google), DEM shows a short summary and a link to the official legacy policy page. Every summary links to its source page and carries a "checked" date, so advisors can verify it. The summaries are machine-generated information, not legal advice, and should be verified at the source.

The feature helps the client, who can compile their wishes for their digital accounts and data based on this information. Each account has a "My Wish" field (for example cancel, deactivate or pass to heir), which the executor later sees next to the provider's policy. It also helps the legal representative after death: the executor can more easily confirm which documents and steps a provider requires and carry them out, with AI-generated summaries that link back to the source.

## Feature 4: Cancellation guidance

DEM does not interact with the client's accounts directly. Instead, it informs the client or executor of their options, such as how to delete an account or cancel an unwanted subscription. This is especially helpful for an executor who is instructed to mass-delete accounts. As companies handle subscription and account termination differently, collecting this information in one place would greatly improve efficiency.

DEM also guides the executor through the cancellation with step-by-step guides. For example, it can autogenerate standard cancellation emails.

## Feature 5: Ethical and privacy-aware agentic AI

The legacy-policy crawler is an agent powered by Apertus 1.5, the fully open Swiss language model built by EPFL, ETH Zurich and CSCS [2][3]. We access it through Swisscom, whose Swiss AI Platform keeps customer data in Switzerland [4]. Apertus was developed with due consideration to Swiss data protection and copyright laws and the transparency obligations of the EU AI Act [3].

The crawler only ever reads public company web pages, so DEM keeps potentially sensitive client data away from big AI companies, which some clients may feel apprehensive about. It uses official pages only, respects `robots.txt` [5] and never logs in to accounts. Because Apertus is multilingual [3], it also handles Swiss providers' non-English pages: for example, a German Swisscom help page.

## Feature 6: Easy integration into the VZ Financial Portal

DEM is a standalone app that fits the VZ ecosystem. VZ clients already use the VZ Financial Portal on the web and as an iOS and Android app, with an overview of their banking and pension data, insurance and mortgages behind a secured login, with data kept in Switzerland [6][7]. DEM adds the missing digital layer: subscriptions and online accounts next to the assets the portal already shows.

Two existing VZ features are a natural fit. VZ Safe already lets clients store documents such as a will or inheritance agreement digitally [1][6]; it could hold the second key or the executor's release documents. The portal's login could also serve as the single sign-in for DEM, so clients do not need another account. Data location matches too: the portal keeps data in Switzerland [6], and so does the Apertus model behind DEM [4].

Technically, DEM keeps its logic (asset models, policies, extraction) in a separate Python package, with the user interface as a thin layer on top. VZ's developers can therefore reuse the logic behind their own portal screens, or embed DEM as a new section, without rebuilding it.

## References

1. VZ VermögensZentrum: independent financial consulting incl. estate planning. <https://www.vermoegenszentrum.ch/en> and <https://www.vermoegenszentrum.ch/en/estate-planning>
2. Apertus 1.5 release (24 July 2026): "fully open: open weights, open data, open values, and full training details"; 8B and 70B models, 262,144-token context, improved tool use. <https://apertus-ai.org/articles/2026-07-apertus-1-5/>. Model card (Apache 2.0): <https://huggingface.co/swiss-ai/Apertus-v1.5-70B>
3. Swisscom, "Apertus: Switzerland launches an open-source AI model": built by EPFL, ETH Zurich and CSCS; multilingual; "developed with due consideration to Swiss data protection laws, Swiss copyright laws, and the transparency obligations under the EU AI Act". <https://www.swisscom.ch/en/about/news/2025/09/02-apertus.html>
4. Swisscom Swiss AI Platform: "Your data and information remain in Switzerland at all times and cannot be used for development by international tech companies"; offers Apertus. <https://www.swisscom.ch/en/business/enterprise/offer/platforms-applications/data-driven-business/swiss-ai-platform.html>. Apertus 1.5 70B API documentation: <https://docs.cloud.swisscom.ch/guide/cloud-services/aip/models/apertus-1_5_70B>
5. Robots Exclusion Protocol (RFC 9309). <https://www.rfc-editor.org/rfc/rfc9309>
6. VZ Financial Portal: asset overview of banking and pension data, insurance and mortgage management, VZ Safe for documents, secured login, data remains in Switzerland, free for VZ clients. <https://www.vermoegenszentrum.ch/en/solution/vz-financial-portal>
7. VZ Finanzportal app (iOS and Android). <https://apps.apple.com/gb/app/vz-finanzportal/id1553514484> and <https://play.google.com/store/apps/details/VZ_Financial_Portal?id=ch.vermoegenszentrum.fipo>
