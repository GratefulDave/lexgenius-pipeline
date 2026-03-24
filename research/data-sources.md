# LexGenius — Additional Data Sources for Mass Tort Intelligence

> **Purpose**: Comprehensive catalog of data sources to expand LexGenius pipeline coverage.
> **Last Updated**: 2026-03-23
> **Audience**: Engineering team implementing ingestion connectors

---

## Existing Pipeline Coverage

| Tier | Connector ID | Source | Status |
|------|-------------|--------|--------|
| Federal | `federal.fda.faers` | FDA Adverse Event Reporting System | ✅ Live |
| Federal | `federal.fda.maude` | FDA MAUDE (device adverse events) | ✅ Live |
| Federal | `federal.fda.recalls` | FDA Drug Enforcement/Recalls | ✅ Live |
| Federal | `federal.fda.dailymed` | DailyMed Drug Labels | ✅ Live |
| Federal | `federal.epa.enforcement` | EPA Enforcement Actions | ✅ Live |
| Federal | `federal.epa.comptox` | EPA CompTox Chemical Hazard Data | ✅ Live |
| Federal | `federal.sec.edgar` | SEC EDGAR Filings (10-K, 10-Q, 8-K) | ✅ Live |
| Federal | `federal.cpsc.recalls` | CPSC Consumer Product Recalls | ✅ Live |
| Federal | `federal.federal_register.notices` | Federal Register Documents | ✅ Live |
| Federal | `federal.nih.clinical_trials` | ClinicalTrials.gov | ✅ Live |
| Federal | `federal.nih.pubmed` | PubMed Literature | ✅ Live |
| Federal | `federal.congress.legislation` | Congress.gov Bills | ✅ Live |
| Federal | `federal.usgs.water_quality` | USGS Water Quality Data | ✅ Live |
| Federal | `federal.cdc.*` | CDC | 🔲 Placeholder |
| Federal | `federal.ftc.*` | FTC | 🔲 Placeholder |
| Federal | `federal.nhtsa.*` | NHTSA | 🔲 Placeholder |
| Federal | `federal.doj.*` | DOJ | 🔲 Placeholder |
| Federal | `federal.osha.*` | OSHA | 🔲 Placeholder |
| Judicial | `judicial.courtlistener` | CourtListener Opinions | ✅ Live |
| Judicial | `judicial.pacer.rss` | PACER Federal Dockets | 🔲 Stub (no auth) |
| Judicial | `judicial.regulations_gov` | Regulations.gov Documents | ✅ Live |
| Commercial | `commercial.news_rss` | Reuters/AP/NYT/WSJ/CNN RSS | ✅ Live |
| Commercial | `commercial.google_news` | Google News RSS | ✅ Live |
| Commercial | `commercial.exa_research` | Exa AI Semantic Search | ✅ Live |
| State | `state.*.courts` | State Courts (template only) | 🔲 Template |

### Critical Gaps

1. **JPML / MDL assignment data** — zero coverage
2. **Class action settlement databases** — zero coverage
3. **State court filings** — template only, no implementations
4. **FDA safety communications** — not ingested
5. **Legal industry news** (Law360, JD Supra) — not ingested
6. **Attorney general actions** — zero coverage
7. **Insurance industry signals** — zero coverage
8. **Plaintiff forum / social media intelligence** — zero coverage
9. **International mass tort equivalents** — zero coverage
10. **FTC/CDC/NHTSA/DOJ/OSHA** — all placeholders, none implemented

---

## 1. Federal Court Systems

### 1.1 JPML (Judicial Panel on Multidistrict Litigation)

| Attribute | Detail |
|-----------|--------|
| **What it is** | Centralizes pretrial proceedings for civil actions with common questions of fact |
| **Type** | Website scrape + PDF parsing |
| **Cost** | Free (public records) |
| **Technical difficulty** | Medium — requires jpml.gov scraping, PDF parsing for transfer orders |

**Data provided**: New MDL transfer orders, petitions for coordination, assigned judges/transferee districts, plaintiff count ranges, case types, product/drug names, bellwether trial orders, termination orders.

**Access**:
- Website: `https://www.jpml.gov/` — transfer orders, hearing schedules, pending petitions
- PDF parsing: Transfer orders published as structured PDFs
- Email alerts: JPML offers email notifications (ingestable via monitored inbox)

**Value**: ⭐⭐⭐⭐⭐ **Highest priority**. MDL transfer orders are the single most important early signal that a mass tort is forming.

**Connector ID**: `judicial.jpml.transfer_orders`

---

### 1.2 PACER / CM/ECF (Full Implementation)

| Attribute | Detail |
|-----------|--------|
| **What it is** | Official federal court electronic filing system |
| **Type** | PACER API + CourtListener RECAP proxy |
| **Cost** | $0.10/page PACER (cap $3/doc); RECAP/CourtListener free |
| **Technical difficulty** | High — auth complexity, aggressive rate limits |

**Data provided**: Complete federal docket sheets, new case filings with party/law firm info, motion practice, hearing dates, MDL tag numbers, attorney contact info.

**Access**:
- PACER Case Locator API: `https://pacer.uscourts.gov/pacercaselocator/`
- CourtListener RECAP API: `https://www.courtlistener.com/api/rest/v4/`
- Python library: `pacer` package (community-maintained)

**Value**: ⭐⭐⭐⭐⭐ Direct access to who is filing what in federal court.

**Connector ID**: `judicial.pacer.dockets` (upgrade from stub)

---

### 1.3 CourtListener (Expanded Coverage)

| Attribute | Detail |
|-----------|--------|
| **What it is** | Free nonprofit federal court data — currently only opinions ingested |
| **Type** | REST API |
| **Cost** | Free (10 req/min unauthenticated, 100/min with key) |
| **Technical difficulty** | Low — well-documented, partially implemented |

**Untapped data**: `/dockets/` (docket metadata), `/docket-entries/` (every filing), `/people/` and `/attorneys/` (lawyer/firm tracking), `/search/` (full-text docket search), oral argument audio.

**Value**: ⭐⭐⭐⭐⭐ Docket entries and attorney tracking are core intelligence.

**Connector IDs**: `judicial.courtlistener.dockets` (new), expand existing `judicial.courtlistener`

---

### 1.4 Federal Judicial Center (FJC) Integrated Database

| Attribute | Detail |
|-----------|--------|
| **Type** | Bulk download (formal request) |
| **Cost** | Free (request-based) |
| **Technical difficulty** | Low once obtained — CSV/flat files |

**Data provided**: Civil case opening/termination data by nature of suit, settlement patterns, time-to-trial, MDL statistics.

**Access**: `https://www.fjc.gov/research/idb`

**Value**: ⭐⭐⭐⭐ Macro trend analysis and market sizing.

**Connector ID**: `federal.fjc.idb` (quarterly bulk import)

---

