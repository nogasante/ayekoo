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

## Quick start

```bash
# fetch the weights (idempotent, verifies SHA256)
bash download_model.sh

# profile locally
adtc-profiler run --submission . --mode participant --output submission.json --skip-accuracy
```

`download_model.sh` needs no credentials and verifies both file size and SHA256 before promoting the download into place.

## Repository contents

```text
├── metadata.json        submission claims — domain, model, test prompts
├── download_model.sh    fetches + verifies the GGUF into model/
├── REPORT.md            technical writeup
└── model/               weights land here; never committed
```

## License

GPL v3 — see [LICENSE](LICENSE). The base model weights are Apache 2.0, per [Qwen2.5-0.5B-Instruct](https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct).
