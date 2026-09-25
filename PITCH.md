# Digital Estate Manager (DEM): Pitch

## Introduction

We all have hundred of accounts, subscriptions, drives, and other digital assets... Many of us manage these accounts, but what happens to them after we die? Our Digital Estate Manager (DEM) Helps handling digital legacy in a private and simple way.

## Feature 1: Privacy and safety
 
Making full use of VZ structure for execution of will, clients can make sure their digital information stays accessible after die, but only after they die thanks to a 2 keys system: one for the client only and one securely stored until their death kept for the heir and their consultants 

No pipsqueak when the client's alive and no hassle for the relatives afterwards.

## Feature 2: Easy extraction of accounts and subscriptions from email and bank statements

DEM uses Apertus as the AI brain for extraction of accounts and subscriptions from emails and bank statements, looking for regular transactions or emails that suggest account sign-ups. The client and their advisor obtain a clean list of accounts and subscriptions (called Assets), so they can make better-informed decisions for the future.

DEM respects the level of exposure each client is comfortable with,they can add the assets they want manually instead of having their data processed by AI.


## Feature 3: Legacy an Cancellation policy gathering

DEM is structured with legacy in mind. Among the most cumbersome tasks is finding out what happens to an asset after death: what a provider does with it, what information they ask for, and what procedure to follow. 

DEM helps clients and legal consultants find this information, based on each provider's policy crawled directly from its official website. For each provider (e.g. Google), DEM shows a short summary and a link to the official legacy policy page. Every summary links to its source page and carries a "checked" date, so advisors can easily verify it. The summaries are machine-generated information, not legal advice, and should be verified at the source.

DEM also helps find cancellation policies: it informs the client or executor of their options, such as how to delete an account or cancel an unwanted subscription. This is especially helpful for an executor who is instructed to mass-delete accounts. As companies handle subscription and account termination differently, collecting this information in one place greatly improves efficiency. In addition, DEM guides the executor through cancellation and legacy recovery with step-by-step guides—for example, by autogenerating cancellation emails.

This supports legal representatives after death, making it much easier to confirm which documents and steps a provider requires and carry them out, backed by AI-generated summaries that link back to the source. 

To further help legal representatives carry out the client's will, each account has a "My Wish" field (for example: cancel, deactivate, or pass to heir), which the executor sees right next to the provider's policy. This lets clients record their wishes for their digital accounts and data based on the information provided by DEM.

## Feature 4: Ethical and privacy-aware agentic AI

The legacy-policy crawler is an agent powered by Apertus 1.5, the fully open Swiss language model built by EPFL, ETH Zurich and CSCS [2][3]. We access it through Swisscom, whose Swiss AI Platform keeps customer data in Switzerland [4]. Apertus was developed with due consideration to Swiss data protection and copyright laws and the transparency obligations of the EU AI Act [3].

The Legacy policy and cancellation policies crawlers only ever reads public company web pages, so DEM keeps potentially sensitive client data away from big AI companies, which some clients may feel apprehensive about. It uses official pages only, respects `robots.txt` [5] and never logs in to accounts. Because Apertus is multilingual [3], it also handles Swiss providers' non-English pages: for example, a German Swisscom help page.

## Feature 5: Easy integration into the VZ Financial Portal

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
