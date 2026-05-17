# Active-User Sizing of 20 Agentic Coding Frameworks (May 2026)

## Methodology

This report ranks 20 agentic coding frameworks by estimated active monthly user base, using a strict discipline that separates **MEASURED** signals (numbers published directly by the vendor, the package registry, or the marketplace, with a date and source) from **ESTIMATES** (analyst extrapolations, my own inferences from indirect signals such as GitHub stars, npm downloads, or revenue). The ranking is anchored on the strongest measured signal available for each tool: paid subscriber counts for the closed-source IDEs (Cursor, Copilot, Windsurf), Marketplace install counts for VS Code extensions (Cline, Continue, Kilo, Roo, Cody, Amazon Q), and a triangulation of GitHub stars + npm/PyPI downloads + vendor disclosures for the open-source CLIs (Aider, Codex, Gemini CLI, opencode, Crush, Goose, OpenHands, Plandex). Confidence is `high` when at least one MAU/WAU/paid-seat number is disclosed within the last six months, `med` when only install or download numbers exist (which conflate cumulative installs with active users), and `low` when only stars, revenue, or third-party press estimates are available. All numbers carry the date they were observed in the source; "active users" is normalised to monthly active where the source allows, otherwise the qualifier (DAU, WAU, paid seat, install, download) is preserved verbatim. **GitHub stars are explicitly not equated to users** — they are at best a momentum signal and almost always over-count by 10x–100x relative to active developers actually running the tool.

## Headline Ranking (best estimate of monthly active users, May 2026)

| Rank | Framework | Active users (best estimate) | Confidence | Primary signal |
|---|---|---|---|---|
| 1 | GitHub Copilot | ~20M total users, 4.7M paid subscribers | high | Microsoft Q2 FY26 disclosure (Jan 28, 2026) |
| 2 | Cursor | ~7M MAU, ~1M DAU, >1M paying customers | high | Vendor disclosures + $2B ARR (Feb 2026) |
| 3 | Gemini CLI | ~3.2M monthly users (npm proxy, scaling rapidly) | med | npm downloads + Google MAU disclosures |
| 4 | OpenAI Codex CLI | ~3M weekly users (Apr 2026, Altman tweet) | high | Sam Altman disclosure Apr 8, 2026 |
| 5 | Claude Code | ~2–4M weekly users (estimate; doubled since Jan 2026) | med | $2.5B ARR + WAU doubling disclosure |
| 6 | JetBrains AI Assistant + Junie | ~2–3M active (estimate from 22M downloads, ~10–15% conversion) | low | Plugin downloads + JetBrains adoption metrics |
| 7 | Cline | ~1.5–2.5M MAU (estimate from 5M+ installs) | med | 5M+ installs across editors (Jan 2026) |
| 8 | Windsurf (Cognition) | ~1M+ active users | high | Vendor disclosure (Mar 2026 product page) |
| 9 | Kilo Code | ~1.5M users (vendor claim, multi-platform) | med | Vendor disclosure, OpenRouter ranking |
| 10 | Continue.dev | ~600k–1M MAU (estimate from 2.5M installs) | low | Marketplace install count |
| 11 | Amazon Q Developer | ~500k–1M MAU (estimate from 964k VS Code installs) | low | Marketplace install count |
| 12 | Sourcegraph Cody + Amp | ~300–600k MAU (estimate from 814k Cody installs) | low | Marketplace install count |
| 13 | Aider | ~200–400k MAU (estimate from 6.6M PyPI downloads) | low | PyPI downloads |
| 14 | Zed | ~hundreds of thousands DAU (vendor disclosure at 1.0 launch) | med | Zed 1.0 blog post (Apr 29, 2026) |
| 15 | opencode (SST) | ~200–500k MAU (heavy discount on 6.5M "developers" claim) | low | npm + GitHub stars; vendor claim disputed |
| 16 | OpenHands | ~100–300k MAU (estimate from 4M cumulative downloads) | low | All Hands AI disclosure (Nov 2025 Series A) |
| 17 | Goose | ~100–200k MAU (estimate from CLI/desktop downloads + 45k stars) | low | GitHub stars + release downloads |
| 18 | Antigravity (Google) | ~50–200k preview testers (estimate from "6% adoption" press) | low | Press estimate; free preview |
| 19 | Crush (Charmbracelet) | ~50–150k MAU (estimate from Homebrew/npm + 24k stars) | low | Stars + multi-channel installs |
| 20 | Plandex | ~10–30k MAU (small, self-hosted only after Cloud sunset) | low | 15.4k stars, niche TUI |

Roo Code is excluded from the active-user ranking because the project was archived on May 15, 2026 — its 3M cumulative installs are historic, not active. The community fork (Zoo Code) and the migration target (Kilo Code) absorb most of that base; Roo Code is discussed inline below for completeness.

---