## 2. MDL / Class Action Specific Sources

### 2.1 MultiDistrictLitigation.com

| Attribute | Detail |
|-----------|--------|
| **Type** | Web scrape |
| **Cost** | Free |
| **Technical difficulty** | Medium |

**Data provided**: Active MDL listings with case counts, bellwether trial dates/outcomes, settlement announcements, lead counsel, key orders, plaintiff eligibility.

**Access**: `https://multidistrictlitigation.com/`

**Value**: ⭐⭐⭐⭐ Consolidated MDL status tracking. Secondary source complementing JPML.

**Connector ID**: `commercial.mdl_tracker`

---

### 2.2 ClassAction.org

| Attribute | Detail |
|-----------|--------|
| **Type** | Web scrape + possible RSS |
| **Cost** | Free |
| **Technical difficulty** | Low-Medium |

**Data provided**: Active settlements with claim deadlines, fund amounts, claimant counts, fairness hearing dates, settlement administrators.

**Access**: `https://www.classaction.org/`

**Value**: ⭐⭐⭐⭐ Settlement claim deadlines reveal underserved plaintiff populations.

**Connector ID**: `commercial.classaction_org`

---

### 2.3 Stanford Class Action Clearinghouse

| Attribute | Detail |
|-----------|--------|
| **Type** | Web scrape |
| **Cost** | Free |
| **Technical difficulty** | Medium |

**Data provided**: Extensive database of class action settlements, settlement agreements, fairness hearing notices, consent decrees, judicial opinions.

**Access**: `https://law.stanford.edu/class-action-clearinghouse/`

**Value**: ⭐⭐⭐⭐ Historical settlement data for benchmarking and market analysis.

**Connector ID**: `commercial.stanford_clearinghouse`

---

### 2.4 CFPB Enforcement Actions

| Attribute | Detail |
|-----------|--------|
| **Type** | RSS feed + bulk data |
| **Cost** | Free |
| **Technical difficulty** | Low |

**Data provided**: Enforcement press releases, consent orders, consumer complaint trends, civil penalty fund data.

**Access**:
- RSS: `https://www.consumerfinance.gov/policy-compliance/enforcement/rss/`
- Complaints: `https://www.consumerfinance.gov/data-research/consumer-complaints/`

**Value**: ⭐⭐⭐⭐ CFPB enforcement often precedes private class actions.

**Connector ID**: `federal.cfpb.enforcement`

---

## 3. FDA / Regulatory (Additional Sources)

### 3.1 FDA Drug Safety Communications

| Attribute | Detail |
|-----------|--------|
| **Type** | RSS feed |
| **Cost** | Free |
| **Technical difficulty** | Low |

**Data provided**: Safety warnings, black box warning additions, FDA safety reviews, post-market study requirements, REMS announcements.

**Access**: `https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/drug-safety-communications`

**Value**: ⭐⭐⭐⭐⭐ Strongest early signal for pharma mass torts. Black box warnings trigger filing floods.

**Connector ID**: `federal.fda.safety_communications`

---

### 3.2 FDA MedWatch Safety Alerts

| Attribute | Detail |
|-----------|--------|
| **Type** | RSS feed |
| **Cost** | Free |
| **Technical difficulty** | Low |

**Data provided**: Drug/device/biologic safety alerts, dietary supplement warnings, recall notices.

**Access**: `https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/medwatch-safety-alerts`

**Value**: ⭐⭐⭐⭐ Supplements FAERS and recall connectors with real-time notifications.

**Connector ID**: `federal.fda.medwatch`

---

### 3.3 FDA 510(k) / PMA Device Pre-Market Data

| Attribute | Detail |
|-----------|--------|
| **Type** | OpenFDA REST API |
| **Cost** | Free |
| **Technical difficulty** | Low |

**Data provided**: Device clearances (510(k)), approvals (PMA), modifications/supplements, post-approval study requirements.

**Access**: 510(k): `https://api.fda.gov/device/510k.json` | PMA: `https://api.fda.gov/device/pma.json`

**Value**: ⭐⭐⭐⭐ Critical for device mass torts. Approval history and post-approval studies signal safety concerns.

**Connector ID**: `federal.fda.device_510k`

---

### 3.4 FDA Advisory Committee Meetings

| Attribute | Detail |
|-----------|--------|
| **Type** | Website scrape + PDF parsing |
| **Cost** | Free |
| **Technical difficulty** | Medium |

**Data provided**: Meeting schedules, FDA briefing documents (safety analyses), committee votes, transcripts, post-meeting action letters.

**Access**: `https://www.fda.gov/advisory-committees/advisory-committee-calendar`

**Value**: ⭐⭐⭐⭐ Committee safety concern votes are strong litigation signals.

**Connector ID**: `federal.fda.advisory_committees`

---

### 3.5 FDA Warning Letters

| Attribute | Detail |
|-----------|--------|
| **Type** | RSS + web scrape |
| **Cost** | Free |
| **Technical difficulty** | Low |

**Data provided**: Warning letters for marketing violations, manufacturing deficiencies, GMP violations, clinical trial irregularities.

**Access**: `https://www.fda.gov/drugs/guidance-compliance-regulatory-information/warning-letters-drug`

**Value**: ⭐⭐⭐ Reveals manufacturing/promotional issues that may lead to product liability claims.

**Connector ID**: `federal.fda.warning_letters`

---

### 3.6 NHTSA Recalls, Complaints & Defect Investigations

| Attribute | Detail |
|-----------|--------|
| **Type** | REST API + bulk download |
| **Cost** | Free |
| **Technical difficulty** | Low-Medium |

**Data provided**: Vehicle recalls, consumer complaints (ORE), defect investigations (PE → EA), TSBs, recall completion rates, civil penalties.

**Access**:
- Recalls: `https://api.nhtsa.gov/recalls/recallsByVehicle`
- Complaints: `https://api.nhtsa.gov/complaints/`
- Investigations: `https://www.nhtsa.gov/equipment/defect-investigations`

**Value**: ⭐⭐⭐⭐ Essential for automotive product liability. Complaint spikes precede recalls and litigation.

**Connector IDs**: `federal.nhtsa.recalls`, `federal.nhtsa.complaints`, `federal.nhtsa.investigations`

---

### 3.7 EPA ECHO (Enforcement & Compliance History Online)

| Attribute | Detail |
|-----------|--------|
| **Type** | REST API + bulk download |
| **Cost** | Free |
| **Technical difficulty** | Medium |

**Data provided**: Facility-level compliance status, inspection reports, enforcement actions, penalties, TRI data per facility, permit violations.

**Access**: `https://echo.epa.gov/`

**Value**: ⭐⭐⭐⭐ Critical for environmental torts. Facility compliance data supports mass tort claims.

**Connector ID**: `federal.epa.echo`

---

### 3.8 EPA TRI (Toxics Release Inventory)

