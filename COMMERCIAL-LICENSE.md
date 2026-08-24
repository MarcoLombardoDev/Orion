# Commercial Licence — Orion

**Orion — PDF Editor for Desktop**  
Copyright © 2026 Marco Lombardo

Orion is dual-licensed. It is available under the
[GNU Affero General Public License v3.0](LICENSE) at no cost, and under the commercial
terms in this document for those who cannot accept the AGPL's obligations.

Both licences cover **the same software**. There is no crippled edition, no feature held
back behind a paywall, no licence key and no phone-home. What you buy is **permission**,
not functionality.

That includes every capability: text, images, shapes and annotations, page
insertion, reordering and rotation, split and merge, and full-document search.
Nothing is reserved for a paid tier, now or later.

> **To buy, or to ask anything commercial — including whether you need this at all —
> email [marco.lombardo@gmail.com](mailto:marco.lombardo@gmail.com?subject=Orion%20commercial%20licence%20enquiry).**
> Email is the only commercial channel: quotes, contracts, invoicing and pre-sales
> questions all go there. GitHub Issues are for bugs and feature requests.

> This page is a **commercial offer and a summary of terms**, not the signed agreement.
> The binding contract is the licence certificate issued per customer. It is not legal
> advice; have your own counsel review it before signing.

---

## 1. Do you actually need this?

Most people do not. Read this before reading the price list.

| What you want to do | Licence you need |
|---|---|
| Use Orion inside your organisation, however many people, however many machines | **AGPL — free.** Nothing to buy, nothing to declare. |
| Modify it for your own internal use and keep the changes to yourself | **AGPL — free.** |
| Publish a fork, or ship a modified version to someone else | **AGPL — free**, provided you release your modified source under AGPL-3.0. |
| Run a modified Orion as a closed-source internal tool, for your own staff only | **Commercial** — see §3 |
| Ship Orion, or code derived from it, inside a **closed-source product** you distribute | **Redistribution** — see §4 |
| Run a modified Orion as a **hosted or SaaS service for your customers**, without publishing your source | **Redistribution** |
| Redistribute it to your customers under **your own name or branding** | **Redistribution** |
| Your organisation's policy forbids AGPL code, and you need it in writing | **Commercial** (or **Redistribution**, if you also distribute) |

**Internal use is free, permanently, for organisations of any size.** Anyone telling you
otherwise about an AGPL project is mistaken. Buy a commercial licence when the AGPL's
*distribution* terms are the problem — not simply because you are a company.

The dividing line is one rule: **AGPL-3.0 is free as long as the source stays open.**

---

## 2. Licence structure

```
PRODUCT LICENSING
│
├── Community
│   └── AGPL-3.0
│
├── Commercial                    (internal use)
│   ├── Small       — 1–49 employees
│   ├── Medium      — 50–249 employees
│   ├── Large       — 250–999 employees
│   └── Enterprise  — 1,000+ employees / Corporate Group
│
└── Redistribution                (reaches third parties)
    ├── Standard
    └── Enterprise
```

Three kinds of licence, not four price points on one list:

- **Community** — the AGPL-3.0 build. Free, unlimited, internal use of any size.
- **Commercial** — removes the AGPL's copyleft obligation for **closed-source internal
  use**. Sized by the licensee's employee count. See §3.
- **Redistribution** — grants the right to **ship Orion, or a derivative of it, to third
  parties** — embedded, OEM'd, resold, or offered as a service to your own customers. See
  §4. It is a different kind of licence from Commercial, not a bigger version of it: a
  five-person software house redistributing a product to ten thousand customers needs
  Redistribution, not a large Commercial tier.

Every tier, in every branch, is the **same software** under the opening of this document:
no feature is gated behind a higher tier.

---

## 3. What the Commercial licence grants

Subject to payment and to the tier purchased, a non-exclusive, non-transferable licence,
for **one named legal entity**, to:

1. use, copy and modify Orion;
2. deploy it as an internal, closed-source tool, without publishing your modified source;
3. run it as an internally-accessed network service without triggering AGPL section 13,
   provided access is limited to your own authorised users and installations.

It does **not** automatically include, at any Commercial tier:

- redistribution to third parties, in any form;
- OEM or embedding in a product you ship;
- sublicensing;
- use by other companies in the same corporate group, unless the Enterprise tier's
  group-wide scope has been explicitly agreed and named in the certificate.

