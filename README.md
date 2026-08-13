# Ayekoo

**An offline farming assistant for Ghanaian farmers. Runs entirely on an 8 GB laptop — no internet, no cloud, no subscription.**

Submission to the [Africa Deep Tech Challenge 2026](https://adtc-2026.devpost.com) — Laptop LLM track, `agriculture` domain.

---

*Ayekoo* is what you say to someone doing hard work — the greeting a farmer hears coming back from the farm. That is who this is built for.

The assistant answers practical Ghanaian farming questions: when to plant, what is eating the crop, what inputs cost in cedis, how to store a harvest. After the weights are fetched once, it never touches the network again.

**A note on language:** *Ayekoo* is an Akan greeting, but the assistant answers in **English**. That is deliberate. The localisation here is in the knowledge, not the interface — real Ghanaian crops, real cedi prices, the real season structure including harmattan and the coastal/northern split.

## How it works

A small quantized language model paired with local retrieval over a curated corpus of Ghanaian agricultural knowledge.

| | |
|---|---|
| Base model | [Qwen2.5-0.5B-Instruct](https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF) |
| Quantization | GGUF `Q4_K_M` |
| Runtime | `llama.cpp` |
| Weights | [`nogasante/ayekoo-gguf`](https://huggingface.co/nogasante/ayekoo-gguf) |
| Peak RSS | ~0.5 GB against the 7 GB ceiling |

The model does not answer from its own parameters — it answers from retrieved corpus passages. Remove the corpus and Ayekoo stops being useful, which is the point: **local knowledge, not model size, is what makes the answers right.**

The method is continental; the corpus is Ghanaian because that is the only honest way to build one in the time available. Swap the corpus for a Kenyan or Nigerian one and the same system serves those farmers.

## How answers are produced

```text
question
   ↓
embed with bge-small (llama.cpp)      ─┐
   ↓                                   │  both run locally,
hybrid retrieval over 8,535 chunks     │  no network, ever
   dense (cosine) + BM25, fused        │
   ↓                                   │
top passages + their attributions      │
   ↓                                   │
Qwen2.5-0.5B via llama-server         ─┘
   ↓
answer, citing [1] [2] by source
```

**The model is not the source of truth — the corpus is.** The model's only job is to read retrieved passages and say what they contain, in plain language, naming the source. If retrieval finds nothing relevant, Ayekoo says *"My sources do not cover this"* rather than guessing. A small model asked an unsupported question will invent a fluent, confident, wrong answer; an admitted gap is worth more than that.

Retrieval is deliberately **hybrid**. Dense embeddings match how a farmer phrases a question ("my cassava leaves are curling") against how a manual writes it ("cassava mosaic disease causes leaf distortion"). BM25 catches what embeddings blur — exact strings like `Obatanpa`, `NPK 15-15-15`, `75cm`. Agronomy answers live or die on those, so a purely semantic index would be the wrong choice here.

Where a Ghanaian and a regional source both match, the Ghanaian one is preferred; regional passages are labelled as such in the answer.

## Quick start

```bash
# 1. fetch both models (idempotent, verifies size + SHA256)
bash download_model.sh

# 2. start the generation server
llama-server -m model/qwen2.5-0.5b-instruct-q4_k_m.gguf -c 4096 -t 4 --port 8080

# 3. ask a question
python -m ayekoo.ask "When should I plant maize in the Northern Region?"
```

For several questions in a row, `python -m ayekoo.ask --repl` loads the models once and keeps them resident. If `llama-server` is not running, `ask.py` falls back to generating in-process.

The index is committed, so nothing needs re-embedding. To rebuild it after changing the corpus:

```bash
python corpus/fetch_sources.py     # refetch sources listed in corpus/sources.yaml
python -m ayekoo.index             # re-chunk and re-embed (~15 min on 4 cores)
python -m tests.test_grounding     # prove answers come from the corpus
```

## Repository contents

```text
├── metadata.json        submission claims — domain, model, test prompts
├── download_model.sh    fetches + verifies both GGUFs into model/
├── REPORT.md            technical writeup
├── ayekoo/
│   ├── chunker.py       splits sources into chunks that carry provenance
│   ├── index.py         embeds chunks, writes the index
│   ├── retrieve.py      hybrid dense + BM25 retrieval
│   ├── aliases.py       local crop, pest and symptom names → corpus terms
│   ├── extractive.py    quotes sources verbatim where exactness matters
│   ├── banned.py        blocks pesticides banned in Ghana
│   ├── verify.py        checks an answer's numbers and months against its sources
│   └── ask.py           grounded, cited answering
├── corpus/
│   ├── sources.yaml     provenance record for every document
│   ├── fetch_sources.py downloads and extracts them
│   └── text/            extracted text — this is the corpus, and it is committed
├── index/               chunks + vectors, committed so it works offline
├── tests/               grounding and refusal tests
└── model/               weights land here; never committed
```

## License

GPL v3 — see [LICENSE](LICENSE). The base model weights are Apache 2.0, per [Qwen2.5-0.5B-Instruct](https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct).