| Attribute | Detail |
|-----------|--------|
| **Type** | Bulk download (annual) |
| **Cost** | Free |
| **Technical difficulty** | Low |

**Data provided**: Annual toxic release quantities by facility, chemical identity/CAS numbers, waste management methods, off-site transfers.

**Access**: `https://www.epa.gov/toxics-release-inventory-tri-program/tri-data-reports`

**Value**: ⭐⭐⭐⭐ Foundation for environmental exposure torts. Release spikes are strong litigation signals.

**Connector ID**: `federal.epa.tri`

---

### 3.9 OSHA Inspection & Citation Data

| Attribute | Detail |
|-----------|--------|
| **Type** | REST API + bulk download |
| **Cost** | Free |
| **Technical difficulty** | Low |

**Data provided**: Inspection reports, citations with penalties, fatality/catastrophe reports, accident investigation summaries, violation types.

**Access**: `https://www.osha.gov/ords/imis/establishment` | Bulk: `https://www.osha.gov/ogate/open-government-data`

**Value**: ⭐⭐⭐ Relevant for workplace exposure / toxic tort cases.

**Connector ID**: `federal.osha.inspections`

---

### 3.10 CDC WONDER / Environmental Public Health Tracking

| Attribute | Detail |
|-----------|--------|
| **Type** | API + bulk data |
| **Cost** | Free |
| **Technical difficulty** | Low-Medium |

**Data provided**: Mortality data by cause (ICD-10), disease incidence rates, cancer registry data, environmental health indicators by county.

**Access**: CDC WONDER: `https://wonder.cdc.gov/` | EPHT: `https://ephtracking.cdc.gov/`

**Value**: ⭐⭐⭐ Epidemiological data supporting causation in toxic/pharmaceutical torts.

**Connector ID**: `federal.cdc.wonder`

---

### 3.11 USDA FSIS Food Safety Recalls

| Attribute | Detail |
|-----------|--------|
| **Type** | RSS |
| **Cost** | Free |
| **Technical difficulty** | Low |

**Data provided**: Food recalls, contamination events, public health alerts, enforcement actions against food producers.

**Access**: `https://www.fsis.usda.gov/recalls`

**Value**: ⭐⭐⭐ Relevant for foodborne illness and contamination class actions.

**Connector ID**: `federal.usda.recalls`

---

## 4. State Court Systems

### 4.1 Priority State Court Implementations

| Attribute | Detail |
|-----------|--------|
| **Type** | Web scrape / API (varies by state) |
| **Cost** | Free (MO, DE) to $0.10-0.50/page (CA, TX, NY) |
| **Technical difficulty** | Very High (50+ different systems) |

**Priority order**:

1. **Missouri (Case.net)** — Free public access, highest mass tort filing volume (St. Louis juries plaintiff-friendly). Tracks state-level case coordination.
2. **Delaware (CourtConnect)** — Free public web access. Key for corporate/securities class actions.
3. **California (CCMS/eCourt)** — Largest state system. Massive tort volume.
4. **Texas (re:SearchTX)** — High volume, Odyssey-based. Some API access.
5. **New Jersey (eCourts)** — Consumer class actions; public web access.
6. **Florida (OSCAR)** — Many mass tort filings; limited but usable public access.
7. **New York (NYSCEF)** — Registration required but free; web-scrapeable.

**Value**: ⭐⭐⭐⭐⭐ State courts see enormous tort volumes (talc, Roundup, hernia mesh). Many cases never reach federal court. Major competitive gap.

**Connector IDs**: `state.mo.courts` → `state.de.courts` → `state.ca.courts` → ...

---

### 4.2 NCSC Court Statistics

| Attribute | Detail |
|-----------|--------|
| **Type** | Published reports (PDF) |
| **Cost** | Free |
| **Technical difficulty** | Low (PDF parsing) |

**Data provided**: Civil case filing statistics by state, trend data on tort filings.

**Access**: `https://www.ncsc.org/` — Court Statistics Project.

**Value**: ⭐⭐⭐ Market sizing and trend analysis.

**Connector ID**: `judicial.ncsc.statistics`

---

## 5. Attorney General Actions

### 5.1 NAAG (National Association of Attorneys General)

| Attribute | Detail |
|-----------|--------|
| **Type** | Website scrape + email alerts |
| **Cost** | Free |
| **Technical difficulty** | Medium |

**Data provided**: Multistate AG settlements, individual AG enforcement actions, press releases, settlement amounts.

**Access**: `https://www.naag.org/`

**Value**: ⭐⭐⭐⭐ AG settlements often set templates for private class actions.

**Connector ID**: `federal.naag.actions`

---

### 5.2 Individual State AG Press Releases

| Attribute | Detail |
|-----------|--------|
| **Type** | RSS / website scrape (per state) |
| **Cost** | Free |
| **Technical difficulty** | Medium-High (50 states) |

**Data provided**: State-level enforcement actions, consumer protection lawsuits, pharma settlements, environmental enforcement.

**Strategy**: Start with high-activity states (CA, NY, TX, IL, MA, PA, FL). Most AG offices publish via RSS or email alerts.

**Value**: ⭐⭐⭐⭐ State AG investigations into drugs often precede mass tort filings.

**Connector ID**: `state.*.ag_actions` (top 10 states first)

---

## 6. DOJ / Federal Law Enforcement

### 6.1 DOJ Press Releases

| Attribute | Detail |
|-----------|--------|
| **Type** | RSS feed |
| **Cost** | Free |
| **Technical difficulty** | Low |

**Data provided**: Criminal/civil enforcement actions, fraud indictments, False Claims Act settlements, antitrust actions, environmental crime prosecutions.

**Access**: `https://www.justice.gov/news/rss`

**Value**: ⭐⭐⭐⭐ DOJ enforcement often precedes or accompanies private mass tort litigation.

**Connector ID**: `federal.doj.press_releases`

---

### 6.2 DOJ False Claims Act Settlements

| Attribute | Detail |
|-----------|--------|
| **Type** | Website scrape |
| **Cost** | Free |
| **Technical difficulty** | Medium |

**Data provided**: FCA settlement amounts, defendants, whistleblower involvement, fraud type (healthcare, defense, etc.).

**Access**: `https://www.justice.gov/opa/pr/false-claims-act-statistics`

**Value**: ⭐⭐⭐⭐ Healthcare FCA settlements often parallel product liability and off-label promotion mass torts.

**Connector ID**: `federal.doj.fca_settlements`

---

## 7. FTC Actions

### 7.1 FTC Enforcement Actions

| Attribute | Detail |
|-----------|--------|
| **Type** | RSS + website |
| **Cost** | Free |
| **Technical difficulty** | Low |

**Data provided**: Consumer protection enforcement, data privacy enforcement, competition actions, consent orders, penalty amounts.