### GitHub Copilot
- **Best estimate of active users (latest)**: ~20M total users (cumulative), 4.7M paid subscribers; MAU not separately disclosed but plausibly in the high single-digit millions among paid + free tier. Confidence: high.
- **MEASURED signals**:
  - 4.7M paid subscribers as of Jan 28, 2026 (Microsoft Q2 FY26 earnings, +75% YoY) — getpanto.ai, secondtalent.com.
  - 20M+ all-time users by July 2025 (Satya Nadella statement) — TechCrunch, Jul 30, 2025.
  - 1.8M paid subscribers in FY24, growing to 4.7M by Jan 2026 — ~2.6× expansion (Microsoft disclosures).
  - Copilot built into VS Code beginning v1.116 (Apr 21, 2026) — GitHub Changelog. This removes the marketplace as a clean install signal for new users going forward.
- **ESTIMATES**:
  - MAU likely 8–12M when combining paid (4.7M, mostly active by definition) and free tier — derived from "20M all-time" minus reasonable churn.
- **Momentum**: growing, but moving to usage-based billing in June 2026 (announced March 2026), which may compress the casual end of the funnel.
- **Notes**: Microsoft conflates Copilot for Business, Individual, Enterprise, and the new Coding Agent in the headline "users" number. "Paid subscribers" is the cleanest measured anchor. Copilot now bundles a CLI, coding agent (Padawan), and VS Code chat — sizing the agentic portion specifically is impossible from public disclosures.

### Cursor (Anysphere)
- **Best estimate of active users (latest)**: ~7M MAU, ~1M DAU, >1M paying customers, 50k+ paying teams (Q1 2026). Confidence: high.
- **MEASURED signals**:
  - >1M DAU disclosed by Anysphere in 2025; >2M total users (Sacra, getpanto.ai).
  - $2B ARR Feb 2026; $1B ARR Nov 2025; >$500M ARR Jun 2025 (TechCrunch, SaaStr, Sacra).
  - $29.3B post-money valuation, Nov 13, 2025 (Series D, $2.3B raise).
  - In talks to raise at $50B valuation, Apr 2026 (TheNextWeb).
  - Cursor stated "50,000+ engineering teams globally", "Fortune 1000 70% coverage" (vendor disclosure, 2026).
- **ESTIMATES**:
  - MAU of ~7M figure appears in vendor talking points but is not in an SEC-style filing — treat as vendor-claimed.
- **Momentum**: growing — fastest SaaS to $1B ARR (~17 months), now also fastest to $2B.
- **Notes**: Cursor is a VS Code fork, so it does not appear in the VS Code Marketplace install counts. Paying-customer count of ">1M" is exceptionally high for a $20–$60/seat product; if accurate, that alone places Cursor as #1 by paid users among the agentic-coding cohort, but Copilot retains the larger total (free + paid) base.

### Google Gemini CLI & Antigravity
- **Best estimate of active users (latest)**: Gemini CLI ~3.2M monthly users (proxy via npm); Antigravity ~50–200k preview users. Confidence: med (CLI), low (Antigravity).
- **MEASURED signals**:
  - Gemini CLI: 104k GitHub stars, 13.7k forks (May 17, 2026 GitHub page).
  - 3.2M npm downloads referenced as "second place" behind Codex CLI in Apr 2026 reporting.
  - Antigravity announced Nov 18, 2025; in free public preview as of May 2026 (Google Developers Blog).
  - Antigravity: "6% developer adoption within 2 months of launch" per industry press (Apr 2026) — unclear what "developer" base is the denominator.
  - Broader Gemini context: 750M MAU on the consumer Gemini app (Q4 2025), 2.4M Gemini API developers (Jan 2026) — these are NOT the CLI/IDE figures.
- **ESTIMATES**:
  - Gemini CLI MAU likely 2–4M based on the npm download trajectory (3.2M/month proxy) and the fact that many installs reflect ChatGPT/Codex-style power users rather than passive downloads.
  - Antigravity 50–200k is my inference from "6% adoption" press: if the addressable denominator is ~3M developers actively trialling new agentic IDEs, 6% × 3M ≈ 180k. The "6% of all developers" reading would imply ~1.5M, which I view as implausible for a 5-month-old preview product.
- **Momentum**: growing rapidly; Google's free tier and Gemini 3 integration are pulling new users.
- **Notes**: Gemini CLI is open source under Apache-2.0; Antigravity is a closed VS Code fork. Conflating them risks double-counting users who use both.

### OpenAI Codex CLI
- **Best estimate of active users (latest)**: ~3M weekly users (Apr 2026). Confidence: high.
- **MEASURED signals**:
  - 3M weekly users confirmed by Sam Altman on Apr 8, 2026.
  - 14.53M npm downloads in March 2026 alone (vs. 82k in Apr 2025 launch month — 177× growth).
  - 32.8M total npm downloads in the trailing 12 months.
  - 83.3k GitHub stars, 12.1k forks (May 2026).