Any of those needs a **Redistribution licence** instead of, or alongside, Commercial — see
§4.

### 3.1 The four Commercial tiers

| Tier | Employees | |
|---|---|---|
| **Small** | 1–49 | Same model as every Commercial tier below, sized for a small organisation: one legal entity, internal use, non-redistributable. |
| **Medium** | 50–249 | Same model, applied to a mid-sized organisation. Still organisation-based, internal-use, single legal entity, non-redistributable. |
| **Large** | 250–999 | Same model, applied to a larger organisation. Still limited to the internal use of the one authorised legal entity. |
| **Enterprise** | 1,000+, **or** any Corporate Group scope | Covers at least one of: an organisation of 1,000+ employees; an organisation belonging to a corporate group; a use case that needs a group-wide perimeter; use by more than one legal entity of the same group, when explicitly authorised. May be named **Enterprise / Group Commercial Licence** in the certificate, which must state exactly which legal entities are included. |

Belonging to a large group does not, by itself, let a small subsidiary's Small-tier
licence cover the rest of the group. A group-wide perimeter is never implied — it must be
explicitly agreed and named entity by entity. See §3.3.

### 3.2 Employee count

Unless the applicable Enterprise / Group agreement states a different scope:

> Employee count refers to the total number of employees of the licensed legal entity.

It does **not** automatically include customers, end users, suppliers, partners, or
external consultants.

### 3.3 Corporate Group

A **Corporate Group** is a set of companies directly or indirectly controlled by the same
parent company, or otherwise part of the same corporate structure, as defined in the
applicable agreement.

Membership in a group is not, by itself, authorisation for the group. A small company
belonging to a large group cannot use a Small-tier licence to extend rights to the rest of
the group — a group-wide perimeter must be expressly authorised and stated in the
Enterprise certificate.

---

## 4. What the Redistribution licence grants

A **Redistribution licence** is required whenever Orion, or any part of it, is passed on
to a third party — regardless of organisation size. Examples:

- incorporation into another piece of software;
- embedding;
- distribution alongside a proprietary product;
- distribution to customers or to end users;
- commercialisation of a derivative product;
- integration into a proprietary application;
- OEM scenarios;
- distribution as a component of a commercial solution.

"OEM" is used above as an example of a Redistribution scenario, not as a separate category
of its own — see §14.

Subject to payment and to the specific agreement, a Redistribution licence may grant:

1. modification, integration and embedding rights;
2. the right to distribute the result, in source or binary form, with no obligation to
   publish your own source;
3. the right to commercialise the resulting product;
4. sublicensing of these rights to your own end users, **solely as part of your product**,
   not as a standalone competing tool.

It does **not** automatically grant: exclusivity; unlimited sublicensing; rights to the
Project Owner's trademarks; rights to third-party dependencies (§11); or transfer of the
licence to another party.

### 4.1 Redistribution — Standard

For ordinary commercial redistribution: software houses, ISVs, integrators, commercial
developers, and businesses embedding Orion in a product, distributed to a non-exceptional
number of customers or installations.

### 4.2 Redistribution — Enterprise

For redistribution at scale: large software houses and groups, worldwide distribution,
high-volume products, millions of users or installations, large-scale commercial
platforms, and large OEM programmes.

Unlike Commercial, this tier is **not** primarily sized by employee count. The relevant
factors, weighed per case in the agreement, include: number of products; number of
customers; number of installations; distribution volume; number of end users; territory;
the product's revenue; number of legal entities involved; and the level of support
required. The exact perimeter is defined in the commercial agreement, not by a fixed
threshold in this document.

---

## 5. Price list

All prices in **EUR, excluding VAT**, per **licensee organisation** — the legal entity and,
where the tier says so, the agreed group perimeter. Seats are never counted: you are not
billed per developer, per user or per installation.

| Tier | Price | Scope |
|---|---:|---|
| **Community** | **Free** | Everything Orion does, under AGPL-3.0. Unlimited internal use. |
| **Commercial — Small** | **€900 / year** | 1–49 employees. Closed-source internal use, one legal entity. |
| **Commercial — Medium** | **€1,800 / year** | 50–249 employees. Same model as Small. |
| **Commercial — Large** | **€3,200 / year** | 250–999 employees. Same model as Small and Medium. |
| **Commercial — Enterprise** | **from €5,500 / year** | 1,000+ employees, or a group-wide perimeter. Unlimited internal products and services within the agreed scope. Written answers to procurement and legal questionnaires. |
| **Redistribution — Standard** | **€2,900 / year** | Ordinary commercial redistribution: embed it in a product you sell, or run it as a hosted service for your customers. |
| **Redistribution — Enterprise** | **from €10,000 / year** | Large-scale redistribution: worldwide distribution, high-volume products, large OEM programmes. Scope priced per case. |