**Access**: RSS: `https://www.ftc.gov/news-events/press-releases` | Cases: `https://www.ftc.gov/enforcement/cases-proceedings`

**Value**: ⭐⭐⭐⭐ FTC enforcement increasingly overlaps with mass tort areas (social media harm, data breaches, deceptive drug/device marketing).

**Connector ID**: `federal.ftc.enforcement`

---

## 8. Insurance Industry Data

### 8.1 NAIC (National Association of Insurance Commissioners)

| Attribute | Detail |
|-----------|--------|
| **Type** | Database query + published reports |
| **Cost** | Free (some restricted) |
| **Technical difficulty** | Medium |

**Data provided**: Insurance company financial data, complaint records, market conduct examinations, rate filings.

**Access**: `https://www.naic.org/` — ADMM portal.

**Value**: ⭐⭐⭐ Insurance financial stress signals can indicate expected future litigation costs.

**Connector ID**: `commercial.naic.insurance`

---

### 8.2 Insurance Reserve Increases via SEC Filings

| Attribute | Detail |
|-----------|--------|
| **Type** | NLP analysis of existing SEC EDGAR data |
| **Cost** | Free (enhances existing connector) |
| **Technical difficulty** | Medium (requires NLP/LLM analysis) |

**Data provided**: Insurance company reserve adjustments in 10-K/10-Q filings. Keywords: "adverse development," "reserve strengthening," specific product/drug liability lines.

**Value**: ⭐⭐⭐⭐ Reserve increases are leading indicators of anticipated mass tort settlements.

**Implementation**: Add NLP analysis layer to existing `federal.sec.edgar` connector.

---

## 9. Legal News & Litigation Tracking Services

### 9.1 Law360 Mass Tort / Class Action Sections

| Attribute | Detail |
|-----------|--------|
| **Type** | Website scrape (paywalled) |
| **Cost** | $$$$ (enterprise subscription ~$3,000-10,000/yr) |
| **Technical difficulty** | High — paywall, anti-scrape measures |

**Data provided**: Breaking news on MDL transfers, settlements, bellwether trials, lead counsel appointments, judicial rulings. Industry-standard legal news.

**Access**: `https://www.law360.com/`

**ToS considerations**: Paywalled content; scraping may violate ToS. RSS headlines available (no full text).

**Value**: ⭐⭐⭐⭐ The gold standard for legal news. Headlines alone are valuable signals even without full text.

**Connector ID**: `commercial.law360_headlines` (headlines only via RSS/surface scraping)

---

### 9.2 JD Supra

| Attribute | Detail |
|-----------|--------|
| **Type** | RSS + website |
| **Cost** | Free |
| **Technical difficulty** | Low |

**Data provided**: Legal alerts, case summaries, and law firm articles about mass tort developments. Often the fastest source for new case filing analysis.

**Access**: `https://www.jdsupra.com/` — RSS available by topic/practice area.

**Value**: ⭐⭐⭐⭐ Free legal intelligence from plaintiff-side firms advertising their involvement in new torts.

**Connector ID**: `commercial.jdsupra_mass_tort`

---

### 9.3 LexisNexis / Westlaw (Commercial)

| Attribute | Detail |
|-----------|--------|
| **Type** | Commercial API |
| **Cost** | $$$$$ ($$$+ per seat/month) |
| **Technical difficulty** | Medium (well-documented APIs) |

**Data provided**: Comprehensive legal research, case law, court filings, analytical materials, litigation analytics.

**Access**: LexisNexis API (`https://developers.lexisnexis.com/`), Westlaw API.

**Value**: ⭐⭐⭐⭐⭐ Comprehensive but very expensive. Likely not viable for a startup pipeline until revenue justifies it.

**Connector ID**: `commercial.lexisnexis` (deferred — cost-prohibitive for MVP)

---

### 9.4 Bloomberg Law

| Attribute | Detail |
|-----------|--------|
| **Type** | Commercial subscription |
| **Cost** | $$$$$ |
| **Technical difficulty** | Medium |

**Data provided**: Litigation analytics, court docket tracking, news, regulatory analysis, law firm financial data.

**Access**: `https://www.bloomberglaw.com/`

**Value**: ⭐⭐⭐⭐ Similar to LexisNexis — comprehensive but expensive. Defer until post-revenue.

**Connector ID**: `commercial.bloomberg_law` (deferred)

---

### 9.5 ClassActionRealm / TopClassActions.com

| Attribute | Detail |
|-----------|--------|
| **Type** | Website scrape |
| **Cost** | Free |
| **Technical difficulty** | Medium |

**Data provided**: Open class action settlements, claim filing deadlines, settlement fund details, consumer-facing litigation news.

**Access**: `https://topclassactions.com/` — consumer-facing site.

**Value**: ⭐⭐⭐⭐ Consumer-facing sites reveal which settlements are seeking claimants — direct lead generation intelligence.

**Connector ID**: `commercial.topclassactions`

---

### 9.6 AboutLawsuits.com / Mass Tort Nexus

| Attribute | Detail |
|-----------|--------|
| **Type** | Website scrape |
| **Cost** | Free |
| **Technical difficulty** | Medium |

**Data provided**: Mass tort news, active litigation updates, settlement information, drug/device case developments. Often plaintiff-firm oriented.

**Access**: `https://www.aboutlawsuits.com/`, `https://www.masstortnexus.com/`

**Value**: ⭐⭐⭐⭐ Plaintiff-firm oriented content reveals which firms are positioning themselves in emerging torts.

**Connector ID**: `commercial.aboutlawsuits`

---

## 10. Social Media / Plaintiff Forums

### 10.1 Reddit (r/lawsuit, r/legaladvice, drug-specific subreddits)

| Attribute | Detail |
|-----------|--------|
| **Type** | Reddit API |
| **Cost** | Free (Reddit API) |
| **Technical difficulty** | Medium |

**Data provided**: Plaintiff discussions about potential lawsuits, side effects, defective products. Subreddits like `r/lawsuit`, `r/legaladvice`, drug-specific communities (e.g., `r/roundup`, `r/talc`).

**Access**: Reddit API (`https://www.reddit.com/dev/api/`) — OAuth2 authentication required.

**Value**: ⭐⭐⭐⭐ Reddit is a leading indicator of plaintiff sentiment. Discussion spikes about side effects or product defects often precede formal legal action by 3-12 months.

**Connector ID**: `commercial.reddit_forums`

---

### 10.2 Facebook Groups (Legal Help / Class Action / Drug-Specific)

| Attribute | Detail |
|-----------|--------|
| **Type** | Facebook Graph API (restricted) |
| **Cost** | Free (API access limited) |
| **Technical difficulty** | High — API restrictions, anti-bot measures |

**Data provided**: Large plaintiff groups discussing potential lawsuits, sharing legal referrals, organizing class actions.

