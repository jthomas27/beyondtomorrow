# Nav Bar Re-Tagging Worksheet

Edit the **`New Nav Tab(s)`** column for any post you want to re-classify, then tell me
to apply it. I'll read this file and patch the tags on Ghost.

## How the nav bar works

The category tab bar in `theme/header.txt` is driven entirely by Ghost **tags**. Each
tab links to a `/tag/<slug>/` page, so a post appears under a tab only if it carries
that exact primary tag:

| Nav tab     | Required tag  |
|-------------|---------------|
| All         | (every post)  |
| Climate     | `Climate`     |
| Technology  | `Technology`  |
| Geopolitics | `Geopolitics` |
| Economics   | `Economics`   |
| Science     | `Science`     |

> `AI` and `Futures` are **not** nav tabs. Posts tagged only with those (or other
> non-nav tags) show up under **All** but no category tab — these are flagged ⚠ below.

## How to edit

- In the **`New Nav Tab(s)`** column, write the nav tab(s) the post should live under.
- Use exact casing: `Climate`, `Technology`, `Geopolitics`, `Economics`, `Science`.
- Multiple tabs allowed — separate with commas (e.g. `Technology, Economics`).
- **Leave a row blank to make no change.**
- Decide the apply mode when you hand it back to me:
  - **Replace** (recommended) — set the post's nav tabs to exactly what you wrote,
    removing any other nav tags. Non-nav tags (e.g. `oil`, `semiconductors`) are kept.
  - **Add** — just append the new nav tag(s), keeping existing ones.

---

## Posts