### Perpetual option

A perpetual licence is bought once and never renews. It covers **the major version current
at the date of purchase**, in perpetuity, together with every patch and minor release
within that major version. Moving to a later major version is a new purchase.

It is priced at **three times the annual rate** of the same tier, and is offered on the
four fixed-price tiers only — both Enterprise tiers are negotiated and priced per case
instead.

| Tier | Perpetual price (one-off) |
|---|---:|
| Commercial — Small | **€2,700** |
| Commercial — Medium | **€5,400** |
| Commercial — Large | **€9,600** |
| Redistribution — Standard | **€8,700** |

Support (§6) runs for **twelve months** from a perpetual purchase, and can be renewed
afterwards at 20% of the annual rate of the same tier. The licence itself does not expire
when support does.

### What every paid licence includes

The same commitments, at every tier above Community:

- **Email support** — see §6. Always included, never sold separately to a paying customer.
- **Updates for the whole term.** Every version released while your subscription is active
  is licensed to you; there is no separate charge for upgrading within a term.
- **No retroactive charge.** Renewals are priced at the rate in force when you first bought,
  for as long as you renew without a gap.
- **Cancel any time.** No notice period, no auto-renewal trap. An invoice is issued per
  term; not paying it ends the subscription.

### Discounts

| Who | What |
|---|---|
| Fewer than 10 employees **and** under €1M annual revenue | **50% off** any annual Commercial or Redistribution tier |
| Registered non-profits, accredited academic institutions, published research | **Free commercial licence** — ask |

---

## 6. Support

**Every paying customer gets support. It is included in the price, at every paid tier, and
it runs over email.** There is no support product to buy separately and no tier that leaves
you on your own.

| Tier | Support | Target first response |
|---|---|---|
| Community | GitHub Issues, best effort | — |
| Commercial — Small / Medium | Email | 5 business days |
| Commercial — Large | Email | 3 business days |
| Commercial — Enterprise | Email, private channel | 2 business days |
| Redistribution — Standard | Email | 3 business days |
| Redistribution — Enterprise | Email, private channel | 2 business days |

What "support" means here, stated plainly so nothing is inferred:

- **Included:** installation and configuration problems, questions about intended behaviour,
  diagnosis of suspected bugs, guidance on using Orion for your case, and licensing or
  compliance questions.
- **A response commitment, not a fix commitment.** The target above is how quickly you get a
  human reply, not how quickly a defect is resolved. Confirmed bugs are prioritised over
  new features, but no repair window is guaranteed at any tier.
- **Not included:** building your workflow for you, writing features, or operating the
  software on your behalf. That is custom development — see §7.

---

## 7. Custom development

Anything that changes the software for you — a new feature, an integration, a format, a
connector, a bespoke build — is **never included in a licence fee**, at any tier.

It is **available on request and quoted separately**, per project:

1. You describe what you need.
2. You get a written scope, a fixed price and a delivery window before any work starts.
3. Nothing is invoiced until you accept that quote.

The indicative day rate for Orion is **€500 / day**, used to size a quote;
the quote itself is fixed-price, not time-and-materials.

Two things worth knowing before you ask:

- **A commercial licence is not required to commission work.** AGPL users can pay for
  custom development too.
- **By default the result is merged into the public project** under AGPL-3.0, which is why
  the rate is what it is. If you need it kept private, say so at quoting time: exclusive or
  unpublished work is priced differently.

---

## 8. How to buy

1. **Ask.** Write to **[marco.lombardo@gmail.com](mailto:marco.lombardo@gmail.com?subject=Orion%20commercial%20licence%20enquiry)**.
   Say what you intend to build, roughly how big your organisation is (for Commercial), or
   how the software will reach third parties (for Redistribution). Use email rather than a
   public issue: what you are building is usually not something you want indexed.