**Access**: Facebook Graph API — heavily restricted since 2018 changes. Group content access is limited.

**Value**: ⭐⭐⭐ Massive plaintiff communities but access is technically difficult. May require manual monitoring or third-party tools.

**Connector ID**: `commercial.facebook_groups` (deferred — API restrictions)

---

### 10.3 Twitter/X (Legal Hashtags, Attorney Accounts)

| Attribute | Detail |
|-----------|--------|
| **Type** | X API |
| **Cost** | $$ (X API pricing tiers) |
| **Technical difficulty** | Medium |

**Data provided**: Real-time legal news, attorney commentary on new filings, judicial announcements, case developments.

**Access**: X API v2 — `https://developer.x.com/` — Free tier limited to 1,500 tweets/month.

**Value**: ⭐⭐⭐⭐ Fastest source for breaking legal news. Plaintiff attorneys often announce new cases on Twitter first.

**Connector ID**: `commercial.twitter_legal`

---

### 10.4 Google Trends

| Attribute | Detail |
|-----------|--------|
| **Type** | REST API (unofficial) / scraping |
| **Cost** | Free |
| **Technical difficulty** | Medium |

**Data provided**: Search interest over time for drug names + "lawsuit," "side effects," "recall." Geographic breakdown by state/MSA.

**Access**: `https://trends.google.com/trends/` — unofficial Python library `pytrends`.

**Value**: ⭐⭐⭐⭐ Search interest spikes for "drug name + lawsuit" are leading indicators of mass tort formation. Geographic data shows where demand is highest.

**Connector ID**: `commercial.google_trends`

---

### 10.5 Drugs.com / WebMD Forums

| Attribute | Detail |
|-----------|--------|
| **Type** | Web scrape |
| **Cost** | Free |
| **Technical difficulty** | Medium |

**Data provided**: Patient reviews and forum discussions about drug side effects, device complications, adverse experiences. Drugs.com has structured reviews with severity ratings.

**Access**:
- `https://www.drugs.com/comments/` — drug reviews with side effect frequency data
- `https://forums.webmd.com/` — health forums

**Value**: ⭐⭐⭐⭐ Patient-reported side effects often precede FAERS reports and legal filings. Review sentiment and volume spikes are early warning signals.

**Connector ID**: `commercial.drugsdotcom_reviews`

---

## 11. Academic / Research Databases

### 11.1 AHRQ (Agency for Healthcare Research and Quality)

| Attribute | Detail |
|-----------|--------|
| **Type** | API + bulk download |
| **Cost** | Free |
| **Technical difficulty** | Medium |

**Data provided**: Hospital discharge data (HCUP), patient safety indicators, healthcare cost/utilization data, medical expenditure surveys.

**Access**: `https://www.ahrq.gov/data/dataresources.html` — HCUP data requires data use agreement.

**Value**: ⭐⭐⭐ Hospital admission spikes for specific conditions can indicate drug/device safety issues.

**Connector ID**: `federal.ahrq.hcup`

---

### 11.2 SEER (Surveillance, Epidemiology, and End Results) — NCI

| Attribute | Detail |
|-----------|--------|
| **Type** | API + bulk download |
| **Cost** | Free (registration required) |
| **Technical difficulty** | Medium |

**Data provided**: Population-based cancer incidence and survival data. Essential for pharmaceutical mass torts involving cancer (e.g., Zantac/NDMA, talc/ovarian cancer).

**Access**: `https://seer.cancer.gov/` — SEER*Stat software for queries; API available.

**Value**: ⭐⭐⭐⭐ Cancer incidence rate data is foundational for pharma mass tort causation analysis. Zantac/NDMA litigation heavily relied on SEER data.

**Connector ID**: `federal.nih.seer`

---

### 11.3 Social Science Research Network (SSRN)

| Attribute | Detail |
|-----------|--------|
| **Type** | Website scrape / RSS |
| **Cost** | Free |
| **Technical difficulty** | Low |

**Data provided**: Pre-publication legal scholarship on mass torts, class actions, empirical studies of litigation outcomes.

**Access**: `https://www.ssrn.com/` — RSS by topic.

**Value**: ⭐⭐ Academic research identifying emerging liability theories before they reach courts.

**Connector ID**: `commercial.ssrn`

---

### 11.4 National Law Review

| Attribute | Detail |
|-----------|--------|
| **Type** | RSS feed |
| **Cost** | Free |
| **Technical difficulty** | Low |

**Data provided**: Legal analysis articles on new cases, regulatory changes, compliance issues, industry-specific legal developments.

**Access**: `https://www.natlawreview.com/` — RSS available.

**Value**: ⭐⭐⭐ Good secondary source for legal analysis of emerging litigation.

**Connector ID**: `commercial.national_law_review`

---

## 12. Industry-Specific Sources

### 12.1 Pharmaceutical / Life Sciences

#### FDA Orange Book (Approved Drug Products)

| Attribute | Detail |
|-----------|--------|
| **Type** | Download (PDF/Excel) + API |
| **Cost** | Free |
| **Technical difficulty** | Low |

**Data provided**: Approved drug products with therapeutic equivalence evaluations, patent information, exclusivity dates.

**Access**: `https://www.accessdata.fda.gov/scripts/cder/ob/default.cfm` | Downloadable data files.

**Value**: ⭐⭐⭐ Patent/exclusivity expirations can trigger generic competition and associated mass tort opportunities.

**Connector ID**: `federal.fda.orange_book`

---

#### European Medicines Agency (EMA) — PSURs / Safety Updates

| Attribute | Detail |
|-----------|--------|
| **Type** | Website + API |
| **Cost** | Free |
| **Technical difficulty** | Medium |

**Data provided**: Periodic Safety Update Reports (PSURs), risk management plans, referral procedures, safety referrals for drugs sold in EU.

**Access**: `https://www.ema.europa.eu/` — some data via API.

**Value**: ⭐⭐⭐⭐ EMA safety signals often precede FDA action on drugs sold in both markets. Early warning from EU.

**Connector ID**: `international.ema.safety`

---

#### MHRA (UK Medicines and Healthcare products Regulatory Agency)

| Attribute | Detail |
|-----------|--------|
| **Type** | Website + Yellow Card data |
| **Cost** | Free |
| **Technical difficulty** | Medium |

**Data provided**: Drug safety alerts, Yellow Card adverse event reports (UK equivalent of FAERS), device safety notices.

**Access**: `https://www.gov.uk/government/organisations/mhra`

**Value**: ⭐⭐⭐ UK safety signals sometimes precede US action. Yellow Card data is publicly accessible.

**Connector ID**: `international.mhra.yellow_card`

---

#### ClinicalTrials.gov (Expanded — Protocol Amendments, Terminations)

Already ingested, but additional use cases:
- **Clinical trial terminations**: Trials stopped for safety reasons are strong signals
- **Protocol amendments**: Amendments adding new safety monitoring suggest emerging concerns
- **Enrollment suspensions**: Halts for safety review