- **ESTIMATES**:
  - MAU is likely 4–6M given WAU of 3M and typical WAU/MAU ratios of 0.5–0.7 for power-developer tools — but vendor only disclosed WAU.
- **Momentum**: explosive growth; OpenAI is reportedly pricing Codex aggressively to defend ChatGPT-Plus base against Anthropic.
- **Notes**: As OpenAI itself notes, npm downloads under-count Codex usage because many users invoke Codex through the ChatGPT desktop app or web UI. The "3M WAU" therefore is more reliable than the npm number.

### Claude Code (Anthropic)
- **Best estimate of active users (latest)**: ~2–4M WAU (estimate; doubled since Jan 2026 baseline, exact baseline not disclosed). Confidence: med.
- **MEASURED signals**:
  - Run-rate revenue: $500M shortly after GA, then >$2.5B by Feb 2026 (Bitget News, demandsage).
  - Run-rate doubled from start of 2026 to Apr 2026.
  - Anthropic disclosed: "Claude Code WAU has doubled since Jan 1, 2026."
  - Anthropic ARR: $14B Feb 2026 → $19B Mar 2026 → $30B Apr 2026 → $44B+ May 2026 (Dario Amodei interview).
  - 300k+ business customers across Anthropic; 500+ spend >$1M/year (Anthropic disclosures).
  - Anthropic at $380B valuation post-Series G Feb 2026.
- **ESTIMATES**:
  - Working backward from $2.5B Claude Code run-rate at an average $40–60/month effective spend per active developer (Pro/Max seats mostly) gives ~3.5–5M paying-equivalent users. Mixing in free Pro users and API-direct Claude Code usage suggests 2–4M WAU is the right band.
- **Momentum**: very strong, growing; Claude Code's growth is the headline reason Anthropic's ARR is tracking ahead of internal forecasts.
- **Notes**: Anthropic conspicuously avoids publishing an absolute WAU/MAU number for Claude Code. The "WAU doubled" wording is rate-of-change only and gives no level. Note also: the Claude Code repo at github.com/anthropics/claude-code is not the primary distribution channel — most users install via npm or direct download.

### JetBrains AI Assistant & Junie
- **Best estimate of active users (latest)**: ~2–3M active (estimate from 22M plugin downloads, with a conservative 10–15% MAU-conversion). Confidence: low.
- **MEASURED signals**:
  - 22M+ downloads cited in a 2026 review (aiproductivity.ai), referring to the JetBrains AI Assistant plugin.
  - Junie marketplace rating: 2.3/5 (plugins.jetbrains.com).
  - Junie available across IntelliJ IDEA, PyCharm, GoLand, PhpStorm, WebStorm, RubyMine, RustRover (JetBrains docs).
  - JetBrains has not publicly disclosed Junie/AI Assistant MAU.
- **ESTIMATES**:
  - JetBrains has ~13M paying IDE users (historical disclosure). A 15–25% adoption of AI tooling among that base would give 2–3M; this matches the rough order of magnitude implied by the 22M downloads.
- **Momentum**: growing; Junie launched April 2025, AI Assistant has been generally available since late 2023, both are gaining as JetBrains pushes AI Pro/Premium bundles.
- **Notes**: Numbers conflate AI Assistant (chat-style) with Junie (agentic). The 22M downloads include update installs and uninstalls. JetBrains' own admin dashboards expose Active AI Users metrics but that data stays on-prem; no aggregate is published.

### Cline (formerly Claude Dev)
- **Best estimate of active users (latest)**: ~1.5–2.5M MAU (estimate from 5M+ cumulative installs across editors). Confidence: med.
- **MEASURED signals**:
  - 5M+ installs across VS Code, JetBrains, Cursor, Windsurf, OpenVSX as of Jan 2026 (Cline blog "5M installs, $1M Open Source Grant program").
  - Install growth: 1M (Mar 2025) → 2.7M (Jul 2025) → 3.8M (Nov 2025) → 5M (Jan 2026).
  - 61.9k GitHub stars, 6.4k forks, ~258 releases (May 2026).
  - $32M Series A + seed announced Jul 31, 2025 (Emergence Capital lead, Pace Capital co-lead) — Sacra, vendor blog.
  - VS Code Marketplace extension ID `saoudrizwan.claude-dev` (carries the original Claude Dev brand).
- **ESTIMATES**:
  - 5M installs across editor families typically maps to 1.5–2.5M MAU at 30–50% retention — Cline is reused frequently within agentic-coder cohorts, supporting the higher end.
- **Momentum**: very strong; one of the few open-source agents that has crossed the chasm from hobbyist to team-paid usage.
- **Notes**: 5M is **installs across editors**, not active users. The marketplace count alone is significantly lower than 5M; Cline counts JetBrains + OpenVSX + Cursor/Windsurf to arrive at the 5M aggregate. Cline's free-extension/BYO-key model means most installs sit in the free funnel rather than the paid Cline Teams seat count.

