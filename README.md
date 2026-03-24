# ETCG Supplementary Materials

Supplementary data and scripts for:

> **LLM-Based Exploratory Testing Charter Generation: A Framework and Empirical Evaluation**
> Arbaz Surti
> *Empirical Software Engineering* (under review)

---

## Repository Contents

```
data/
  etcg-results.json           — 125 ETCG-generated charters (25 specs × 5 charters)
  etcg-baseline-results.json  — 125 baseline-generated charters (same specs)
  etcg-scores.json            — Rubric scores for all 250 charters (5 dimensions each)
  specs-new-7.json            — 7 new requirement specifications (SPEC-19 to SPEC-25)
  specs-new-7.md              — Same specs in Markdown format

scripts/
  etcg_tool.py                — ETCG charter generator (GPT-4o via OpenRouter)
  etcg_baseline_tool.py       — Baseline generator (unstructured prompt, same model)
  etcg_score.py               — Automated rubric scorer (GPT-4o at temperature 0)
  generate_figures.py         — Generates Figures 2, 3, 4 from etcg-scores.json
```

The 18 sparse specifications (SPEC-01 to SPEC-18) were carried over from the prior ATSR
study ([arbaz-surti/atsr-supplementary](https://github.com/arbaz-surti/atsr-supplementary))
and are not duplicated here.

---

## Replication

### Requirements

- Python 3.9+
- `pip install openai python-dotenv matplotlib numpy`
- An [OpenRouter](https://openrouter.ai) API key

### Setup

```bash
git clone https://github.com/arbaz-surti/etcg-supplementary
cd etcg-supplementary
cp .env.template .env
# Add your OpenRouter API key to .env
pip install openai python-dotenv matplotlib numpy
```

### Run the ETCG charter generator

```bash
python scripts/etcg_tool.py
# Outputs: data/etcg-results.json
```

### Run the baseline generator

```bash
python scripts/etcg_baseline_tool.py
# Outputs: data/etcg-baseline-results.json
```

### Score the generated charters

```bash
python scripts/etcg_score.py
# Reads:   data/etcg-results.json + data/etcg-baseline-results.json
# Outputs: data/etcg-scores.json
```

### Regenerate paper figures

```bash
python scripts/generate_figures.py
# Reads:   data/etcg-scores.json
# Outputs: figures/figure-02-boxplot.pdf
#          figures/figure-03-radar.pdf
#          figures/figure-04-barchart.pdf
```

---

## Evaluation Design

| Parameter | Value |
|-----------|-------|
| Specifications | 25 (SPEC-01–25) |
| Domains | Restaurant technology, healthcare, logistics |
| Charters per condition | 125 (5 per spec × 25 specs) |
| Rubric dimensions | Specificity, Testability, Risk Coverage, Clarity, Actionability |
| Scoring scale | 1–3 per dimension (max 15 per charter) |
| Scorer model | GPT-4o at temperature 0 |
| IRR sample | 37 charters, independent human reviewer |
| IRR range (κ_w) | 0.79–0.91 |

---

## Key Results

| Condition | Mean Score | SD |
|-----------|------------|-----|
| ETCG | 95.47% | 9.79% |
| Baseline | 92.58% | 14.51% |

Cohen's *d* = 0.23 (small effect). ETCG advantage concentrated in Specificity,
Risk Coverage, and Actionability — dimensions directly mapped to the structured
output schema. On structured specifications (SPEC-19–25), ETCG achieves
99.81% ± 1.13%.

---

## Licences

- **Data** (`data/`): [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)
- **Code** (`scripts/`): [MIT](LICENSE-CODE)

---

## Citation

Citation details will be added upon publication.