**Enhancement**: Add monitoring for trial status changes (terminated, suspended) and protocol amendments.

**Connector ID**: Enhance existing `federal.nih.clinical_trials`

---

### 12.2 Medical Device

#### FDA Device Recall Database (Expand Existing)

Already partially covered by `federal.fda.recalls` but that connector is drug-focused. Need device-specific recall connector.

| Attribute | Detail |
|-----------|--------|
| **Type** | OpenFDA API |
| **Cost** | Free |
| **Technical difficulty** | Low |

**Data provided**: Medical device recall data including reason, classification (I/II/III), affected lot numbers, distribution quantities.

**Access**: `https://api.fda.gov/device/recall.json`

**Value**: ⭐⭐⭐⭐ Device recall Class I recalls are immediate mass tort signals.

**Connector ID**: `federal.fda.device_recalls`

---

#### FDA Manufacturer and User Facility Device Experience (MAUDE) — Expanded

Already ingested but could be enhanced:
- **Correlation analysis**: Track adverse event volume trends per device over time
- **Event type filtering**: Focus on "malfunction" vs "injury" vs "death"
- **Manufacturer response patterns**: Manufacturers who delay reporting are liability risks

**Enhancement**: Add trend analysis to existing `federal.fda.maude` connector.

---

#### EU Medical Device Regulation (MDR) Vigilance Database

| Attribute | Detail |
|-----------|--------|
| **Type** | Website (Eudamed) |
| **Cost** | Free (limited public access) |
| **Technical difficulty** | High |

**Data provided**: European device safety data, field safety notices, vigilance reports.

**Access**: `https://ec.europa.eu/health/documents/eudamed_en` — public access limited.

**Value**: ⭐⭐⭐ European device safety signals that may precede US action.

**Connector ID**: `international.eu.mdr_vigilance`

---

### 12.3 Environmental / Toxic Tort

#### ATSDR (Agency for Toxic Substances and Disease Registry)

| Attribute | Detail |
|-----------|--------|
| **Type** | Website + publications |
| **Cost** | Free |
| **Technical difficulty** | Medium |

**Data provided**: Toxicological profiles for chemicals, health assessments for contaminated sites, exposure investigations, public health assessments.

**Access**: `https://www.atsdr.cdc.gov/` — Toxicological Profiles searchable by chemical.

**Value**: ⭐⭐⭐⭐ ATSDR health assessments for contaminated sites are foundational evidence in environmental torts (Camp Lejeune, PFAS, etc.).

**Connector ID**: `federal.atsdr.health_assessments`

---

#### EPA Superfund / NPL (National Priorities List)

| Attribute | Detail |
|-----------|--------|
| **Type** | Website + database |
| **Cost** | Free |
| **Technical difficulty** | Medium |

**Data provided**: Superfund site listings, contamination types, responsible parties, cleanup progress, health risk assessments, cost recovery actions.

**Access**: `https://www.epa.gov/superfund/national-priorities-list-npl-sites` | SEMS database.

**Value**: ⭐⭐⭐⭐ Superfund sites are environmental tort epicenters. New NPL listings or cost recovery actions signal potential mass torts.

**Connector ID**: `federal.epa.superfund`

---

#### EWG (Environmental Working Group) Databases

| Attribute | Detail |
|-----------|--------|
| **Type** | Website / data downloads |
| **Cost** | Free |
| **Technical difficulty** | Low-Medium |

**Data provided**: Tap Water Database (contaminants by zip code), Skin Deep (cosmetic ingredient safety), Farm Subsidy Database, PFAS contamination map.

**Access**: `https://www.ewg.org/`

**Value**: ⭐⭐⭐⭐ EWG's PFAS and tap water contamination maps are widely cited in environmental mass torts. Direct exposure data.

**Connector ID**: `commercial.ewg_contamination`

---

### 12.4 Consumer Products

#### CPSC SaferProducts.gov — Consumer Complaints (Expanded)

Already have recalls (`federal.cpsc.recalls`) but not consumer complaint data.

| Attribute | Detail |
|-----------|--------|
| **Type** | REST API |
| **Cost** | Free |
| **Technical difficulty** | Low |

**Data provided**: Consumer-submitted reports of product injuries and hazards. Real-time consumer injury reports.

**Access**: `https://www.saferproducts.gov/RestWebServices/Recall` — includes consumer reports.

**Value**: ⭐⭐⭐⭐ Consumer complaint spikes are leading indicators for product recalls and litigation.

**Connector ID**: `federal.cpsc.consumer_reports`

---

#### Consumer Product Safety Databases (International)

| Attribute | Detail |
|-----------|--------|
| **Type** | Website / RSS |
| **Cost** | Free |
| **Technical difficulty** | Medium |

**Data provided**:
- **RAPEX (EU)**: Rapid Alert System for dangerous non-food products — `https://ec.europa.eu/safety-gate/`
- **Health Canada Recalls**: `https://www.canada.ca/en/health-canada/services/consumer-product-safety.html`
- **ACCC (Australia)**: Product Safety recalls — `https://www.productsafety.gov.au/`

**Value**: ⭐⭐⭐ International recall alerts for products also sold in the US market.

**Connector IDs**: `international.eu.rapex`, `international.ca.recalls`, `international.au.accc`

---

### 12.5 Securities / Financial Fraud

#### SEC Whistleblower Program

| Attribute | Detail |
|-----------|--------|
| **Type** | Website |
| **Cost** | Free |
| **Technical difficulty** | Medium |

**Data provided**: Annual whistleblower program reports, award amounts, enforcement action types triggered by whistleblower tips.

**Access**: `https://www.sec.gov/whistleblower`

**Value**: ⭐⭐⭐ SEC whistleblower awards in specific sectors (healthcare, pharma) can signal underlying fraud that leads to securities class actions.

**Connector ID**: `federal.sec.whistleblower`

---

## 13. International Mass Tort Equivalents

### 13.1 UK Group Litigation Orders (GLOs)

| Attribute | Detail |
|-----------|--------|
| **Type** | Website scrape |
| **Cost** | Free |
| **Technical difficulty** | Medium |

**Data provided**: UK court orders authorizing group litigation, case management directions, lead solicitor appointments. UK equivalent of MDL.

**Access**: UK Courts and Tribunals Judiciary — `https://www.judiciary.uk/`

**Value**: ⭐⭐⭐ UK GLOs for the same products (e.g., Paraquat, vaginal mesh) signal international scope of liability.

**Connector ID**: `international.uk.glo`

---

### 13.2 Canada Multi-Provincial / Class Actions

| Attribute | Detail |
|-----------|--------|
| **Type** | Website scrape |
| **Cost** | Free |
| **Technical difficulty** | Medium |