| # | Post (slug) | Current Nav Tab(s) | New Nav Tab(s) |
|---|-------------|--------------------|----------------|
| 1 | el-nino-2026-the-climate-crisis-tipping-point | Climate, Economics | |
| 2 | ai-supply-chain-fragile-or-future-proof | Technology, Economics, Geopolitics | |
| 3 | the-hidden-limits-of-geothermal-power-for-ai | Technology, Climate, Economics | |
| 4 | self-improving-ai-models-the-risks-were-not-ready-for | Technology, Economics, Geopolitics | |
| 5 | uk-growth-exposed-whos-winning-and-losing | Economics, Climate | |
| 6 | how-far-behind-are-open-source-ai-models-really | Technology, Economics | |
| 7 | will-ai-trigger-historys-largest-wealth-transfer | Technology, Economics | |
| 8 | can-world-models-solve-ais-energy-and-water-consumption-challenges | Climate, Technology, Economics | |
| 9 | are-we-being-fooled-by-llms-clever-words | Technology | |
| 10 | will-world-models-and-llms-compete-or-collaborate | Technology | |
| 11 | ai-regulation-racing-against-a-global-lag | Technology, Geopolitics, Economics | |
| 12 | robo-taxis-are-safer-but-will-they-replace-us | Technology, Economics | |
| 13 | your-investments-are-riskier-than-you-think | Climate, Economics | |
| 14 | openais-erdos-ais-breakthrough-and-boundaries-revealed | Technology, Economics | |
| 15 | argentina-economic-progress-mileis-tax-haven-mirage | Economics, Geopolitics | |
| 16 | spacexs-1-75-trillion-ipo-bubble-or-breakthrough-2 | Technology, Economics | |
| 17 | europes-heat-wave-is-stress-testing-our-food-supply-chain | Climate, Economics | |
| 18 | why-companies-are-secretly-scaling-back-ai-data-centre-spending | Technology, Economics | |
| 19 | will-chinas-renewable-energy-lead-its-ai-dominance | Technology, Geopolitics, Economics | |
| 20 | do-evs-really-help-the-climate-or-just-cost-you-more | Technology, Climate, Economics | |
| 21 | is-historys-greatest-power-grab-underway | Economics, Geopolitics, Technology | |
| 22 | stagflation-stagnation-and-strain-the-forces-holding-back-uk-growth | Economics | |
| 23 | how-to-outwit-ai-sycophancy-prompting-that-gets-results | ⚠ none (AI only) | |
| 24 | price-wars-ai-and-the-memory-chip-risk-game | ⚠ none (AI only) | |
| 25 | who-really-pays-for-europes-fuel-relief | Climate | |
| 26 | why-some-companies-win-the-ai-race-and-others-fall-behind | Technology | |
| 27 | when-commodities-spike-who-wins-who-bleeds | Economics | |
| 28 | jet-fuel-shortages-why-your-next-flight-may-cost-more | Economics | |
| 29 | can-ai-really-discover-evaluating-the-evidence | Technology | |
| 30 | why-data-centre-growth-faces-regional-limits-and-economic-risks | Climate | |
| 31 | factor-investing-risks-and-rewards-developed-vs-emerging-markets | Geopolitics | |
| 32 | quality-factor-investing-who-wins-who-worries | Economics | |
| 33 | oil-ai-and-iran-the-earnings-tug-of-war | Geopolitics, Climate | |
| 34 | climate-shifts-who-profits-and-who-perishes | Climate | |
| 35 | nato-without-america-who-holds-the-line-now | Geopolitics | |
| 36 | will-ai-replace-developers-the-real-impact-of-code-generating-tools | ⚠ none (AI only) | |
| 37 | when-will-ais-lightning-progress-finally-slow-down | Technology, Geopolitics | |
| 38 | when-ai-agents-sign-contracts-whos-liable | ⚠ none (AI only) | |
| 39 | ai-chips-price-wars-and-power-plays-the-semiconductor-showdown | Geopolitics, Technology, Economics | |
| 40 | semiconductors-the-battleground-for-ai-and-geopolitical-power | Geopolitics | |
| 41 | geopolitics-and-the-race-for-ai-chip-supremacy | Geopolitics, Technology | |
| 42 | why-ai-isnt-destroying-young-workers-jobs-yet | ⚠ none (AI only) | |
| 43 | the-paradox-of-fossil-fuel-subsidies-in-wealthy-nations | Climate | |
| 44 | climate-change-upends-migration-and-insurance-futures | Climate, Geopolitics | |
| 45 | is-circular-financing-fueling-an-ai-asset-bubble | ⚠ none (AI only) | |
| 46 | how-ai-queries-impact-the-environment-and-costs | Technology | |
| 47 | ai-agents-under-fire-cybersecurity-risks-for-business-and-consumers | ⚠ none (AI only) | |
| 48 | oil-shockwaves-how-iran-conflict-reshapes-the-energy-future | Geopolitics | |
| 49 | will-ai-make-us-smarter-or-duller-cognitive-effects-explored | Technology | |
| 50 | guardrails-for-workplace-ai-balancing-innovation-and-risk-3 | ⚠ none (AI only) | |
| 51 | renewable-energy-costs-are-fossil-fuels-still-worth-it-2 | Technology, Economics | |
| 52 | critical-minerals-the-geopolitical-risk-behind-ai-chips | Geopolitics, Technology | |
| 53 | middle-east-oil-squeeze-the-petrodollars-unsteady-future | Geopolitics | |
| 54 | rising-fossil-fuel-prices-economic-shockwaves-and-government-credibility | Economics, Geopolitics | |
| 55 | net-zero-commitments-ambition-gaps-and-real-world-impact | Climate | |
| 56 | is-indias-net-zero-plan-credible-or-just-political-signalling | Climate | |
| 57 | ai-capex-boom-sustainable-growth-or-looming-risk | Technology, Geopolitics | |
| 58 | climate-disasters-divide-nations-wmos-2025-wake-up-call | Economics | |
| 59 | financial-markets-reverse-course-uk-faces-stagflation-risk | Economics | |
| 60 | iran-war-forces-urgent-iea-oil-demand-action | Geopolitics, Climate | |
| 61 | trumps-iran-ceasefire-market-moves-or-political-strategy | Geopolitics | |
| 62 | ai-model-token-wastage-and-its-environmental-cost | ⚠ none (AI only) | |
| 63 | ai-and-inequality-power-poverty-and-policy | ⚠ none (AI only) | |
| 64 | carbon-intensity-by-iea-sector-decarbonisation-gaps-and-pathways | Climate | |
| 65 | how-carbon-accounting-methods-shift-sector-emission-perspectives | Climate | |
| 66 | climate-pledges-miss-1-5degc-target-again | Climate | |
| 67 | could-the-ai-revolution-collapse-modern-society | Technology, Geopolitics | |
| 68 | the-impact-of-ai-on-unemployment-across-ages | Technology | |
| 69 | ai-companions-solving-loneliness-or-deepening-isolation | Technology | |
| 70 | tech-billionaires-ai-push-winners-and-losers-revealed | ⚠ none (AI only) | |
| 71 | is-artificial-intelligence-causing-job-loss-in-developed-economies | Technology | |
| 72 | billions-spent-little-removed-the-carbon-capture-dilemma | Climate | |
| 73 | chip-supply-chains-the-new-geopolitical-battleground-for-ai | Geopolitics | |
| 74 | ais-climate-dilemma-powering-progress-fueling-emissions | ⚠ none (AI only) | |