2. **Confirm the tier.** You get a written statement of which tier applies and why — for
   Commercial, the employee count that was used; for Redistribution, the factors from §4.2
   that were weighed — so there is no ambiguity later.
3. **Invoice.** Issued in EUR, payable by bank transfer within 30 days.
4. **Certificate.** On payment you receive a signed licence certificate naming your
   organisation (and, at Enterprise scope, every included legal entity), the tier, the term
   and the covered products. That certificate — not a key file — is the licence.

To get a concrete quote in one round instead of three, include: your **company** and the
legal entity that would hold the licence; the **intended use** (internal, or distributed to
third parties); **organisation size** or **distribution scale**, as applicable; the **tier**
you think fits; and whether you need **custom development**.

There is **no licence key, no activation, no phone-home.** The software behaves identically
whether or not you have paid. Compliance is contractual and self-declared; there is no
audit clause.

---

## 9. Term, warranty and liability

- **Term.** Annual from the invoice date, unless the certificate says otherwise, or
  perpetual where the perpetual option in §5 was purchased.
- **Updates.** Included for the duration of the term.
- **Warranty.** Orion is provided **as is**. No warranty of merchantability, fitness for a
  particular purpose, or non-infringement. Orion edits and rewrites PDF documents: read the [Disclaimer](README.md#disclaimer).
- **Liability.** Total aggregate liability under a commercial licence is limited to **the
  fees paid in the twelve months preceding the claim**. Liability is not excluded where it
  cannot lawfully be excluded — death or personal injury caused by negligence, fraud, or
  wilful misconduct.
- **Indemnity.** No IP indemnity at Commercial Small/Medium/Large or Redistribution
  Standard. Commercial Enterprise and Redistribution Enterprise may include one; ask, and
  it will be stated in the certificate.
- **Governing law.** Italian law, courts of Milan, unless the certificate names otherwise.

---

## 10. What is *not* included

Stated plainly, so nobody discovers it after paying:

- **No SLA on the software itself.** Response targets are commitments about replying to
  you, not about fixing anything within a window.
- **No custom development.** Quoted separately — see §7.
- **No guarantee of future features.** The roadmap is not a contract.
- **No exclusivity.** The same licence is available to your competitors.
- **No rights to third-party components.** See §11.
- **No hosted service.** Orion is a desktop application. There is nothing to sign
  into, and no document ever leaves the machine it is opened on.
- **No implied redistribution rights on a Commercial licence**, and no implied
  group-wide scope without an explicit Enterprise perimeter. See §3.

---

## 11. Third-party components

A commercial licence covers Orion's own code. Everything Orion is built on is
separately licensed by its own authors, and this licence cannot and does not
relicense any of it. §10 applies: no rights to third-party components are granted
here.

### The dependency that used to make this section a problem

Until recently Orion rendered and wrote PDFs with **MuPDF**, licensed by Artifex
under the AGPL-3.0 or a commercial licence of its own. Orion held no right to
sublicense it, so a Redistribution customer still received AGPL MuPDF and still
carried the AGPL's obligations — including its network clause — no matter what
they had paid here. That was a real limit on what this licence could deliver, and
it was stated as such.

**It no longer applies.** MuPDF has been replaced by pypdfium2 (Google's PDFium),
pypdf and reportlab, all permissively licensed. Nothing in Orion's dependencies
is copyleft any more except Qt, which is LGPL and has always been workable inside
a closed product.

### What Orion depends on

The five packages Orion requires, plus the interpreter it runs on and the tool
that freezes it, with the licence each declares in its own metadata at the
versions pinned in `requirements.txt`:

| Component | Licence | What it asks of you |
|---|---|---|
| Python, standard library | PSF-2.0 | Attribution. Nothing further. |
| pypdfium2 (PDFium) | BSD-3-Clause / Apache-2.0 | Reproduce the copyright notices in binary distributions. |
| pypdf | BSD-3-Clause | Reproduce the copyright notice in binary distributions. |
| reportlab | BSD-3-Clause | Reproduce the copyright notice in binary distributions. |
| Pillow | MIT-CMU (HPND) | Reproduce the copyright notice in binary distributions. |
| PyInstaller | GPL-2.0-or-later **with the Bootloader Exception** | Nothing. The exception grants unlimited permission to embed the bootloader in a combined program and distribute it without restriction — which is exactly what a frozen application does. |
| PySide6 / shiboken6 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | Under the LGPL option: ship the licence text, state that Qt is used, keep Qt replaceable by the recipient, and impose no further restriction on Qt itself. |

The PyPI wheels for PySide6 *are* the open-source build of Qt; their metadata
offers no commercial option. A Qt commercial licence is bought from The Qt
Company and is not something this licence, or a wheel, can grant.

### What a downloadable build actually contains

The table above is Orion's **source** dependency list. It is not what a
redistributor ships. A standalone build is a frozen bundle, and the bundle
contains the transitive closure of everything those packages link — Qt's own
libraries and plugins, the libraries Pillow vendors, and whatever the build
machine's linker resolved.

A Linux build contains **185 native binaries**. Every one of them is inventoried,
with the source of each licence determination, in
**[THIRD-PARTY-LICENSES.md](THIRD-PARTY-LICENSES.md)**, and the licence texts
themselves now ship inside the archive as `licenses/`. Grouped by what they
require:

| Class | What it asks of you |
|---|---|
| Permissive — MIT, BSD, ISC, Apache-2.0, Zlib, Unicode | Reproduce the notices. |
| Python and its extension modules — PSF-2.0 | Attribution. |
| Qt — LGPL-3.0 | Licence text, notice, and the recipient's ability to relink. |
| Other LGPL-2.1 / LGPL-2.0 libraries | The same, in their earlier form. |
| GCC runtime — GPL-3.0-or-later **with GCC Runtime Library Exception 3.1** | Nothing. The exception is what makes it distributable; without it a GPL-3 library would sit inside every build. |
| Microsoft Visual C++ and Universal CRT runtime (Windows) | Microsoft's own redistributable terms — **not an open-source licence**, and a different legal basis from every other row here. |

The published v1.0.0 archives had one more row than this, and it should not
have been there: `libreadline`, **GPL-3.0-or-later with no linking exception**,
collected by PyInstaller along with the standard library's optional `readline`
extension. A GPL-3 library inside an archive offered under this licence is the
one combination a Redistribution tier cannot survive. Nothing in Orion used it;
it is excluded from the build now, and a test fails if the exclusion is ever
removed. The `v1.0.0` tag was re-cut onto the fixed build, so the archives on
the releases page do not contain it — but a copy downloaded before that does,
and nothing about the file name distinguishes the two.

Counts change with the build. The inventory is regenerated from the archives at
each release rather than maintained by hand.

### Verify against what you ship

The determinations above and in THIRD-PARTY-LICENSES.md were made from package
metadata and from the build machine's own copyright records, and each entry names
its source so it can be re-checked. They are given in good faith, are current as
at the version of this document, and are **not a legal opinion**. Verify them
against the versions you actually ship.

---

## 12. Contributors

Contributions are accepted under the [Contributor License Agreement](CLA.md), which grants
the Project Owner the right to license contributed code under both AGPL-3.0 and commercial
terms. That grant is what makes dual licensing possible: without it, a single contributed
patch would block commercial licensing for everyone.

Contributors keep the copyright in their work, and receive a perpetual, royalty-free
commercial licence to Orion for their own use, as thanks.

---

## 13. Contact

**Commercial licensing, quotes and support for paying customers:
[marco.lombardo@gmail.com](mailto:marco.lombardo@gmail.com?subject=Orion%20commercial%20licence%20enquiry)**

For anything that is *not* a purchase — a bug, a feature request, a question about which
row of §1 you fall into — the [issue tracker](https://github.com/MarcoLombardoDev/Orion/issues) is the better channel, and the
answer helps whoever asks next.

---

## 14. Terminology

This document uses **Community**, **Commercial** and **Redistribution** as the three
licence families. **OEM** is deliberately not used as a top-level category: it appears only
as an example, because it describes one *scenario* within Redistribution, not a distinct
set of rights —

> OEM, embedded and other redistribution scenarios are covered by the Redistribution
> Licence.

Naming it this way keeps the category general enough to apply to whichever commercial
model a redistributor actually uses, instead of forcing OEM deals through a differently
worded licence than an equivalent embedding or hosting deal.

---

*This document is a commercial offer, not legal advice. Prices and terms may change for new
purchases; a licence already issued is governed by the certificate you hold, not by later
revisions of this file.*

*Copyright © 2026 Marco Lombardo. Orion is licensed under AGPL-3.0; commercial licensing is
available under the terms above.*