**Data provided**: Canadian class action certifications, multi-provincial coordination, settlement approvals. Key provinces: Ontario, Quebec, BC.

**Access**: Provincial court websites. Canadian Bar Association maintains some listings.

**Value**: ⭐⭐⭐ Canadian class actions for same drugs/devices indicate liability scope.

**Connector ID**: `international.ca.class_actions`

---

### 13.3 Australian Class Actions

| Attribute | Detail |
|-----------|--------|
| **Type** | Website scrape |
| **Cost** | Free |
| **Technical difficulty** | Medium |

**Data provided**: Federal Court class action filings, settlement approvals, funding arrangements. Australia has become a major class action jurisdiction.

**Access**: Federal Court of Australia — `https://www.fedcourt.gov.au/`

**Value**: ⭐⭐⭐ Australian class actions often run in parallel with US mass torts for global products.

**Connector ID**: `international.au.class_actions`

---

## 14. Emerging / Alternative Data Sources

### 14.1 Google Scholar Alerts

| Attribute | Detail |
|-----------|--------|
| **Type** | Email alert ingestion |
| **Cost** | Free |
| **Technical difficulty** | Low |

**Data provided**: New academic publications citing specific drugs, devices, or legal theories. Automated alerts for mass-tort-relevant research.

**Access**: Create Google Scholar alerts, ingest via monitored email account.

**Value**: ⭐⭐⭐ New epidemiological studies linking products to health conditions are early litigation signals.

**Connector ID**: `commercial.google_scholar`

---

### 14.2 Patent Litigation (USPTO / PTAB)

| Attribute | Detail |
|-----------|--------|
| **Type** | API + website |
| **Cost** | Free |
| **Technical difficulty** | Medium |

**Data provided**: Patent challenge proceedings (IPR, PGR), patent infringement suits, patent validity challenges. Patent disputes around pharmaceutical compounds can signal competitive pressures that affect drug safety and litigation.

**Access**: USPTO: `https://www.uspto.gov/patents/search` | PTAB decisions: `https://www.uspto.gov/patents/application-process/patent-trial-and-appeal-board`

**Value**: ⭐⭐⭐ Patent challenges on pharma compounds sometimes coincide with generic competition and associated mass tort filings.

**Connector ID**: `judicial.uspto.ptab`

---

### 14.3 IOLTA / Court Filing Fee Trends

| Attribute | Detail |
|-----------|--------|
| **Type** | State court data / reports |
| **Cost** | Free |
| **Technical difficulty** | Medium-High |

**Data provided**: Interest on Lawyers Trust Account (IOLTA) revenue trends as proxy for litigation activity. Filing fee revenues as proxy for court workload.

**Value**: ⭐⭐ IOLTA revenue trends are a macro indicator of legal market activity. Low priority.

**Connector ID**: `judicial.iolta_trends`

---

### 14.4 Legal Job Postings / Law Firm Hiring

| Attribute | Detail |
|-----------|--------|
| **Type** | Web scrape (job boards) |
| **Cost** | Free |
| **Technical difficulty** | Medium |

**Data provided**: Mass tort attorney hiring spikes at specific firms indicate which firms are building capacity for new litigation areas.

**Access**: LinkedIn, Indeed, law firm career pages (scrape for "mass tort" / "product liability" / specific drug names).

**Value**: ⭐⭐⭐ Hiring patterns reveal which firms anticipate growth in specific tort areas — competitive intelligence.

**Connector ID**: `commercial.law_firm_hiring`

---

### 14.5 Expert Witness Directories / Daubert Motions

| Attribute | Detail |
|-----------|--------|
| **Type** | Web scrape |
| **Cost** | Free |
| **Technical difficulty** | Medium |

**Data provided**: Expert witness filings in mass tort cases, Daubert challenge outcomes, medical expert testimony patterns.

**Access**: Court filings (via PACER/CourtListener); expert witness directories.

**Value**: ⭐⭐⭐ Expert witness activity in specific case types indicates litigation intensity and scientific controversy.

**Connector ID**: `judicial.expert_witness_activity`

---

### 14.6 Court-Appointed Counsel / Lead Counsel Orders

| Attribute | Detail |
|-----------|--------|
| **Type** | PACER / JPML scrape |
| **Cost** | Free (via CourtListener/JPML) |
| **Technical difficulty** | Medium |