### Windsurf (Cognition)
- **Best estimate of active users (latest)**: >1M active users. Confidence: high (vendor disclosure).
- **MEASURED signals**:
  - "1M+ active users, 70M+ lines of code/day, 59% of Fortune 500" — Windsurf product page, Mar 2026.
  - 4,000+ enterprises in production (Windsurf enterprise page, Mar 2026).
  - Codeium ARR $82M Jul 2025, 350+ enterprise customers at acquisition (Reuters).
  - Cognition combined ARR doubled since Windsurf acquisition (Cognition blog).
  - Cognition valuation $25B (Bloomberg, Apr 23, 2026), up from $10.2B (Sep 2025 CNBC report).
- **ESTIMATES**:
  - "1M+ active users" is vendor language without an MAU/WAU qualifier — treat as the floor.
- **Momentum**: growing; the Cognition-Windsurf-Devin integration is consolidating share among enterprise customers.
- **Notes**: Brand turbulence: Codeium → Windsurf → Google licensed CEO + ~40 staff → Cognition acquired remainder, all in mid-2025. Active-user numbers from the Codeium era and Windsurf era should not be added together — the >1M figure on the Mar 2026 page is post-consolidation.

### Kilo Code
- **Best estimate of active users (latest)**: ~1.5M users (vendor claim spanning VS Code + JetBrains + CLI). Confidence: med.
- **MEASURED signals**:
  - 19.4k GitHub stars, 2.5k forks (May 2026).
  - VS Code Marketplace extension ID `kilocode.Kilo-Code`.
  - Vendor (Kilo) claim: "#1 on OpenRouter with over 1.5M users and 25T tokens processed" (kilo.ai/Kilo-Org/kilocode).
  - Kilo GA'd on April 2, 2026 after rebuilding on the opencode server.
- **ESTIMATES**:
  - The 1.5M "users" number is vendor-disclosed and not separately verified; OpenRouter ranking is consistent with high relative usage but does not validate the absolute count.
  - Likely active MAU is 400–800k once one discounts uninstalled and one-time-trial users.
- **Momentum**: growing fast; Kilo has been the explicit migration target for the now-archived Roo Code base (3M historical installs).
- **Notes**: Kilo is itself a Roo Code fork, which was a Cline fork — the "5M Cline installs" and "3M Roo installs" and "1.5M Kilo users" overlap substantially in concept and partly in person.

### Continue.dev
- **Best estimate of active users (latest)**: ~600k–1M MAU (estimate from 2.5M VS Code installs + JetBrains). Confidence: low.
- **MEASURED signals**:
  - 2.5M+ installs on VS Code Marketplace as of 2026 (vendor disclosure; corroborated by review sites).
  - 33.2k GitHub stars, 4.5k forks (May 2026).
  - $5.6M raised (Y Combinator + Heavybit + $3M Feb 2025) — Tracxn, PitchBook.
  - 19 employees as of Mar 31, 2026.
  - 822 releases; pivoted in mid-2025 from IDE extension to "Continuous AI" CI-style platform.
- **ESTIMATES**:
  - 600k–1M MAU is my estimate from 2.5M installs at 25–40% MAU/install. Continue's recent CI pivot may have softened the inline-extension active base; no fresh MAU is public.
- **Momentum**: flat-to-modest; strategic pivot to CI checks took the product partly out of the daily-driver agentic-coding category.
- **Notes**: Continue is the longest-running open-source coding agent on this list; install velocity has slowed as Cline, Kilo, Roo, and Cursor pulled mind-share.

### Amazon Q Developer
- **Best estimate of active users (latest)**: ~500k–1M MAU (estimate from 964k VS Code installs + JetBrains/Visual Studio). Confidence: low; trending **down** as AWS sunsets Q Developer.
- **MEASURED signals**:
  - 964k+ installs on the VS Code Marketplace (`AmazonWebServices.amazon-q-vscode`), reported in July 2025 supply-chain-incident coverage.
  - AWS announced Amazon Q Developer end-of-support on April 30, 2027; **new signups blocked from May 15, 2026** (AWS DevOps blog).
  - AWS pushing migration to Kiro (spec-driven IDE); "Kiro developer usage more than doubled QoQ, enterprise usage up ~10×" — Amazon Q1 FY26 earnings (Futurum Group).
  - $260M revenue milestone disclosed (AWS DevOps blog, 2024) — pre-EOL announcement.
- **ESTIMATES**:
  - Active MAU near the 500–1M band based on 964k VS Code installs plus an unknown JetBrains/Visual Studio share; the absolute floor is the paid Pro subscribers ($19/user/month) which is undisclosed.