**Data provided**: Lead counsel appointments in MDLs, PSC (Plaintiffs' Steering Committee) membership, liaison counsel designations.

**Value**: ⭐⭐⭐⭐ Knowing who is leading MDL plaintiff committees reveals the most active firms and their strategic positioning.

**Connector ID**: `judicial.lead_counsel` (derived from PACER/JPML data)

---

## 15. Implementation Priority Matrix

### Tier 1: Implement First (Highest ROI, Low-Medium Effort)

| # | Source | Connector ID | Effort | Value |
|---|--------|-------------|--------|-------|
| 1 | JPML Transfer Orders | `judicial.jpml.transfer_orders` | M | ⭐⭐⭐⭐⭐ |
| 2 | FDA Drug Safety Communications | `federal.fda.safety_communications` | L | ⭐⭐⭐⭐⭐ |
| 3 | FDA MedWatch Alerts | `federal.fda.medwatch` | L | ⭐⭐⭐⭐ |
| 4 | CourtListener Dockets/Attorneys | `judicial.courtlistener.dockets` | L | ⭐⭐⭐⭐⭐ |
| 5 | DOJ Press Releases | `federal.doj.press_releases` | L | ⭐⭐⭐⭐ |
| 6 | FTC Enforcement | `federal.ftc.enforcement` | L | ⭐⭐⭐⭐ |
| 7 | NHTSA Recalls/Complaints | `federal.nhtsa.recalls` | L | ⭐⭐⭐⭐ |
| 8 | JD Supra Mass Tort | `commercial.jdsupra_mass_tort` | L | ⭐⭐⭐⭐ |
| 9 | Google News (Mass Tort Keywords) | Enhance `commercial.google_news` | L | ⭐⭐⭐⭐ |
| 10 | CFPB Enforcement | `federal.cfpb.enforcement` | L | ⭐⭐⭐⭐ |

### Tier 2: Implement Next (High ROI, Medium Effort)

| # | Source | Connector ID | Effort | Value |
|---|--------|-------------|--------|-------|
| 11 | PACER (Full Implementation) | `judicial.pacer.dockets` | H | ⭐⭐⭐⭐⭐ |
| 12 | Missouri Case.net | `state.mo.courts` | M | ⭐⭐⭐⭐⭐ |
| 13 | EPA ECHO | `federal.epa.echo` | M | ⭐⭐⭐⭐ |
| 14 | EPA TRI | `federal.epa.tri` | L | ⭐⭐⭐⭐ |
| 15 | NAAG Settlements | `federal.naag.actions` | M | ⭐⭐⭐⭐ |
| 16 | ClassAction.org | `commercial.classaction_org` | M | ⭐⭐⭐⭐ |
| 17 | Stanford Clearinghouse | `commercial.stanford_clearinghouse` | M | ⭐⭐⭐⭐ |
| 18 | Reddit Legal Forums | `commercial.reddit_forums` | M | ⭐⭐⭐⭐ |
| 19 | FDA Device 510(k)/PMA | `federal.fda.device_510k` | L | ⭐⭐⭐⭐ |
| 20 | FDA Warning Letters | `federal.fda.warning_letters` | L | ⭐⭐⭐ |
| 21 | OSHA Inspections | `federal.osha.inspections` | L | ⭐⭐⭐ |
| 22 | TopClassActions.com | `commercial.topclassactions` | M | ⭐⭐⭐⭐ |
| 23 | Drugs.com Reviews | `commercial.drugsdotcom_reviews` | M | ⭐⭐⭐⭐ |
| 24 | Google Trends | `commercial.google_trends` | M | ⭐⭐⭐⭐ |

### Tier 3: Implement After Core (Medium ROI, Higher Effort)

| # | Source | Connector ID | Effort | Value |
|---|--------|-------------|--------|-------|
| 25 | Delaware CourtConnect | `state.de.courts` | M | ⭐⭐⭐⭐ |
| 26 | FJC Integrated Database | `federal.fjc.idb` | M | ⭐⭐⭐⭐ |
| 27 | EPA Superfund/NPL | `federal.epa.superfund` | M | ⭐⭐⭐⭐ |
| 28 | ATSDR Health Assessments | `federal.atsdr.health_assessments` | M | ⭐⭐⭐⭐ |
| 29 | State AG Press Releases (top 10) | `state.*.ag_actions` | H | ⭐⭐⭐⭐ |
| 30 | NHTSA Defect Investigations | `federal.nhtsa.investigations` | M | ⭐⭐⭐⭐ |
| 31 | FDA Advisory Committees | `federal.fda.advisory_committees` | M | ⭐⭐⭐⭐ |
| 32 | CDC WONDER | `federal.cdc.wonder` | M | ⭐⭐⭐ |
| 33 | CPSC Consumer Reports | `federal.cpsc.consumer_reports` | L | ⭐⭐⭐⭐ |
| 34 | FDA Device Recalls | `federal.fda.device_recalls` | L | ⭐⭐⭐⭐ |
| 35 | EMA Safety Updates | `international.ema.safety` | M | ⭐⭐⭐⭐ |
| 36 | MultiDistrictLitigation.com | `commercial.mdl_tracker` | M | ⭐⭐⭐⭐ |
| 37 | X/Twitter Legal | `commercial.twitter_legal` | M | ⭐⭐⭐⭐ |
| 38 | SEER Cancer Registry | `federal.nih.seer` | M | ⭐⭐⭐⭐ |

### Tier 4: Defer / Cost-Prohibitive

| # | Source | Connector ID | Reason |
|---|--------|-------------|--------|
| 39 | LexisNexis | `commercial.lexisnexis` | Cost-prohibitive |
| 40 | Bloomberg Law | `commercial.bloomberg_law` | Cost-prohibitive |
| 41 | Law360 Full Text | `commercial.law360` | Paywalled, ToS concerns |
| 42 | California CCMS | `state.ca.courts` | Very High effort |
| 43 | Texas re:SearchTX | `state.tx.courts` | High effort |
| 44 | Facebook Groups | `commercial.facebook_groups` | API restrictions |
| 45 | AM Best | `commercial.ambest_reports` | Paid subscription |

---

## 16. Cross-Cutting Enhancements

### 16.1 NLP Analysis Layer for Existing Connectors

Several existing connectors can be enhanced without adding new sources:

| Existing Connector | Enhancement | Signal |
|-------------------|-------------|--------|
| `federal.sec.edgar` | Scan 10-K/10-Q for "reserve increase," "adverse development," "litigation contingency" language | Insurance/litigation cost leading indicators |
| `federal.nih.clinical_trials` | Monitor for trial status changes (terminated, suspended, enrollment halted) | Safety concern signals |
| `federal.fda.faers` | Trend analysis — detect volume spikes for specific drugs over 30/60/90-day windows | Adverse event trend acceleration |
| `federal.fda.maude` | Same trend analysis for device adverse events | Device safety trend signals |
| `commercial.news_rss` | Add legal-specific feeds (Law.com, Legal News, JD Supra RSS) | Broader legal news coverage |

### 16.2 Named Entity Recognition for Party Extraction

Apply NER to docket entries and court opinions (via CourtListener) to automatically extract:
- Plaintiff law firm names and addresses
- Defense firm names
- Judge assignments
- Expert witness names
- Settlement amounts mentioned in orders

### 16.3 Cross-Source Signal Correlation Engine

Build analysis layer that correlates signals across sources:
- **Example pipeline**: FDA safety communication → FAERS adverse event spike → Google Trends increase → New MDL petition filed → Mass tort detected
- **Scoring**: Weight signals by source reliability, recency, and cross-source corroboration

---

## 17. Data Source Inventory Summary

| Category | Existing | New (Recommended) | New (Deferred) |
|----------|----------|-------------------|----------------|
| Federal Courts | 2 | 4 (JPML, PACER full, FJC, NCSC) | 0 |
| MDL/Class Action | 0 | 4 (MDL tracker, ClassAction.org, Stanford, CFPB) | 0 |
| FDA/Regulatory | 4 | 7 (Safety Comms, MedWatch, 510(k), Advisory, Warning Letters, Device Recalls, Orange Book) | 0 |
| Other Federal | 5 | 5 (NHTSA x3, OSHA, ATSDR, USDA) | 1 (ATF) |
| EPA | 2 | 3 (ECHO, TRI, Superfund) | 0 |
| State Courts | 0 (template) | 2+ (MO, DE primary) | 5 (CA, TX, NY, NJ, FL) |
| AG Actions | 0 | 2 (NAAG, State AG RSS) | 0 |
| DOJ/FTC | 0 | 3 (DOJ press, FCA, FTC) | 0 |
| Insurance | 0 | 1 (NAIC) + 1 enhancement | 1 (AM Best) |
| Legal News | 3 | 5 (JD Supra, Law360 headlines, TopClassActions, AboutLawsuits, SSRN) | 2 (LexisNexis, Bloomberg Law) |
| Social/Alt Data | 0 | 5 (Reddit, Twitter, Google Trends, Drugs.com, Law Firm Hiring) | 1 (Facebook) |
| Academic | 1 (PubMed) | 3 (SEER, AHRQ, CDC WONDER) | 0 |
| International | 0 | 5 (EMA, MHRA, EU RAPEX, UK GLO, Canada/Australia) | 0 |
| **TOTAL** | **17** | **~45** | **~12** |