- **Momentum**: declining; the May 2026 EOL announcement freezes the funnel. The active base is migrating to Kiro (which is out of scope of this 20-tool list but functionally replaces Q Developer).
- **Notes**: VS Code install count is heavily inflated by AWS Toolkit autoinstalls (the AWS Toolkit extension auto-installs Amazon Q for many enterprise developers).

### Sourcegraph Cody + Amp
- **Best estimate of active users (latest)**: ~300–600k MAU combined (estimate from 814k Cody VS Code installs minus churn after the Free/Pro shutdown, plus Amp's free-tier ramp). Confidence: low.
- **MEASURED signals**:
  - 814k+ installs on VS Code Marketplace as of Mar 2026 (`sourcegraph.cody-ai`); 788,736 verified in Feb 2026 — installation growth ~3% MoM.
  - Cody Free + Pro shut down June–July 2025; only Cody Enterprise ($59/user/month) remains.
  - 250k+ code repositories indexed by Sourcegraph (vendor disclosure).
  - Amp launched as a free, agentic successor to Cody for individuals — currently testing ad-supported free tier (AInativedev).
- **ESTIMATES**:
  - Active MAU likely 200–400k for Cody (mostly enterprise seats) and 100–200k for Amp (free + early paid), summing to a 300–600k band.
- **Momentum**: bifurcated — Cody flat (enterprise-only), Amp growing from a smaller base.
- **Notes**: The product split confuses sizing. The 814k install count is mostly historical Cody Free/Pro users; many of those installs are now inactive after the June–July 2025 shutdown of the free tiers.

### Aider
- **Best estimate of active users (latest)**: ~200–400k MAU (estimate from ~6.6M PyPI downloads). Confidence: low.
- **MEASURED signals**:
  - 44.9k GitHub stars, 4.4k forks (May 2026).
  - 6.6–7M PyPI total downloads (aider-chat package) per pepy.tech and Libraries.io as of early 2026.
  - 174+ releases; latest 0.86.2 Feb 12, 2026.
  - Vendor talking point: "15 billion tokens processed weekly" (aider.chat).
- **ESTIMATES**:
  - PyPI downloads cumulative ≠ MAU. CI/CD reinstall traffic is heavy for Python tools. A reasonable MAU haircut is 5–8% of cumulative downloads for a power-user CLI like Aider, giving 200–400k.
- **Momentum**: flat-to-growing; Aider was the original terminal coding agent and retains a loyal Python-heavy user base, but its growth has been outpaced by Codex CLI, opencode, and Crush.
- **Notes**: The 15B tokens/week claim, if accurate, supports the high end of the MAU estimate — that workload is consistent with ~300k power users at ~50k tokens/day each.

### Zed
- **Best estimate of active users (latest)**: ~hundreds of thousands DAU (vendor disclosure at 1.0 launch). Confidence: med.
- **MEASURED signals**:
  - "Hundreds of thousands of daily developers" — Zed 1.0 blog post, Apr 29, 2026.
  - 83.1k GitHub stars, 8.5k forks (May 2026).
  - 37,811 commits; 1,227 releases; ~1M+ lines of Rust (vendor blog).
  - Zed Pro at $10/month, launched Feb 19, 2026, includes Claude Opus/Sonnet access via credit pool.
- **ESTIMATES**:
  - "Hundreds of thousands of daily developers" suggests 200–500k DAU. MAU is likely 1.5–3× DAU for a daily-driver editor — 300k–1.5M MAU is a wide band.
- **Momentum**: growing; the 1.0 launch and AI agent panel were a strong catalyst.
- **Notes**: Zed is a full editor, not a coding-agent extension; its agentic panel is one feature among many. The DAU figure mixes pure-editor users (no AI) with agent-panel users. The agent-using subset is plausibly 30–60% of total — still likely 100–300k MAU for the agentic use case alone.

### opencode (SST / Anomaly Innovations)
- **Best estimate of active users (latest)**: ~200–500k MAU (heavily discounting vendor "6.5M monthly developers" claim). Confidence: low.
- **MEASURED signals**:
  - 149k–162k GitHub stars depending on snapshot (Apr–May 2026); 806 releases; v1.15.4 (May 17, 2026).
  - 19k forks, 623 watchers.
  - npm package `opencode-ai`: 39 dependent projects (npm registry, May 2026).
  - 18k new stars in 2-week January 2026 surge (medium.com analysis).
  - Vendor (Anomaly Innovations / SST) claim: "6.5–7.5M monthly active developers" by mid-2026 — referenced via DeepWiki, aiwiki.ai, techfundingnews.
- **ESTIMATES**:
  - The vendor "6.5M monthly developers" figure is implausible against the underlying npm download trace and would imply opencode is roughly the size of Cursor; this is unsupported by ARR, fundraising, or independent traffic measures. I discount it to 200–500k MAU based on triangulating GitHub stars vs. comparable tools.
- **Momentum**: growing rapidly on stars; uncertain on active users.
- **Notes**: opencode is the canonical example of GitHub stars vastly outrunning active users. Treat its public "monthly developer" claim with extreme caution — it appears to be either total cumulative install events or a press-release inflation. Note also the repo namespace migration: `sst/opencode` is mirrored at `anomalyco/opencode` after SST rebranded.

### OpenHands / All Hands AI
- **Best estimate of active users (latest)**: ~100–300k MAU (estimate from 4M cumulative downloads + Series A signals). Confidence: low.
- **MEASURED signals**:
  - 73.9k GitHub stars, 9.4k forks (May 2026); 102 releases, latest v1.7.0 May 1, 2026.
  - "4M downloads, 60k+ stars, 7k forks" per recent press citation (BusinessWire Series A announcement, Nov 18, 2025).
  - $18.8M Series A (Menlo, Obvious, Madrona, Fujitsu Ventures), Nov 2025; $23.8M total raised.
  - SaaS launch: "All Hands Online (Beta)" — Nov 12, 2025 (vendor blog).
- **ESTIMATES**:
  - 4M cumulative downloads × ~5% MAU conversion (typical for a heavyweight Python+Docker tool that few keep daily) ≈ 200k MAU. Cloud beta adds a smaller but more engaged tail.
- **Momentum**: growing; positioning as "open-source Devin" continues to attract enterprise pilots (AMD, Apple, Google, Amazon, Netflix, NVIDIA cited as cloners/forkers — but those are individual engineer signals, not enterprise contracts).
- **Notes**: OpenHands was renamed from OpenDevin in 2024 after the Cognition trademark dispute. Star/download counts must be interpreted on the All-Hands-AI org, which now also hosts an `openhands-cloud` repo separately. The 60k stars cited at Series A vs 73.9k now is consistent with ~6 months of organic growth.

### Goose (Agentic AI Foundation, formerly Block)
- **Best estimate of active users (latest)**: ~100–200k MAU (estimate from CLI/desktop downloads + 45k stars). Confidence: low.
- **MEASURED signals**:
  - 45.4k GitHub stars (May 2026), 4.7k forks, 134 releases.
  - 27.2k stars at January 2026 public launch; +18k in ~4 months.
  - Repo moved from `block/goose` to `aaif-goose/goose` (Agentic AI Foundation under Linux Foundation).
  - 400+ contributors (vendor disclosure).
  - 15+ LLM provider integrations.
  - "Broadly deployed across Block's engineering, sales, finance, and data teams" (Block blog), implying low thousands of internal users at Block alone.
- **ESTIMATES**:
  - MAU likely 100–200k based on multi-platform desktop + CLI binary install activity inferred from release download counts (Block has not published binary-download analytics).
- **Momentum**: growing; the Linux Foundation transition (April 2026) is a strong neutrality signal for enterprise adoption.
- **Notes**: Goose is a general agent, not strictly a coding agent — its user base includes non-developer Block employees, which inflates MAU vs. coding-specific use. Adjusting for coding-only would lower the estimate to ~60–120k.

### Crush (Charmbracelet)
- **Best estimate of active users (latest)**: ~50–150k MAU. Confidence: low.
- **MEASURED signals**:
  - 24.4k GitHub stars, 1.7k forks (May 2026); 156 releases, latest v0.69.1 (May 15, 2026).
  - Distributed via Homebrew, npm, Arch Linux (yay), Nix, FreeBSD, Winget, Scoop — broad packaging.
  - Charm ecosystem disclosure: "powers 25k+ applications" (across all Charm libraries — Bubble Tea etc., not Crush-specific).
- **ESTIMATES**:
  - 50–150k MAU is my inference from a 24k-star Go-based TUI with a recognized brand (Charm) and roughly Aider-class momentum, but without the PyPI funnel that Aider has.
- **Momentum**: growing; Charm has strong terminal-developer mindshare.
- **Notes**: Crush is the youngest serious entrant on this list; star counts are still climbing fast (~600 stars/week trend), and Vercel added it to its "Agent Resources" docs in 2026 — both momentum signals, neither a measured user count.

### Antigravity (Google)
- **Best estimate of active users (latest)**: ~50–200k preview testers. Confidence: low.
- **MEASURED signals**:
  - Announced Nov 18, 2025; public preview ongoing as of May 2026 (Google Developers Blog).
  - "Reached 6% developer adoption within just two months of launch" — multiple press citations (aitooljunction, openaitoolshub, baytechconsulting).
  - VS Code fork; closed source; runs Gemini 3 Pro and 3 Flash.
- **ESTIMATES**:
  - 50–200k is my inference depending on which "developer" denominator the "6%" press cite uses (Google's own developer surveys put serious AI-IDE evaluators in the low millions). 6% × 2–3M attentive developers ≈ 120–180k.
- **Momentum**: growing fast in preview; pricing post-preview will be the inflection.
- **Notes**: "6% adoption" is press analysis, not a Google disclosure — and "adoption" likely means "tried" rather than "active monthly user." Treat as a soft estimate. Google has yet to publish a measured Antigravity user number.

### Plandex
- **Best estimate of active users (latest)**: ~10–30k MAU. Confidence: low.
- **MEASURED signals**:
  - 15.4k GitHub stars, 1.1k forks (May 2026); 73 releases (latest cli/v2.2.1 from July 16, 2025 — note the **slow release cadence**).
  - 1,483 commits on main branch.
  - "Plandex Cloud is winding down and no longer accepts new users — self-hosting is the recommended path" (recent docs/reviews).
- **ESTIMATES**:
  - 10–30k MAU based on 15k stars (Aider/Crush-class), but Plandex's self-hosted-only posture and stale release cadence push the active number toward the low end.
- **Momentum**: flat-to-declining (Plandex Cloud wind-down is the bearish signal).
- **Notes**: Plandex's 2M-token context window and cumulative-diff sandbox keep it relevant for a narrow large-codebase niche, but it does not have the consumer/enterprise reach of the top-15 tools.

### Roo Code (archived May 15, 2026; included for completeness)
- **Best estimate of active users (latest)**: ~0 (archived); ~3M cumulative installs at peak.
- **MEASURED signals**:
  - 3M+ VS Code Marketplace installs at archival (roborhythms.com, kilo.ai migration page).
  - 24.1k GitHub stars, 3.3k forks, 281 releases; archived May 15, 2026.
  - Co-founder Matt Rubens announced shutdown April 21, 2026; team pivoted to Roomote (autonomous agent integrating with Slack/GitHub/Linear).
- **ESTIMATES**:
  - The ~3M install base is dispersed across Kilo Code (migration target), Zoo Code (community fork), and back to Cline (parent project).
- **Momentum**: declining (terminated).
- **Notes**: Roo's install count is historically the largest among Cline-family forks but is not active as of May 2026.

---

## Sources

- Aider GitHub: https://github.com/Aider-AI/aider
- Aider PyPI: https://pypi.org/project/aider-chat/ ; pepy.tech statistics; Libraries.io
- Amazon Q Developer end-of-support announcement (AWS DevOps Blog): https://aws.amazon.com/blogs/devops/amazon-q-developer-end-of-support-announcement/
- Amazon Q Developer marketplace listing: https://marketplace.visualstudio.com/items?itemName=AmazonWebServices.amazon-q-vscode
- Amazon Q $260M milestone (AWS DevOps Blog): https://aws.amazon.com/blogs/devops/amazon-q-developer-just-reached-a-260-million-dollar-milestone/
- AWS Q1 FY26 earnings analysis (Futurum Group): https://futurumgroup.com/insights/amazon-q1-fy-2026-aws-momentum-builds-as-ai-infrastructure-spend-surges/
- Anthropic Economic Index (March 2026): https://www.anthropic.com/research/economic-index-march-2026-report
- Anthropic / Claude Code revenue (Bitget News): https://www.bitget.com/news/detail/12560605396205
- Claude statistics (DemandSage): https://www.demandsage.com/claude-ai-statistics/
- Claude Code increased weekly limits 50% (apidog): https://apidog.com/blog/claude-code-weekly-limits-50-percent-increase-july-2026/
- Cline 5M installs blog post: https://cline.bot/blog/5m-installs-1m-open-source-grant-program
- Cline GitHub: https://github.com/cline/cline
- Cline marketplace: https://marketplace.visualstudio.com/items?itemName=saoudrizwan.claude-dev
- Cline revenue & analysis (Sacra): https://sacra.com/c/cline/
- Cognition acquires Windsurf (TechCrunch): https://techcrunch.com/2025/07/14/cognition-maker-of-the-ai-coding-agent-devin-acquires-windsurf/
- Cognition Windsurf blog: https://cognition.ai/blog/windsurf
- Cognition $25B valuation analysis (Idlen): https://www.idlen.io/news/cognition-devin-25-billion-valuation-windsurf-vibe-coding-april-2026/
- Codex CLI npm: https://www.npmjs.com/package/@openai/codex
- Codex CLI GitHub: https://github.com/openai/codex
- Codex CLI statistics (gradually.ai): https://www.gradually.ai/en/codex-statistics/
- Continue.dev GitHub: https://github.com/continuedev/continue
- Continue.dev marketplace: https://marketplace.visualstudio.com/items?itemName=Continue.continue
- Continue PitchBook profile: https://pitchbook.com/profiles/company/534537-28
- Continue Tracxn profile: https://tracxn.com/d/companies/continue/
- Crush GitHub: https://github.com/charmbracelet/crush
- Crush review (Vibe Coding Hub): https://vibecodinghub.org/tools/crush
- Cursor revenue (Sacra): https://sacra.com/c/cursor/
- Cursor statistics (getpanto.ai): https://www.getpanto.ai/blog/cursor-ai-statistics
- Cursor $50B talks (TheNextWeb): https://thenextweb.com/news/cursor-anysphere-2-billion-funding-50-billion-valuation-ai-coding
- Cursor $1B ARR (SaaStr): https://www.saastr.com/cursor-hit-1b-arr-in-17-months-the-fastest-b2b-to-scale-ever-and-its-not-even-close/
- Cursor business breakdown (Contrary Research): https://research.contrary.com/company/cursor
- Gemini CLI GitHub: https://github.com/google-gemini/gemini-cli
- Gemini CLI monitoring dashboards (Google Cloud Blog): https://cloud.google.com/blog/topics/developers-practitioners/instant-insights-gemini-clis-new-pre-configured-monitoring-dashboards/
- Gemini statistics (Second Talent): https://www.secondtalent.com/resources/google-gemini-statistics/
- GitHub Copilot 20M users (TechCrunch): https://techcrunch.com/2025/07/30/github-copilot-crosses-20-million-all-time-users/
- GitHub Copilot statistics (getpanto.ai): https://www.getpanto.ai/blog/github-copilot-statistics
- GitHub Copilot usage-based billing blog: https://github.blog/news-insights/company-news/github-copilot-is-moving-to-usage-based-billing/
- Goose GitHub: https://github.com/block/goose
- Goose Block Open Source intro: https://block.xyz/inside/block-open-source-introduces-codename-goose
- Goose review (effloow): https://effloow.com/articles/goose-open-source-ai-agent-review-2026
- Antigravity Wikipedia: https://en.wikipedia.org/wiki/Google_Antigravity
- Antigravity adoption (Tool Junction): https://www.tooljunction.io/ai-tools/antigravity
- Antigravity build (Google Developers Blog): https://developers.googleblog.com/build-with-google-antigravity-our-new-agentic-development-platform/
- JetBrains AI Adoption docs: https://www.jetbrains.com/help/jetbrains-console/ai-adoption-and-usage.html
- JetBrains AI Assistant review (aiproductivity.ai): https://aiproductivity.ai/tools/jetbrains-ai-assistant/
- Junie plugin marketplace: https://plugins.jetbrains.com/plugin/26104-junie-the-ai-coding-agent-by-jetbrains
- Kilo Code marketplace: https://marketplace.visualstudio.com/items?itemName=kilocode.Kilo-Code
- Kilo Code GitHub: https://github.com/Kilo-Org/kilocode
- Kilo's Roo migration guide: https://kilo.ai/articles/roo-to-kilo-migration-guide
- Codex CLI guide (Shareuhack): https://www.shareuhack.com/en/posts/openai-codex-cli-agent-guide-2026
- opencode GitHub: https://github.com/sst/opencode
- opencode npm: https://www.npmjs.com/package/opencode-ai
- opencode background (techfundingnews): https://techfundingnews.com/opencode-the-background-story-on-the-most-popular-open-source-coding-agent-in-the-world/
- opencode vs Claude Code (saiyampathak Substack): https://saiyampathak.substack.com/p/opencode-just-overtook-claude-code
- OpenHands GitHub: https://github.com/All-Hands-AI/OpenHands
- OpenHands Series A (BusinessWire): https://www.businesswire.com/news/home/20251118768131/en/OpenHands-Raises-$18.8M-Series-A-to-Bring-Open-Source-Cloud-Coding-Agents-to-Enterprises
- OpenHands AMD partnership: https://www.amd.com/en/developer/resources/technical-articles/2025/OpenHands.html
- Plandex GitHub: https://github.com/plandex-ai/plandex
- Plandex review (Vibe Coding Hub): https://vibecodinghub.org/tools/plandex
- Roo Code GitHub (archived): https://github.com/RooCodeInc/Roo-Code
- Roo Code shutdown analysis (RoboRhythms): https://www.roborhythms.com/roo-code-vs-roomote/
- Sourcegraph Cody marketplace: https://marketplace.visualstudio.com/items?itemName=sourcegraph.cody-ai
- Sourcegraph Cody Free/Pro shutdown blog: https://sourcegraph.com/blog/changes-to-cody-free-pro-and-enterprise-starter-plans
- Sourcegraph Amp (ad-supported tier, AI Native Dev): https://ainativedev.io/news/amp-s-new-business-model-ad-supported-ai-coding
- Windsurf statistics (getpanto.ai): https://www.getpanto.ai/blog/windsurf-ai-ide-statistics
- Codeium / Windsurf revenue (Sacra): https://sacra.com/c/codeium/
- Zed 1.0 launch blog: https://zed.dev/blog/zed-1-0
- Zed GitHub: https://github.com/zed-industries/zed
- Zed AI plans/pricing: https://zed.dev/docs/ai/plans-and-usage
- The Register on Zed 1.0: https://www.theregister.com/2026/04/30/zed_team_releases_version_10/
